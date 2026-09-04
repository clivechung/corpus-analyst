# Implementation Plan — Automated Ingestion Pipeline (ING-01, ING-02, ING-05)

Build and integrate the automated document ingestion pipeline for the **corpus-analyst** platform, comprising continuous directory monitoring with complete write detection (**`ING-01`**), automated SEC EDGAR filing acquisition with rate-limiting and SEC-compliant headers (**`ING-02`**), and robust processing lifecycle management with atomic moves and dead-letter trace logging (**`ING-05`**).

---

## 1. Architectural Overview & Design Decisions

- **Decoupled Document Processing Contract (TREM: Extensible)**:
  - Features `ING-01` and `ING-05` manage the intake, write completion verification, and lifecycle transitions of documents.
  - Because structural parsing (`ING-03`) and adaptive chunking (`ING-04`) are scheduled for Phase 4, and embedding/lakehouse sink (`EMB-01`, `LAK-01`) for Phase 5, an extensible `DocumentProcessorProtocol` is introduced.
  - In Phase 3, this defaults to `DefaultDocumentProcessor`, which validates file format, extracts basic `DocumentMetadata`, verifies file readability/integrity, and records processing duration/metrics.
  - In Phase 4 and 5, the full parsing, chunking, and embedding pipeline implements this exact protocol with zero breaking changes to the watcher or lifecycle manager.
- **Continuous Directory Watcher with Complete Write Detection (`ING-01`)**:
  - `IncomingWatcher` in `src/ingestion/watcher.py` combines event-driven filesystem monitoring (`watchdog`) with a periodic polling fallback sweep (`poll_interval_seconds`) to guarantee robustness across Docker bind mounts.
  - `CompleteWriteDetector` verifies that candidate files are completely written by sampling file size and modification time over a configurable window (`write_detection_interval_seconds`, `stability_checks`) and confirming read access before dispatching to the processing pipeline.
  - Active temporary files (`*.tmp`, `*.crdownload`, `*.part`, `.*` hidden files) are automatically excluded until write completion and final rename.
  - Concurrency guard: In-progress files are tracked in `_active_files: set[Path]` to prevent duplicate processing.
- **SEC EDGAR Downloader Utility (`ING-02`)**:
  - `SecFetcher` in `src/ingestion/sec_fetcher.py` queries SEC EDGAR public endpoints using `httpx.Client` (injected for high testability).
  - **Zero-Config User-Agent Injection**: Enforces mandatory SEC-compliant `User-Agent` headers (`Name email@domain.com`) injected directly via `SEC_USER_AGENT` environment variable or `--user-agent` CLI argument, decoupling the tool from global settings models.
  - **Day-Granularity Date Filtering**: SEC EDGAR's Submissions API natively returns `filingDate` in `YYYY-MM-DD` format. The tool natively supports day-level range filtering via `--start-date YYYY-MM-DD` and `--end-date YYYY-MM-DD` in addition to fiscal `--year`.
  - Built-in `TokenBucketRateLimiter` strictly guarantees compliance with SEC's fair-access limit of $\le 10$ requests per second across all endpoints.
  - Resolves ticker symbols to CIKs via `https://www.sec.gov/files/company_tickers.json` (in-memory cached) and inspects `https://data.sec.gov/submissions/CIK{cik}.json` for `10-K`, `10-Q`, and `8-K` filings.
  - Saves downloaded filings directly into `/data/incoming/` alongside companion `.meta.json` sidecar files storing `DocumentMetadata` (`ticker`, `company_name`, `form_type`, `filing_date`, `accession_number`).
  - Provides a Typer CLI entrypoint (`python -m src.ingestion.sec_fetcher --ticker NVDA --form 10-K --start-date 2024-01-01 --end-date 2024-03-31`).
  - Accompanied by a dedicated helper bash script (`scripts/fetch_sec_filings.sh`) that interactively prompts for the SEC User-Agent if not set, forwards day-granularity date filters, and executes the downloader seamlessly via the containerized or local environment.
