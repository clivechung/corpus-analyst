# corpus-analyst (Multi-Domain Containerized RAG Platform)

A containerized, horizontally scalable, zero-vectorDB corpus analysis and Retrieval-Augmented Generation (RAG) platform powered by DuckDB Lakehouse, Pluggable Lakehouse Storage (LocalFS / Cloud Azure Blob), LangGraph, and Ragas.

## Overview & Motivation

Enterprises and researchers increasingly rely on Retrieval-Augmented Generation (RAG) to perform deep document analysis across highly specialized domains—such as SEC EDGAR financial filings (10-K, 10-Q, 8-K), technical manuals, and complex literary corpora. However, conventional RAG architectures built on standalone, proprietary vector databases and simplistic document splitters introduce critical operational and architectural challenges:

- **Vector Database Sprawl & Operational Overhead**: Dedicated vector databases (e.g., Pinecone, Milvus, Qdrant) introduce steep infrastructure costs, complex cluster management, vendor lock-in, and synchronization lag between the primary data lake and the vector index.
- **Loss of Structural & Tabular Fidelity**: Standard fixed-character token splitters naively shred complex tabular layouts (financial balance sheets, income statements) and hierarchical document sections, destroying quantitative context and causing hallucinations in analytical queries.
- **Static Single-Domain Embeddings**: Generic, one-size-fits-all embedding models fail to capture the nuanced domain vocabularies required for deep document research (e.g., specialized accounting terminology in 10-Ks versus narrative prose in literature).
- **Single-Host & Scalability Bottlenecks**: Tightly coupled ingestion and retrieval pipelines running in monolithic setups lack horizontal elasticity, causing ingestion spikes to degrade query responsiveness and blocking high-availability scaling.
- **Lack of Agentic Reasoning & Evaluation Quality Gates**: Naive single-shot retrieval cannot handle complex multi-hop or comparative questions (e.g., cross-year margin comparisons), and the absence of automated CI/CD evaluation leads to undetected retrieval regressions.

**corpus-analyst** solves these challenges by providing a **centralized, containerized, zero-vectorDB data lakehouse architecture** powered by **in-process DuckDB vector scanning over Hive-partitioned Parquet files**, **adaptive structural chunking via Unstructured**, **pluggable domain embeddings**, and **stateless, HPA-ready microservices** orchestrated with **LangGraph** and **Ragas**.

---

## Key Capabilities & Features

- **Zero-VectorDB Data Lakehouse**: Embeddings are stored directly in Hive-partitioned columnar Parquet files (`domain={domain}/year={YYYY}/month={MM}/day={DD}/`) managed via pluggable storage backends (`LocalFS` lakehouse default, with cloud Azure Blob extension capability). Zero external vector database infrastructure required.
- **In-Process High-Performance DuckDB Vector Search**: Leverages native DuckDB vector similarity scanning with Hive partition pruning and metadata push-down predicates, delivering sub-second retrieval over local and cloud lakehouses.
- **Structural Document Parsing & Adaptive Chunking**: Uses `unstructured` to preserve document hierarchy and HTML tabular structures (`is_table = true`), coupled with an adaptive recursive token splitter bounded to 512 tokens with sliding-window overlap.
- **Pluggable Domain Embeddings**: Runtime-configurable embedding registry supporting domain-specialized models for Finance (`BAAI/bge-small-en-v1.5`, `finbert`), Literature (`all-mpnet-base-v2`), and General corpora (`bge-large-en-v1.5`).
- **Containerized Microservice Mesh**: Turnkey Docker Compose topology featuring an Nginx ingress reverse proxy, stateless FastAPI query engine (HPA-ready), background directory-watcher ingestion daemon, and an interactive Streamlit research UI.
- **Dual-Mode LLM Inference**: Grounded synthesis with traceable citations via Google Gemini (`google-genai`), with an offline Ollama local LLM fallback option.
- **Agentic Multi-Hop Reasoning (Day 2)**: LangGraph state graph with query decomposition, self-correcting relevance grading, and FlashRank cross-encoder re-ranking for multi-document comparative synthesis.
- **Automated RAG Evaluation & CI/CD Quality Gates (Day 2)**: Synthetic golden testset generation and automated evaluation CLI using Ragas measuring Faithfulness, Answer Relevancy, and Context Precision/Recall.

