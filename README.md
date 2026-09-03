# corpus-analyst (Multi-Domain Containerized RAG Platform)

A containerized, horizontally scalable, zero-vectorDB corpus analysis and Retrieval-Augmented Generation (RAG) platform powered by DuckDB Lakehouse, Azure Edge Blob, LangGraph, and Ragas.

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

- **Zero-VectorDB Data Lakehouse**: Embeddings are stored directly in Hive-partitioned columnar Parquet files (`domain={domain}/year={YYYY}/month={MM}/day={DD}/`) synced to an Azure Edge Blob / Azurite storage emulator. Zero external vector database infrastructure required.
- **In-Process High-Performance DuckDB Vector Search**: Leverages native DuckDB vector similarity scanning with Hive partition pruning and metadata push-down predicates, delivering sub-second retrieval over local and edge lakehouses.
- **Structural Document Parsing & Adaptive Chunking**: Uses `unstructured` to preserve document hierarchy and HTML tabular structures (`is_table = true`), coupled with an adaptive recursive token splitter bounded to 512 tokens with sliding-window overlap.
- **Pluggable Domain Embeddings**: Runtime-configurable embedding registry supporting domain-specialized models for Finance (`BAAI/bge-small-en-v1.5`, `finbert`), Literature (`all-mpnet-base-v2`), and General corpora (`bge-large-en-v1.5`).
- **Containerized Microservice Mesh**: Turnkey Docker Compose topology featuring an Nginx ingress reverse proxy, stateless FastAPI query engine (HPA-ready), background directory-watcher ingestion daemon, Azurite edge blob emulator, and an interactive Streamlit research UI.
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

        ParquetWriter --> EdgeBlob[("Azure Edge Blob / Azurite Container\n(Storage Emulator)")]
        ParquetWriter --> LocalMount[("Shared Lakehouse Volume\n(/data/lake)")]

        LocalMount -.->|Read-Only Shared Mount / Blob Sync| QueryEngine
        EdgeBlob -.->|Blob Sync / Shared Lakehouse| QueryEngine

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

> Detailed specifications, deliverables, and test criteria are tracked in [feature-list.md](file:///home/cc/ws/corpus-analyst/feature-list.md) and [ducklake-rag-prd.md](file:///home/cc/ws/corpus-analyst/ducklake-rag-prd.md).

### Phase Status Overview

- [ ] **Phase 1: Initial Directory Structure & Core Scaffolding** (0/2 features completed)
- [ ] **Phase 2: Basic Services in Compose** (0/4 features completed)
- [ ] **Phase 3: Ingest Path** (0/4 features completed)
- [ ] **Phase 4: Chunk (Parsing & Adaptive Splitting)** (0/2 features completed)
- [ ] **Phase 5: Embedding & Lakehouse Storage** (0/3 features completed)
- [ ] **Phase 6: Retrieval, Query Engine & Serving** (0/8 features completed)
- [ ] **Phase 7: Agentic Orchestration & Re-Ranking (Day 2)** (0/4 features completed)
- [ ] **Phase 8: Evaluation & CI/CD Quality Gate (Day 2)** (0/2 features completed)

---

### Detailed Feature Checklist

#### Phase 1: Initial Directory Structure & Core Scaffolding
- [ ] `FND-01`: **Workspace Scaffolding & Directory Setup** — Modular directory layout (`src/`, `docker/`, `config/`, `data/`, `ui/`, `tests/`), `.env.example`, `.dockerignore`, and package management via `pyproject.toml`.
- [ ] `FND-02`: **Shared Pydantic Schemas & Settings Core** — Common data contracts (`Chunk`, `DocumentMetadata`, `QueryRequest`, `QueryResponse`, `RetrievedContextChunk`) and unified configuration loader (`config.py`, `config.yaml`).

#### Phase 2: Basic Services in Compose
- [ ] `INF-01`: **Multi-Container Docker Compose Topology** — 5-service orchestration mesh (`nginx`, `edgeblob`, `ingestion-runner`, `query-engine`, `streamlit`).
- [ ] `INF-02`: **Nginx Ingress Reverse Proxy & WebSockets** — Port 80 ingress proxy with WebSocket upgrades for Streamlit and unified `/health` route.
- [ ] `EMB-02`: **Persistent Model Cache Volume** — Shared Docker volume `model_cache` mounted to `/root/.cache/huggingface` to eliminate redundant weight downloads.
- [ ] `LAK-02`: **Azure Edge Blob / Azurite Emulator Provisioning** — Local Azurite blob emulator container initialization and persistent `sec-filings-lake` container.

#### Phase 3: Ingest Path
- [ ] `ING-01`: **Automated Drop-Directory Watcher** — Background daemon using `watchdog` monitoring `/data/incoming` with complete write detection.
- [ ] `ING-02`: **Automated SEC EDGAR Downloader** — Fetcher for 10-K, 10-Q, and 8-K filings with SEC-compliant User-Agent headers and rate limiting.
- [ ] `ING-05`: **Processing Lifecycle & Dead-Letter Handling** — Atomic moves to `/data/processed/` or `/data/failed/` with structured error trace logging.
- [ ] `UI-02`: **Document Ingestion Monitor & Manual Trigger** — Streamlit UI for drag-and-drop file uploads, queue status inspection, and on-demand SEC download triggers.

#### Phase 4: Chunk (Parsing & Adaptive Splitting)
- [ ] `ING-03`: **Structural Parsing & Table Preservation** — Document element extraction via `unstructured`, preserving headings, sections, and HTML table representations (`is_table = true`).
- [ ] `ING-04`: **Secondary Recursive Token Splitter** — Strict token bounding (`MAX_CHUNK_TOKENS=512`) with 64-token sliding window overlap and parent lineage tracking.

#### Phase 5: Embedding & Lakehouse Storage
- [ ] `EMB-01`: **Dynamic Domain Embedding Registry** — Pluggable runtime registry supporting Finance (`bge-small-en-v1.5`, `finbert`), Literature (`all-mpnet-base-v2`), and General models.
- [ ] `LAK-01`: **Hive-Partitioned Parquet Sink** — Columnar PyArrow sink writing to `/data/lake/domain={domain}/year={YYYY}/month={MM}/day={DD}/` with dense vector arrays.
- [ ] `LAK-02s`: **Parquet Edge Blob Sync Pipeline** — Blob synchronization pipeline pushing partitioned Parquet chunks to Azurite Edge Blob (`sec-filings-lake`).

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