- **Processing Lifecycle & Dead-Letter Handling (`ING-05`)**:
  - `LifecycleManager` in `src/ingestion/lifecycle.py` transitions files through discrete states: `PENDING` $\to$ `PROCESSING` $\to$ `PROCESSED` or `FAILED`.
  - Atomically moves successfully processed files from `/data/incoming/` to `/data/processed/` using `os.replace` / `shutil.move` with collision-safe renaming (`{basename}_{timestamp}{ext}`).
  - On processing errors, atomically relocates files to `/data/failed/` and generates a structured dead-letter trace artifact `{failed_file}.error.json` containing ISO8601 timestamp, error type, message, stack trace, and document metadata.
  - Emits structured `IngestionSummary` metrics (processing time, chunk count, token count, status).

---

## 2. Pre-Agreed Testing Seams (TDD)

In alignment with the project's [TDD skill](file:///home/cc/ws/corpus-analyst/.agents/skills/tdd/SKILL.md) and Phase 2 conventions, testing is scoped strictly to pre-agreed public boundaries:

| Seam ID | Seam Target | Verification Scope |
| :--- | :--- | :--- |
| **`SEAM-WATCHER`** | `src/ingestion/watcher.py` | Validates file creation detection, complete write verification (sampling size/mtime stability over intervals), exclusion of temporary/hidden files (`.tmp`, `.*`), active file deduplication, and periodic polling fallback. |
| **`SEAM-SEC-FETCHER`** | `src/ingestion/sec_fetcher.py` | Validates SEC EDGAR company tickers CIK lookup, filing submissions search for 10-K, 10-Q, 8-K, token-bucket rate limiter compliance ($\le 10$ req/s), SEC-compliant User-Agent headers, document download to incoming dir, and sidecar metadata generation using mock HTTP transports. |
| **`SEAM-LIFECYCLE`** | `src/ingestion/lifecycle.py` | Validates atomic file relocations to `/data/processed/` upon success, moves to `/data/failed/` upon error, collision-safe filename generation, structured dead-letter `.error.json` trace logs with full stack traces, and `IngestionSummary` metric emission. |
| **`SEAM-RUNNER-INGEST`** | `src/ingestion/runner.py` | Validates `IngestionRunner` integration with `IncomingWatcher` and `LifecycleManager`, clean daemon startup, single cycle execution, and graceful termination upon OS signal. |

---

## 3. Detailed File Deliverables

### Configuration & Data Contracts
1. **`src/common/config.py`** [MODIFY]:
   - Add `WatcherSettings` sub-model (`poll_interval_seconds: float = 1.0`, `write_detection_interval_seconds: float = 1.0`, `stability_checks: int = 2`, `supported_extensions: list[str]`).
   - Wire `WatcherSettings` into `Settings` with optional environment variable overrides.
2. **`src/common/models.py`** [MODIFY]:
   - Add `IngestionStatus(str, Enum)` (`PENDING`, `PROCESSING`, `COMPLETED`, `FAILED`).
   - Add `DeadLetterRecord(BaseModel)` (`timestamp`, `source_filename`, `file_size_bytes`, `error_type`, `error_message`, `stack_trace`, `metadata`).
   - Add `IngestionSummary(BaseModel)` (`file_path`, `status`, `duration_seconds`, `chunk_count`, `token_total`, `error_message`).

### Ingestion Core Subsystem
3. **`src/ingestion/lifecycle.py`** [NEW]:
   - `DocumentProcessorProtocol` interface and `DefaultDocumentProcessor` implementation.
   - `LifecycleManager` coordinating atomic relocations to `/data/processed` or `/data/failed`, dead-letter error JSON generation, collision handling, and metrics logging.