---

## System Architecture

```mermaid
flowchart TD
    Client[Browser / Client] -->|HTTP :80| Nginx[Nginx Ingress Proxy]

    subgraph "Docker Compose Infrastructure"
        Nginx -->|/ (Port 8501)| Streamlit[Streamlit UI Service]
        Nginx -->|/api/v1/query (Port 8000)| QueryEngine[DuckDB Query Engine API\nFastAPI / Stateless / HPA-Ready]

        IncomingDir[("Incoming Drop Directory\n(/data/incoming)")] --> IngestionRunner["Ingestion Scraper Runner\n(Watchdog / Poller)"]

        IngestionRunner -->|"1. Parse & Adaptive Split"| Chunker["Unstructured + Token Splitter"]
        Chunker -->|"2. Domain Embed"| Transformer["Pluggable Embedder\n(Finance / Literature / General)"]
        Transformer -->|"3. Hive Partition"| ParquetWriter["Parquet Sink\nyear=YYYY/month=MM/day=DD"]

        ParquetWriter --> LocalLake[("Pluggable Lakehouse Storage\n(LocalFS: /data/lake / Cloud Azure Blob)")]

        LocalLake -.->|Read-Only Shared Mount (:ro)| QueryEngine

        QueryEngine -->|"Day 1: Direct Gemini\nDay 2: LangGraph Agent"| LLM["Gemini API (google-genai) /\nDay 2: Local Ollama"]
        Streamlit -->|HTTP REST| QueryEngine
    end

    subgraph "Day 2 Evaluation & Tooling"
        LocalMount --> RagasRunner["Ragas Golden Testset Generator & Evaluator"]
        RagasRunner --> MetricsDashboard[("Evaluation Metrics\nFaithfulness, Relevancy, Precision")]
    end
```

---

## Implementation Roadmap & Feature Progress

