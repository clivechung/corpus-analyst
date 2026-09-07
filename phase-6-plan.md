# Implementation Plan — Phase 6: Stateless DuckDB Vector Retrieval, Partition Pruning, REST API & Quant UI (QRY-01, QRY-02, QRY-03, UI-01, UI-03, UI-04)

Implement and integrate the core retrieval, search, partition pruning, and research UI components for the **corpus-analyst** platform, satisfying **`QRY-01`**, **`QRY-02`**, **`QRY-03`**, **`UI-01`**, **`UI-03`**, and **`UI-04`** as specified in [`feature-list.md:L139-L155`](file:///home/cc/ws/corpus-analyst/feature-list.md#L139-L155) and [`corpus-analyst-prd.md:L166-L215`](file:///home/cc/ws/corpus-analyst/corpus-analyst-prd.md#L166-L215).

---

## 1. Architectural Overview & Design Decisions

```
+----------------------------------------------------------------------------------------------------+
|                                    Streamlit Research Dashboard                                    |
|  +--------------------------------+  +--------------------------------+  +-----------------------+ |
|  |  Research Chat & Citations     |  |  Lakehouse Explorer & SQL      |  |  Sidebar Controls     | |
|  |  (UI-01: Expandable Cards)     |  |  (UI-03: DuckDB SQL Console)   |  |  (UI-04: Domain, K)   | |
|  +--------------------------------+  +--------------------------------+  +-----------------------+ |
+--------------------------------------------------+-------------------------------------------------+
                                                   | HTTP (httpx)
                                                   v
+----------------------------------------------------------------------------------------------------+
|                         Stateless FastAPI Query Engine (QRY-03, HPA-Ready)                         |
|  +-----------------------------+  +---------------------------------+  +-------------------------+ |
|  | POST /api/v1/search         |  | POST /api/v1/query              |  | GET /healthz            | |
|  | (Raw Candidates & Scores)   |  | (Grounded Synthesis & Citations)|  | (Readiness Probe)       | |
|  +--------------+--------------+  +----------------+----------------+  +-------------------------+ |
+-----------------|----------------------------------|-----------------------------------------------+
                  |                                  |
                  +-----------------+----------------+
                                    |
                                    v
+----------------------------------------------------------------------------------------------------+
|                      DuckDB Lakehouse Client (QRY-01: Vector Search, QRY-02: Pruning)              |
|  1. Embed Query Text -> Dense Vector via EmbeddingRegistry (dim: 384/768/1024)                     |
|  2. Build Dynamic SQL with Hive Pruning & Metadata Filters (domain, year, filing_date, is_table)   |
|  3. Execute read_parquet('/data/lake/domain=.../**/*.parquet', hive_partitioning=true)             |
|  4. SIMD array_cosine_similarity(embedding::FLOAT[dim], ?::FLOAT[dim]) with LIMIT top_k           |
+----------------------------------------------------------------------------------------------------+
                                    |
                                    v
+----------------------------------------------------------------------------------------------------+
|                           Hive-Partitioned Parquet Lakehouse (/data/lake)                          |
|  /data/lake/domain={finance|literature|general}/year={YYYY}/month={MM}/day={DD}/*.snappy.parquet   |
+----------------------------------------------------------------------------------------------------+
```

### 1.1 Native DuckDB In-Process Vector Search (`QRY-01`)
- **Zero Dedicated Vector Database**:
  - Traditional RAG architectures introduce operational complexity by requiring external vector databases (Milvus, Pinecone, Qdrant, Weaviate), causing sync drift between source text and vector index.
  - Corpus Analyst executes in-process vector similarity search directly over Snappy-compressed Parquet files using DuckDB's vectorized execution engine.
- **Cosine Similarity Execution**:
  - Query embeddings are generated on-the-fly using the domain's configured embedder (`BAAI/bge-small-en-v1.5` for `finance`, `all-mpnet-base-v2` for `literature`, `bge-large-en-v1.5` for `general`) via `EmbeddingRegistry`.
  - Vectors in Parquet are stored as `embedding: LIST<FLOAT32>`.
  - DuckDB calculates cosine similarity using:
    ```sql
    array_cosine_similarity(embedding::FLOAT[{dim}], ?::FLOAT[{dim}]) AS similarity_score
    ```
    with fallback to `list_cosine_similarity(embedding, ?::FLOAT[])` if dynamically typed arrays are encountered.
  - Results are filtered by `similarity_score >= $threshold` and ordered by `similarity_score DESC` with `LIMIT $top_k`.
- **Handling Empty Lake & Missing Files**:
  - If no Parquet files exist for a domain or partition, the client detects the empty glob before executing DuckDB, returning an empty candidate list `[]` without crashing.

### 1.2 Hive Partition Push-down Pruning & Metadata Filtering (`QRY-02`)
- **Hive Directory Pruning**:
  - The lakehouse directory layout follows:
    `/data/lake/domain={domain}/year={YYYY}/month={MM}/day={DD}/*.parquet`
  - DuckDB's `read_parquet(path, hive_partitioning=true)` treats `domain`, `year`, `month`, and `day` as virtual partition keys.
  - DuckDB's query optimizer inspects Parquet footer metadata and directory names before reading file data, completely skipping non-matching files (e.g. `Scanning Files: 1/120`).
- **Metadata Predicate Filtering**:
  - In addition to directory pruning, queries push down scalar predicates directly into the Parquet reader:
    - `domain = $domain` (prunes entire domain trees)
    - `form_type = $form_type` (filters e.g. `10-K`, `10-Q`, `8-K`)
    - `filing_date >= $start_date` AND `filing_date <= $end_date`
    - `is_table = true` (when `is_table_only=True`)
  - **Performance Advantage**: Predicates are evaluated by DuckDB **prior** to running `array_cosine_similarity`, reducing vector distance calculations from $O(N)$ across the entire lake to $O(M)$ over strictly matching candidate chunks.
  - Parameterized query generation avoids SQL injection and allows DuckDB to compile prepared statements efficiently.

### 1.3 Stateless & HPA-Ready REST API (`QRY-03`)
- **Zero Database Write Locks**:
  - The Query Engine runs DuckDB in in-memory / read-only mode (`duckdb.connect(database=':memory:')` with `con.cursor()` per request).
  - Multiple horizontal pods (Kubernetes HPA or Docker Compose replicas) mount the shared Parquet lake volume (`/data/lake`) read-only without lock contention.
- **REST API Endpoints**:
  - `POST /api/v1/search`:
    - Accepts `QueryRequest` (question, domain, top_k, form_type, date filters, is_table_only, similarity_threshold).
    - Embeds query string into dense vector.
    - Executes DuckDB vector query with push-down predicates.
    - Returns `list[RetrievedContextChunk]`.
  - `POST /api/v1/query`:
    - Accepts `QueryRequest`.
    - Retrieves top candidate chunks via DuckDB client.
    - Extracts grounded citations with source filename, section, score, and excerpt.
    - Synthesizes grounded response attributing context to citations.
    - Returns complete `QueryResponse` (question, answer, domain, retrieved_chunks, citations, latency_ms, model_used).
  - `GET /healthz`:
    - Fast liveness probe for container orchestrators.
  - `GET /api/v1/health`:
    - Detailed readiness probe verifying DuckDB connectivity, registered domain profiles, and Parquet lake status.

### 1.4 Interactive Quant Research UI (`UI-01`, `UI-03`, `UI-04`)
- **UI-01: Research Assistant & Expandable Citations (`ui/components/chat.py`)**:
  - Natural language chat stream with trading floor obsidian aesthetic.
  - Renders assistant answers backed by expandable citation cards showing:
    - Source filename (e.g., `NVDA_10-K_20240221.htm`).
    - Document section / Item title (e.g., `Item 1A - Risk Factors`).
    - Cosine similarity score badge (green for high confidence $>0.80$, amber for medium $>0.60$).
    - Tabular chunk indicator badge (`[TABLE]` vs `[TEXT]`).
    - Exact grounding excerpt with highlighted keywords.
    - Deep chunk inspection drawer showing full metadata payload.
- **UI-03: Lakehouse Parquet Explorer & SQL Console (`ui/components/lake_explorer.py`)**:
  - **Hive Partition Tree Browser**: Live directory navigation of `/data/lake` displaying partition hierarchies, file counts, file sizes, and chunk statistics.
  - **Parquet Schema & Metadata Inspector**: Displays column types, nullability, and compression info for selected Parquet files.
  - **Embedded DuckDB SQL Console**: Allows analysts and quants to run interactive ad-hoc SQL queries directly over the Parquet lake (e.g., `SELECT domain, count(*) FROM read_parquet('/data/lake/**/*.parquet') GROUP BY domain`).
  - Includes pre-canned query templates ("Chunk Distribution by Domain & Year", "Tabular Financial Metrics", "Vector Null Checks").
- **UI-04: Domain Profile & Model Switcher (`ui/app.py` Sidebar)**:
  - Domain switcher (`finance`, `literature`, `general`).
  - Retrieval hyperparameter controls:
    - Top-K slider (1 to 50, default 5).
    - Cosine similarity threshold slider (0.0 to 1.0, default 0.0).
    - Date range filter (start date / end date date-pickers).
    - Tabular-only filter toggle.
    - Form type filter (`All`, `10-K`, `10-Q`, `8-K`, `BOOK`, `MISC`).

---

## 2. Pre-Agreed Testing Seams (TDD)

In compliance with the project's [TDD skill](file:///home/cc/ws/corpus-analyst/.agents/skills/tdd/SKILL.md), testing is anchored at pre-agreed public boundaries:

| Seam ID | Seam Target | Verification Scope |
| :--- | :--- | :--- |
| **`SEAM-DUCKDB-RETRIEVER`** | [`src/query_engine/duckdb_client.py`](file:///home/cc/ws/corpus-analyst/src/query_engine/duckdb_client.py) | Validates `DuckDBLakehouseClient`: (1) vector similarity ranking with `array_cosine_similarity` over Parquet files, (2) Hive partition directory pruning (`domain`, `year`, `month`, `day`), (3) metadata predicate pushdown (`form_type`, `filing_date`, `is_table`), (4) similarity threshold filtering, (5) top-K truncation, (6) dimension compatibility between query vector and Parquet embeddings, and (7) empty lake / zero-result handling without exceptions. |
| **`SEAM-QUERY-API`** | [`src/query_engine/main.py`](file:///home/cc/ws/corpus-analyst/src/query_engine/main.py) | Validates FastAPI endpoints via `TestClient`: (1) `POST /api/v1/search` returning validated `list[RetrievedContextChunk]`, (2) `POST /api/v1/query` returning `QueryResponse` with grounded citations, (3) `GET /healthz` and `GET /api/v1/health` probes, (4) input validation (e.g. invalid top-K returning 422), (5) dependency injection overrides for test isolation, and (6) request latency reporting. |
| **`SEAM-UI-COMPONENTS`** | [`ui/components/chat.py`](file:///home/cc/ws/corpus-analyst/ui/components/chat.py), [`ui/components/lake_explorer.py`](file:///home/cc/ws/corpus-analyst/ui/components/lake_explorer.py) | Validates presentation helpers and data contracts: (1) citation card rendering logic, (2) score badge styling thresholds, (3) partition tree calculation over filesystem, and (4) safe SQL console execution (read-only enforcement, error trapping). |
| **`SEAM-E2E-RETRIEVAL`** | [`tests/test_query_engine_api.py`](file:///home/cc/ws/corpus-analyst/tests/test_query_engine_api.py) + [`tests/test_duckdb_client.py`](file:///home/cc/ws/corpus-analyst/tests/test_duckdb_client.py) | Full integration loop: synthetic chunks ingested via `ParquetSink` are queried through `DuckDBLakehouseClient` and `POST /api/v1/query`, returning ranked chunks matching the expected cosine similarity order within SLA (<2s). |

---

## 3. Proposed Changes

### Query Engine Core

#### [NEW] [duckdb_client.py](file:///home/cc/ws/corpus-analyst/src/query_engine/duckdb_client.py)
- Define `DuckDBClientProtocol(Protocol)`:
  - `search(request: QueryRequest, query_vector: list[float]) -> list[RetrievedContextChunk]`
  - `execute_sql(query: str, params: list[Any] | None = None) -> tuple[list[str], list[tuple[Any, ...]]]`
  - `get_lake_stats() -> dict[str, Any]`
- Implement `DuckDBLakehouseClient`:
  - Constructor accepting `Settings` and optional database path (defaults to `:memory:`).
  - In-process connection management with per-query cursor isolation.
  - SQL query builder with parameterized predicates:
    - Path resolution: `/data/lake/domain={domain}/**/*.parquet` (or all domains if domain is empty).
    - Pruning clauses: `domain = ?`, `form_type = ?`, `filing_date >= ?`, `filing_date <= ?`, `is_table = ?`.
    - Similarity clause: `array_cosine_similarity(embedding::FLOAT[{dim}], ?::FLOAT[{dim}]) AS similarity_score`.
    - Ordering and cutoff: `WHERE similarity_score >= ? ORDER BY similarity_score DESC LIMIT ?`.
  - Maps DuckDB result rows back into validated `RetrievedContextChunk` Pydantic models.
  - Safe SQL execution method for the UI console with read-only guards (rejecting `DROP`, `DELETE`, `INSERT`, `UPDATE`, `ATTACH`).
- Factory provider `get_duckdb_client(settings: Settings | None = None) -> DuckDBLakehouseClient`.

#### [MODIFY] [main.py](file:///home/cc/ws/corpus-analyst/src/query_engine/main.py)
- Wire `DuckDBLakehouseClient` and `EmbeddingRegistry` into FastAPI dependency injection:
  - `DuckDBDep = Annotated[DuckDBLakehouseClient, Depends(get_duckdb_client)]`
  - `RegistryDep = Annotated[EmbeddingRegistry, Depends(get_embedding_registry)]`
- Update `POST /api/v1/search`:
  - Look up domain embedder from registry.
  - Embed `request.question` into query vector.
  - Delegate to `duckdb_client.search(request, query_vector)`.
  - Return `list[RetrievedContextChunk]`.
- Update `POST /api/v1/query`:
  - Execute vector search to obtain candidate chunks.
  - Construct grounded `Citation` objects from top retrieved chunks.
  - Generate grounded answer referencing citations with fallback synthesis.
  - Calculate request latency in milliseconds (`latency_ms`).
  - Return complete `QueryResponse`.
- Update `GET /api/v1/health`:
  - Verify DuckDB responsiveness and return Parquet lake summary (total files, total domains).

---

### Streamlit UI Components

#### [NEW] [chat.py](file:///home/cc/ws/corpus-analyst/ui/components/chat.py)
- Implement `render_research_chat_view(query_engine_url: str, active_domain: str, query_params: dict[str, Any])`:
  - Chat history container retaining conversational turns.
  - Form with question input, sample prompt chips ("What were NVIDIA's 2024 revenues?", "Summarize Item 1A Risk Factors", "Compare Gross Margins").
  - Execution spinner with timer.
  - Dispatches HTTP request to `POST /api/v1/query` using `httpx`.
  - Renders synthesized answer in a styled quant callout box.
  - Renders expandable citation cards:
    - Header: `Citation [i]: {source_filename} // {section} (Score: {score})`
    - Badges: `[TABLE]` / `[TEXT]`, `Form: {form_type}`, `Date: {filing_date}`
    - Excerpt blockquote.
    - JSON metadata inspector.

#### [NEW] [lake_explorer.py](file:///home/cc/ws/corpus-analyst/ui/components/lake_explorer.py)
- Implement `render_lakehouse_explorer_view(duckdb_client: DuckDBLakehouseClient | None, lake_path: str)`:
  - **Partition Telemetry Strip**: 3 KPI metric tiles (Total Parquet Files, Total Lake Size MB, Indexed Domains).
  - **Hive Partition Directory Browser**:
    - Scans `/data/lake` partition folders (`domain=*`, `year=*`, `month=*`, `day=*`).
    - Displays interactive directory hierarchy or dataframe table.
  - **Parquet Schema & Sample Data Viewer**:
    - Select partition file to inspect PyArrow/DuckDB schema and preview the first 5 records.
  - **Embedded DuckDB SQL Console**:
    - Text area for SQL queries with pre-populated templates.
    - "Execute Query" button.
    - Executes read-only queries and renders output via `st.dataframe`.
    - Execution timer and row count telemetry.

#### [MODIFY] [app.py](file:///home/cc/ws/corpus-analyst/ui/app.py)
- Update Sidebar:
  - Add retrieval control expander (`UI-04`):
    - Top-K slider (`default_top_k` from settings, range 1 to 50).
    - Similarity cutoff threshold slider (0.0 to 1.0).
    - Date range inputs (`start_date`, `end_date`).
    - "Tabular Chunks Only" checkbox toggle.
    - Form type multi-select / dropdown (`All`, `10-K`, `10-Q`, `8-K`, `BOOK`, `MISC`).
- Wire Tab 2 (`💬 RESEARCH CHAT`) to `render_research_chat_view()` from `ui/components/chat.py`.
- Wire Tab 3 (`🗄️ LAKEHOUSE EXPLORER`) to `render_lakehouse_explorer_view()` from `ui/components/lake_explorer.py`.

---

### Automated Tests (TDD)

#### [NEW] [test_duckdb_client.py](file:///home/cc/ws/corpus-analyst/tests/test_duckdb_client.py)
- Test `SEAM-DUCKDB-RETRIEVER`:
  - `test_vector_similarity_ordering`: Ingest synthetic Parquet files with known vectors $[1, 0, 0]$, $[0, 1, 0]$, $[0.7, 0.7, 0]$. Query with $[1, 0, 0]$ and verify chunks are returned in descending cosine order ($1.0 \to 0.707 \to 0.0$).
  - `test_hive_partition_pushdown_domain`: Verify search for `domain="finance"` only returns chunks from the finance partition.
  - `test_hive_partition_pushdown_dates`: Verify `start_date` and `end_date` filters correctly exclude chunks outside temporal boundaries.
  - `test_metadata_predicate_is_table`: Verify `is_table_only=True` strictly returns tabular chunks (`is_table = true`).
  - `test_metadata_predicate_form_type`: Verify filtering by `form_type="10-K"` excludes `10-Q` chunks.
  - `test_similarity_threshold_cutoff`: Verify candidates with score below cutoff are pruned.
  - `test_empty_lakehouse_returns_empty_list`: Verify querying an empty directory returns `[]` without raising errors.
  - `test_read_only_sql_console_guard`: Verify SQL console rejects mutative statements (`DROP`, `DELETE`, `UPDATE`).

#### [MODIFY] [test_query_engine_api.py](file:///home/cc/ws/corpus-analyst/tests/test_query_engine_api.py)
- Test `SEAM-QUERY-API`:
  - `test_search_endpoint_with_duckdb_retrieval`: Mock or wire local test lakehouse, assert `POST /api/v1/search` returns populated `RetrievedContextChunk` models with similarity scores.
  - `test_query_endpoint_with_citations`: Assert `POST /api/v1/query` returns grounded citations matching retrieved chunks.
  - `test_health_endpoints_verify_duckdb`: Assert `GET /healthz` and `GET /api/v1/health` return status `ok` and lake stats.

#### [NEW] [test_ui_chat_and_lake.py](file:///home/cc/ws/corpus-analyst/tests/test_ui_chat_and_lake.py)
- Test `SEAM-UI-COMPONENTS`:
  - Verify partition browser helper functions correctly parse Hive directory paths into structured hierarchy trees.
  - Verify citation badge scoring logic accurately assigns color styles.

---

## 4. Verification Plan

### Automated Tests
Run the test suite using Python virtual environment:
```bash
.venv/bin/python -m pytest tests/test_duckdb_client.py tests/test_query_engine_api.py tests/test_ui_chat_and_lake.py -v
```
Run the full test suite to guarantee zero regression:
```bash
.venv/bin/python -m pytest tests/ -v
```

### Manual Verification
1. **REST API Live Verification**:
   - Start the query engine:
     ```bash
     .venv/bin/python -m uvicorn src.query_engine.main:app --host 0.0.0.0 --port 8000
     ```
   - Query raw search candidates:
     ```bash
     curl -X POST http://localhost:8000/api/v1/search \
       -H "Content-Type: application/json" \
       -d '{"question": "What were the revenues?", "domain": "finance", "top_k": 3}'
     ```
   - Query grounded synthesis:
     ```bash
     curl -X POST http://localhost:8000/api/v1/query \
       -H "Content-Type: application/json" \
       -d '{"question": "What were the revenues?", "domain": "finance", "top_k": 3}'
     ```
2. **Streamlit UI Live Verification**:
   - Launch Streamlit UI:
     ```bash
     .venv/bin/python -m streamlit run ui/app.py --server.port 8501
     ```
   - Navigate to Tab 2 (`💬 RESEARCH CHAT`), submit sample query, and inspect expandable citation cards.
   - Navigate to Tab 3 (`🗄️ LAKEHOUSE EXPLORER`), verify partition tree visualization, inspect Parquet schema, and execute SQL query in embedded console (`SELECT domain, count(*) FROM read_parquet('/data/lake/**/*.parquet', hive_partitioning=true) GROUP BY domain`).
   - Adjust sidebar controls (`UI-04`), toggle "Tabular Only", and verify search query applies predicates.