4. **`src/ingestion/watcher.py`** [NEW]:
   - `CompleteWriteDetector` verifying size and timestamp stability over intervals and checking open/lock status.
   - `DropDirHandler(FileSystemEventHandler)` for reactive file system events.
   - `IncomingWatcher` orchestrating watchdog events, periodic fallback scans, file deduplication, and lifecycle dispatches.
5. **`src/ingestion/sec_fetcher.py`** [NEW]:
   - `TokenBucketRateLimiter` guaranteeing $\le 10$ requests per second.
   - `SecFetcher` client querying company tickers, fetching filing submissions, downloading primary documents, generating `.meta.json` sidecars, and handling 429 backoff.
   - Typer CLI command wrapper for manual and containerized execution.
6. **`src/ingestion/runner.py`** [MODIFY]:
   - Instantiate and wire `LifecycleManager` and `IncomingWatcher`.
   - Update `run_cycle()` to drive pending watcher sweeps.
   - Gracefully stop watcher on SIGTERM/SIGINT.
7. **`scripts/fetch_sec_filings.sh`** [NEW]:
   - Executable bash utility prompting for `SEC_USER_AGENT` if unset, accepting ticker, form, and day-granularity date filters (`--start-date`, `--end-date`), and invoking the fetcher inside the running `ingestion-runner` container or local Python.
8. **`README.md`** [MODIFY]:
   - Document SEC downloader CLI and bash helper usage, day-granularity date range flags, and `SEC_USER_AGENT` configuration.

### Test Suites
9. **`tests/test_watcher.py`** [NEW]:
   - Unit tests for `CompleteWriteDetector`, temporary file exclusion, deduplication, and `IncomingWatcher` event/poll dispatch.
10. **`tests/test_sec_fetcher.py`** [NEW]:
   - Unit tests for CIK lookup, filing submissions filtering (10-K, 10-Q, 8-K), day-granularity range filtering (`start_date`, `end_date`), rate limiter enforcement, User-Agent headers, and sidecar metadata generation using mock HTTP responses.
11. **`tests/test_lifecycle.py`** [NEW]:
   - Unit tests for atomic moves to `/data/processed/`, failure handling with `.error.json` dead-letter files, name collision prevention, and `IngestionSummary` metrics.
12. **`tests/test_ingestion_runner.py`** [MODIFY]:
    - Extend test suite to verify `IngestionRunner` lifecycle with integrated watcher and lifecycle manager.

---

## 4. Execution & Verification Workflow

1. **Red Phase (TDD Test First)**:
   - Create `tests/test_watcher.py`, `tests/test_sec_fetcher.py`, and `tests/test_lifecycle.py` with failing test assertions at the agreed seams.
2. **Green Phase (Implementation)**:
   - Update `src/common/config.py` and `src/common/models.py`.
   - Implement `src/ingestion/lifecycle.py`, `src/ingestion/watcher.py`, and `src/ingestion/sec_fetcher.py`.
   - Implement `scripts/fetch_sec_filings.sh` and update `README.md`.
   - Update `src/ingestion/runner.py` to drive watcher and lifecycle manager.
3. **Automated Verification**:
   - Run the complete pytest suite inside Python 3.13:
     ```bash
     docker run --rm -v $(pwd):/app -w /app corpus-test:3.13 pytest -v
     ```
   - Run linting and style checks:
     ```bash
     docker run --rm -v $(pwd):/app -w /app corpus-test:3.13 ruff check src/ tests/
     ```
4. **Integration & Manual Verification**:
   - Verify live SEC fetch with day-granularity date range:
     ```bash
     export SEC_USER_AGENT="CorpusAnalystAdmin admin@corpus-analyst.local"
     ./scripts/fetch_sec_filings.sh --ticker NVDA --form 10-K --start-date 2024-01-01 --end-date 2024-03-31
     ```
   - Verify watcher complete write detection and atomic move by dropping sample files into `/data/incoming`.
   - Verify dead-letter logging by dropping malformed files and validating `/data/failed/*.error.json`.