> Detailed specifications, deliverables, and test criteria are tracked in [feature-list.md](file:///home/cc/ws/corpus-analyst/feature-list.md) and [corpus-analyst-prd.md](file:///home/cc/ws/corpus-analyst/corpus-analyst-prd.md).

### Phase Status Overview

- [x] **Phase 1: Initial Directory Structure & Core Scaffolding** (2/2 features completed)
- [x] **Phase 2: Basic Services in Compose** (4/4 features completed)
- [ ] **Phase 3: Ingest Path** (3/4 features completed)
- [ ] **Phase 4: Chunk (Parsing & Adaptive Splitting)** (0/2 features completed)
- [ ] **Phase 5: Embedding & Lakehouse Storage** (0/3 features completed)
- [ ] **Phase 6: Retrieval, Query Engine & Serving** (0/8 features completed)
- [ ] **Phase 7: Agentic Orchestration & Re-Ranking (Day 2)** (0/4 features completed)
- [ ] **Phase 8: Evaluation & CI/CD Quality Gate (Day 2)** (0/2 features completed)

---

### Detailed Feature Checklist

#### Phase 1: Initial Directory Structure & Core Scaffolding
- [x] `FND-01`: **Workspace Scaffolding & Directory Setup** — Modular directory layout (`src/`, `docker/`, `config/`, `data/`, `ui/`, `tests/`), `.env.example`, `.dockerignore`, and package management via `pyproject.toml`.
- [x] `FND-02`: **Shared Pydantic Schemas & Settings Core** — Common data contracts (`Chunk`, `DocumentMetadata`, `QueryRequest`, `QueryResponse`, `RetrievedContextChunk`) and unified configuration loader (`config.py`, `config.yaml`).

#### Phase 2: Basic Services in Compose
- [x] `INF-01`: **Multi-Container Docker Compose Topology** — 4-service orchestration mesh (`nginx`, `ingestion-runner`, `query-engine`, `streamlit`).
- [x] `INF-02`: **Nginx Ingress Reverse Proxy & WebSockets** — Port 80 ingress proxy with WebSocket upgrades for Streamlit and unified `/health` route.
- [x] `EMB-02`: **Persistent Model Cache Volume** — Shared Docker volume `model_cache` mounted to `/root/.cache/huggingface` to eliminate redundant weight downloads.
- [x] `LAK-02`: **Pluggable Lakehouse Storage Backend** — Extensible `StorageBackendProtocol` with high-performance `LocalStorageBackend` over `./data/lake` and future cloud Azure Blob Storage adapter.

#### Phase 3: Ingest Path
- [x] `ING-01`: **Automated Drop-Directory Watcher** — Background daemon using `watchdog` monitoring `/data/incoming` with complete write detection.
- [x] `ING-02`: **Automated SEC EDGAR Downloader** — Fetcher for 10-K, 10-Q, and 8-K filings with SEC-compliant User-Agent headers and rate limiting.
- [x] `ING-05`: **Processing Lifecycle & Dead-Letter Handling** — Atomic moves to `/data/processed/` or `/data/failed/` with structured error trace logging.
- [ ] `UI-02`: **Document Ingestion Monitor & Manual Trigger** — Streamlit UI for drag-and-drop file uploads, queue status inspection, and on-demand SEC download triggers.
- [x] `UI-02`: **Document Ingestion Monitor & Manual Trigger** — Professional Quant Trading Floor Streamlit interface featuring Bloomberg/Refinitiv Obsidian & Amber aesthetics, real-time queue telemetry HUD, order-ticket SEC EDGAR requisition, drag-and-drop intake dropbox with SHA-256 validation, and dead-letter quarantine triage.

#### Phase 4: Chunk (Parsing & Adaptive Splitting)
- [x] `ING-03`: **Structural Parsing & Table Preservation** — Document element extraction via `unstructured`, preserving headings, sections, and HTML table representations (`is_table = true`).
- [x] `ING-04`: **Secondary Recursive Token Splitter** — Strict token bounding (`MAX_CHUNK_TOKENS=512`) with 64-token sliding window overlap and parent lineage tracking.

#### Phase 5: Embedding & Lakehouse Storage
- [ ] `EMB-01`: **Dynamic Domain Embedding Registry** — Pluggable runtime registry supporting Finance (`bge-small-en-v1.5`, `finbert`), Literature (`all-mpnet-base-v2`), and General models.
- [ ] `LAK-01`: **Hive-Partitioned Parquet Sink** — Columnar PyArrow sink writing to `/data/lake/domain={domain}/year={YYYY}/month={MM}/day={DD}/` with dense vector arrays.
- [ ] `LAK-02s`: **Parquet Lakehouse Storage Pipeline** — Pluggable storage pipeline writing partitioned Parquet chunks to LocalFS (`corpus-lake` root) with cloud Azure Blob extension capability.

#### Phase 6: Retrieval & Serving (DuckDB Query Engine)
- [ ] `QRY-01`: **Native DuckDB Parquet Vector Search** — In-process vector similarity search directly over Parquet files via `array_cosine_similarity`.
- [ ] `QRY-02`: **Hive Partition Push-down Predicate Filtering** — Folder pruning on `domain`, `year`, `month`, `day` and metadata predicates (`filing_date`, `is_table`).
- [ ] `QRY-03`: **Stateless & HPA-Ready REST API** — FastAPI endpoints (`POST /api/v1/query`, `POST /api/v1/search`, `GET /healthz`) with concurrency-safe read connections.
- [ ] `LLM-01`: **Google Gemini Cloud Synthesis** — Grounded synthesis using `google-genai` SDK with strict context attribution and traceable citations.
- [ ] `LLM-02`: **Ollama Local LLM Fallback** — Local inference alternative (`qwen2.5:7b`, `llama3.2`) matching cloud schema and citation contracts.
- [ ] `UI-01`: **Interactive Research Assistant & Citations** — Streamlit chat interface with expandable citation cards (source file, section, similarity score, exact text).
- [ ] `UI-03`: **Parquet Lakehouse Explorer & SQL Console** — Interactive partition browser, Parquet schema inspector, and embedded DuckDB SQL console.
- [ ] `UI-04`: **Domain Profile & Model Switcher** — Sidebar controls for dynamic domain switching and retrieval hyperparameter tuning.

#### Phase 7: Agentic Orchestration & Re-Ranking (Day 2)
- [ ] `AGT-01`: **FlashRank / Cross-Encoder Re-Ranking** — Two-stage precision ranking (Top 50 candidates $\to$ Top 5 high-precision chunks).
- [ ] `AGT-02`: **LangGraph Multi-Hop Query Decomposition** — Multi-hop state graph decomposing complex comparative questions into sub-queries.
- [ ] `AGT-03`: **Self-Correction Relevance Grading Loop** — Autonomous evaluation node assessing context sufficiency and triggering query rewrites.
- [ ] `AGT-04`: **Multi-Document Comparative Synthesis** — Cross-document synthesis fusing disparate filings into structured comparative reports.

#### Phase 8: Evaluation & CI/CD Quality Gate (Day 2)
- [ ] `EVL-01`: **Synthetic Golden Testset Generator** — Ragas-powered testset generator creating 30–50 domain QA pairs across diverse reasoning evolutions.
- [ ] `EVL-02`: **Automated RAG Quality Gate & CI/CD CLI** — Evaluation CLI (`sec-rag eval`) computing Faithfulness, Answer Relevancy, and Context Precision/Recall against target thresholds.

---

## Quickstart & Usage Guide

### 1. Environment Setup

Copy the example environment configuration:
```bash
cp .env.example .env
```
*(Optional)* Add your `GEMINI_API_KEY` in `.env` if you want to test cloud LLM synthesis, or leave the default settings to use local Ollama / mock synthesis.

### 2. Spinning Up the Platform (Docker Compose)

Launch all 4 microservices with Docker Compose:
```bash
docker compose up -d --build
```

Verify that all services are up and healthy:
```bash
docker compose ps
```

Expected output:
```
NAME               IMAGE                             STATUS                   PORTS
ingestion-runner   corpus-analyst-ingestion-runner   Up (healthy)             
nginx-ingress      nginx:alpine                      Up (healthy)             0.0.0.0:80->80/tcp
query-engine       corpus-analyst-query-engine       Up (healthy)             0.0.0.0:8000->8000/tcp
streamlit          corpus-analyst-streamlit          Up (healthy)             0.0.0.0:8501->8501/tcp
```

To view live logs from any service:
```bash
# Follow all container logs
docker compose logs -f

# Follow the ingestion daemon runner
docker logs -f ingestion-runner
```

### 3. Accessing the Streamlit UI & APIs

Once the containers are running, access the interfaces:

| Service / Interface | URL | Description |
| :--- | :--- | :--- |
| **Streamlit Research UI (via Ingress)** | [**http://localhost**](http://localhost) | Main unified dashboard (Chat, Ingestion Monitor, Lakehouse Explorer, Settings). |
| **Streamlit Research UI (Direct Port)** | [**http://localhost:8501**](http://localhost:8501) | Direct UI port access. |
| **Query Engine REST API Docs** | [**http://localhost:8000/docs**](http://localhost:8000/docs) | Interactive OpenAPI (Swagger) documentation. |
| **Query Engine Health Endpoint** | [**http://localhost/api/v1/health**](http://localhost/api/v1/health) | Query engine liveness and metadata probe via Ingress. |
| **Nginx Ingress Health Probe** | [**http://localhost/health**](http://localhost/health) | Gateway health check probe (`200 OK`). |

### 4. File Drop for Document Ingestion

You can ingest documents into the platform in two ways:

#### Option A: Direct File Drop (Background Ingestion Watcher)
Drop raw document files (PDF, HTML, JSON, TXT) directly into the host-mounted incoming directory:
```bash
# Drop files for automated ingestion
cp path/to/sample_filing.pdf ./data/incoming/
```
The **`ingestion-runner`** daemon automatically:
1. Detects newly added files in `/data/incoming`.
2. Initiates structural parsing, adaptive chunking, and embedding.
3. Writes Hive-partitioned Parquet files into the lakehouse at `./data/lake/`.
4. Moves successfully processed files to `./data/processed/` (or `./data/failed/` if parsing errors occur).

#### Option B: Automated SEC EDGAR Downloader (CLI & Helper Script)
Fetch 10-K, 10-Q, and 8-K filings directly into `./data/incoming` with native day-granularity date filtering and built-in SEC rate-limiting ($\le 10$ req/s).

SEC EDGAR requires a compliant `User-Agent` header in the format `Sample Company Name AdminContact@domain.com`. You can provide this via the `SEC_USER_AGENT` environment variable or enter it when prompted:

```bash
# Set your SEC User-Agent header
export SEC_USER_AGENT="CorpusAnalystAdmin admin@corpus-analyst.local"

# Fetch a 10-K filing with day-granularity date range (YYYY-MM-DD):
./scripts/fetch_sec_filings.sh --ticker NVDA --form 10-K --start-date 2024-01-01 --end-date 2024-03-31

# Fetch recent 10-Q quarterly reports:
./scripts/fetch_sec_filings.sh --ticker AAPL --form 10-Q --limit 2

# Or run directly using Python CLI in container or locally:
python -m src.ingestion.sec_fetcher --ticker MSFT --form 8-K --start-date 2024-06-01 --end-date 2024-06-30
```
Downloaded documents and their companion `.meta.json` metadata sidecars are placed directly into `./data/incoming/` where the ingestion watcher detects them and initiates the processing lifecycle.

#### Option C: Drag-and-Drop via Streamlit UI
#### Option C: Quant Trading Floor Dashboard (Streamlit UI)
1. Navigate to [**http://localhost**](http://localhost) in your browser.
2. Select the **Ingestion Monitor** tab.
3. Drag and drop documents directly into the upload pane, or trigger on-demand SEC EDGAR downloads for automated ticker retrieval.
2. Select the **INGESTION MONITOR (UI-02)** tab.
3. Features available on the quant trading terminal:
   - **Queue Telemetry HUD**: Real-time KPI tiles for incoming queue depth, settled corpus volume, dead-letter count, and failure rate.
   - **SEC EDGAR Requisition Desk**: Quick-ticker selector (`NVDA`, `AAPL`, `MSFT`, `AMZN`, `GOOGL`, `META`, `TSLA`, `JPM`), form filter (`10-K`, `10-Q`, `8-K`), and day-granularity date filtering presets.
   - **Direct Intake Dropbox**: Drag-and-drop document upload (`.pdf`, `.htm`, `.html`, `.json`, `.txt`) with real-time SHA-256 calculation and companion `.meta.json` sidecar generation.
   - **Forensic Dead-Letter Drawer**: Interactive quarantine inspector with full error traceback viewing and one-click `[↺ RE-QUEUE FILE]` retry mechanism.

### 5. Querying the Corpus

#### Via Streamlit UI
Open the **Research Assistant** chat tab at [**http://localhost**](http://localhost), choose your active domain profile (`Finance`, `Literature`, or `General`), and submit your question. The assistant provides grounded answers with expandable citation cards showing exact source files, similarity scores, and excerpts.

#### Via Query Engine REST API
Send retrieval or answer generation queries directly to the query engine:
```bash
curl -X POST http://localhost/api/v1/query \
  -H "Content-Type: application/json" \
  -d '{
    "question": "What are the key risk factors described in the filings?",
    "domain": "finance",
    "top_k": 5
  }'
```

### 6. Shutting Down the Platform

To stop and remove containers cleanly:
```bash
docker compose down
```
Data in `./data/lake`, `./data/incoming`, and HuggingFace weights in the `model_cache` volume persist safely across restarts.

