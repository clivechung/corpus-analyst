# Implementation Plan — Phase 3 UI-02: Document Ingestion Monitor & Manual SEC Trigger (Quant Trading Floor Edition)

Build and integrate the **`UI-02`** feature for the **corpus-analyst** platform: an interactive document ingestion monitor, manual SEC EDGAR filing acquisition trigger, and drag-and-drop file intake interface, designed with a high-density, professional **Quant Trading Floor** aesthetic (Bloomberg Terminal / Refinitiv Eikon inspired Obsidian & Amber theme, live telemetry HUD, market status bar, order-ticket style SEC trigger, and dead-letter quarantine inspector).

---

## 1. Architectural Overview & Design Decisions

### 1.1 Quant Trading Floor Visual Identity & Design System
Quants and algorithmic researchers require high information density, dark obsidian backgrounds to prevent visual fatigue during long market sessions, clear monospace typography for numerical figures and identifiers, and sharp color-coded terminal alerts:
- **Obsidian & Amber / Emerald Palette**:
  - Background: Deep Obsidian (`#0b0e14`) with dark slate surfaces (`#111622`, `#161f30`) and crisp 1px borders (`#1e293b`, `#26354a`).
  - Terminal Amber (`#ffb000` / `#f59e0b`): Primary active accent, highlight badges, and requisition buttons.
  - High-Frequency Emerald (`#10b981` / `#00e676`): Settled / successfully ingested files and positive telemetry.
  - Telemetry Cyan (`#00e5ff` / `#38bdf8`): Queue counters, active processing states, and live streaming logs.
  - Circuit Breaker Red (`#ef4444` / `#f87171`): Dead-letter failures, validation alerts, and exceptions.
- **Typography & Layout**:
  - Strict monospace font stack (`ui-monospace, "SF Mono", "JetBrains Mono", "IBM Plex Mono", Menlo, Consolas, monospace`) for all numbers, CIKs, accession hashes, timestamps, and sizes.
  - Compact padding (`0.4rem` to `0.75rem`) to maximize visible information density per screen without unnecessary scrolling.
  - Sharp corners (`border-radius: 4px` - `6px`) matching trading terminals.
- **Top Ticker HUD**:
  - Live UTC & NYSE Market Hours clock/indicator (`MARKET: OPEN [US/EASTERN]` / `MARKET: CLOSED`).
  - Microservice mesh health indicator (`INGESTION DAEMON: ACTIVE`, `QUERY ENGINE: ONLINE`).
  - Ingestion metrics strip: Queue Depth (`INCOMING`), Corpus Volume (`PROCESSED`), Quarantined (`FAILED`), and Failure Rate (`%`).

### 1.2 Separation of Concerns (TREM Engineering)
To adhere to the project's [TREM principles](file:///home/cc/ws/corpus-analyst/.agents/skills/trem-python/SKILL.md) (Testable, Readable, Extensible, Maintainable), the UI implementation is decoupled into three distinct layers:
1. **Style & Theme Layer (`ui/components/quant_theme.py` & `.streamlit/config.toml`)**:
   - Injects custom CSS rules, layout modifiers, custom metric cards, status badges, and terminal aesthetics.
2. **Business & Storage Service Layer (`ui/components/ingestion_service.py`)**:
   - Pure Python service decoupled from Streamlit UI rendering.
   - Handles directory scanning across `/data/incoming`, `/data/processed`, `/data/failed`, reading `.meta.json` sidecars, parsing `.error.json` dead-letter files, atomic file re-queuing, saving uploaded files with companion metadata, and executing `SecFetcher`.
   - **100% testable via pytest** without running a Streamlit server or browser.
3. **Streamlit View Component (`ui/components/ingestion_view.py`)**:
   - Stateless Streamlit presentation component rendering the telemetry HUD, SEC requisition ticket, drag-and-drop dropbox, queue data table, and dead-letter forensic drawer.
4. **Main Orchestrator (`ui/app.py`)**:
   - Applies the global quant theme, mounts the top telemetry bar, and hosts the tabs.

---

## 2. User Review Required

> [!IMPORTANT]
> **Streamlit Container Dependencies & Volume Mount**:
> - `docker/streamlit/Dockerfile` currently only installs `streamlit` and `httpx`. To allow the Streamlit dashboard to directly load configurations (`pydantic`, `pyyaml`) and call `SecFetcher` (`typer`), we will add `pydantic>=2.7.0`, `pyyaml>=6.0.1`, and `typer>=0.12.0` to `docker/streamlit/Dockerfile`.
> - In `docker-compose.yml`, we will mount `./src:/app/src:ro` into the `streamlit` service so that any code in `src/` is immediately available and changes hot-reload without container rebuilds.
> - We will pass `SEC_USER_AGENT` through environment variables into the `streamlit` container.

> [!NOTE]
> **Live Coordination with Ingestion Daemon**:
> When a filing is fetched or a file is uploaded via the UI to `/data/incoming`:
> - The `ingestion-runner` daemon (running `IncomingWatcher`) automatically detects the new file and its companion `.meta.json` sidecar.
> - `CompleteWriteDetector` verifies complete write stability.
> - `LifecycleManager` atomically moves the file to `/data/processed` or `/data/failed`.
> - The UI's live queue monitor reflects this transition immediately upon page refresh or periodic rerun.

---

## 3. Open Questions

None. The requirements for `UI-02` and the quant trading floor styling are clear and fully specified by `feature-list.md` and user instructions.

---

## 4. Proposed Changes

### Styling & Theme Configuration

#### [NEW] [config.toml](file:///home/cc/ws/corpus-analyst/.streamlit/config.toml)
- Streamlit dark theme configuration:
  - `primaryColor = "#ffb000"` (Bloomberg Amber)
  - `backgroundColor = "#0b0e14"` (Deep Obsidian)
  - `secondaryBackgroundColor = "#111622"` (Dark Slate Card)
  - `textColor = "#e2e8f0"` (High-contrast Off-White)
  - `font = "monospace"`

#### [NEW] [quant_theme.py](file:///home/cc/ws/corpus-analyst/ui/components/quant_theme.py)
- Injected custom CSS rules:
  - Tight paddings, compact margins, crisp card borders (`1px solid #1e293b`).
  - Terminal status badges (`.quant-badge-pending`, `.quant-badge-processed`, `.quant-badge-failed`, `.quant-badge-sec`).
  - Monospace tabular styling for data grids.
  - Ticker strip and market hours telemetry helper.
  - Monospace code and error traceback styling.

---

### Ingestion Service & Data Layer (TREM: Testable)

#### [NEW] [ingestion_service.py](file:///home/cc/ws/corpus-analyst/ui/components/ingestion_service.py)
- Pydantic models for UI state:
  - `QueueItem`: `filename`, `status` (`PENDING`, `PROCESSED`, `FAILED`), `file_size_bytes`, `mtime`, `ticker`, `form_type`, `domain`, `error_type`, `error_message`, `has_metadata`.
  - `QueueMetrics`: `incoming_count`, `processed_count`, `failed_count`, `total_processed_bytes`, `failure_rate_pct`, `latest_ingest_time`.
- `IngestionService` class:
  - `__init__(incoming_dir, processed_dir, failed_dir, sec_fetcher_cls)`: Dependency-injected paths and fetcher.
  - `scan_queue(status_filter=None, search_query=None) -> list[QueueItem]`: Scans filesystem directories, associates `.meta.json` sidecars and `.error.json` dead-letter records, and returns sorted queue items.
  - `get_metrics() -> QueueMetrics`: Calculates HUD telemetry metrics.
  - `get_dead_letter_details(filename: str) -> dict | None`: Reads and returns formatted `{filename}.error.json`.
  - `get_metadata_details(filename: str) -> dict | None`: Reads and returns companion `.meta.json`.
  - `requeue_failed_file(filename: str) -> bool`: Atomically moves a quarantined file from `/data/failed` back to `/data/incoming` to trigger automatic watcher retry.
  - `save_uploaded_file(uploaded_file, ticker=None, form_type=None, domain=None) -> Path`: Writes uploaded file to `/data/incoming` with complete write safety and emits a companion `.meta.json` sidecar.
  - `execute_sec_fetch(ticker, form_type, start_date, end_date, user_agent) -> dict`: Instantiates `SecFetcher` targeting `incoming_dir`, downloads document + sidecar, and returns execution summary.

---

### UI Presentation Layer

#### [NEW] [ingestion_view.py](file:///home/cc/ws/corpus-analyst/ui/components/ingestion_view.py)
- Streamlit presentation components for Tab 2 ("Ingestion Monitor"):
  1. `render_kpi_strip(metrics: QueueMetrics)`: Renders 4 compact telemetry tiles (Queue Depth, Settled Corpus, Dead-Letter Failures, Volume).
  2. `render_sec_requisition_ticket(service: IngestionService, user_agent: str)`:
     - Quick-select Ticker grid (`NVDA`, `AAPL`, `MSFT`, `AMZN`, `GOOGL`, `META`, `TSLA`, `JPM`).
     - Ticker symbol text input with auto-uppercase and regex validation.
     - Form selector segmented buttons (`10-K`, `10-Q`, `8-K`).
     - Date filtering with presets ("Trailing 12M", "Year to Date", "Fiscal 2024", "Custom Range") and day-granularity date pickers.
     - SEC User-Agent status badge & override field.
     - Amber "EXECUTE SEC REQUISITION" action button with live status feedback.
  3. `render_intake_dropzone(service: IngestionService)`:
     - Drag-and-drop file uploader (`.pdf`, `.htm`, `.html`, `.json`, `.txt`).
     - SHA-256 hash calculation, byte size badge, and optional ticker/form/domain tags.
     - "INJECT TO INCOMING QUEUE" button.
  4. `render_pipeline_queue_grid(service: IngestionService)`:
     - Filter tabs (`ALL`, `PENDING`, `PROCESSED`, `FAILED`) and ticker/filename search bar.
     - High-density table with status pills, ticker badges, sizes, timestamps, and row actions.
  5. `render_dead_letter_drawer(service: IngestionService, failed_item: QueueItem)`:
     - Forensic drawer rendering error type, message, formatted traceback codeblock, and `[↺ RE-QUEUE FILE]` retry button.

#### [MODIFY] [app.py](file:///home/cc/ws/corpus-analyst/ui/app.py)
- Apply `inject_quant_theme()` on page boot.
- Render top trading floor header bar (System heartbeat, market session clock, active domain).
- Wire `render_ingestion_monitor` into the "Ingestion Monitor" tab using `IngestionService`.
- Fix bug on line 117 (import `Path`).
- Style other tabs with quant dark theme consistency.

---

### Containerization & Service Orchestration

#### [MODIFY] [Dockerfile](file:///home/cc/ws/corpus-analyst/docker/streamlit/Dockerfile)
- Update pip install to include:
  ```dockerfile
  RUN pip install --no-cache-dir \
      streamlit>=1.35.0 \
      httpx>=0.27.0 \
      pydantic>=2.7.0 \
      pyyaml>=6.0.1 \
      typer>=0.12.0
  ```

#### [MODIFY] [docker-compose.yml](file:///home/cc/ws/corpus-analyst/docker-compose.yml)
- Update `streamlit` service:
  - Add volume mount `- ./src:/app/src:ro`
  - Pass `SEC_USER_AGENT` environment variable
  - Pass `DATA_INCOMING_PATH`, `DATA_PROCESSED_PATH`, `DATA_FAILED_PATH`, `DATA_LAKE_PATH`

---

### Automated Tests (TDD Seam)

#### [NEW] [test_ui_ingestion.py](file:///home/cc/ws/corpus-analyst/tests/test_ui_ingestion.py)
- Dedicated test seam (`SEAM-UI-INGESTION`) testing `IngestionService`:
  - `test_scan_queue_classifies_incoming_processed_failed`: Validates file discovery and state assignment.
  - `test_scan_queue_parses_sidecar_metadata`: Verifies ticker, form_type, and CIK resolution from `.meta.json`.
  - `test_scan_queue_parses_dead_letter_error_json`: Verifies parsing of `.error.json` dead-letter traces.
  - `test_queue_metrics_calculation`: Verifies counts, volume aggregation, and failure rate percentage.
  - `test_save_uploaded_file_and_meta_sidecar`: Verifies atomic write to incoming and sidecar generation.
  - `test_requeue_failed_file_moves_to_incoming`: Verifies atomic relocation of failed file and removal of stale `.error.json`.
  - `test_execute_sec_fetch_wrapper`: Mocks `SecFetcher` and verifies argument passing and error handling.

---

### Documentation

#### [MODIFY] [README.md](file:///home/cc/ws/corpus-analyst/README.md)
- Mark `UI-02` as complete `[x]`.
- Add section describing the Quant Trading Floor Ingestion Monitor, SEC requisition ticket, and dead-letter quarantine triage.

---

## 5. Verification Plan

### Automated Tests
1. Run complete pytest test suite in Python 3.13 Docker test container:
   ```bash
   docker run --rm -v $(pwd):/app -w /app corpus-test:3.13 pytest -v
   ```
2. Run code style and linting checks:
   ```bash
   docker run --rm -v $(pwd):/app -w /app corpus-test:3.13 ruff check src/ tests/ ui/
   ```

### Manual & Integration Verification
1. **Docker Compose Build & Startup**:
   ```bash
   docker compose build streamlit
   docker compose up -d
   ```
2. **Quant UI Inspection**:
   - Access `http://localhost` (via Nginx ingress) and verify:
     - Dark obsidian & amber quant terminal aesthetic renders cleanly.
     - Top market session clock and microservice heartbeat badges display.
     - KPI metric tiles show real-time counts from `/data/incoming`, `/data/processed`, `/data/failed`.
3. **Manual SEC EDGAR Requisition**:
   - Select `NVDA`, `10-K`, specify date range `2024-01-01` to `2024-03-31`.
   - Click "EXECUTE SEC REQUISITION".
   - Confirm filing downloads to `/data/incoming` with companion `.meta.json`.
   - Verify `ingestion-runner` daemon picks up the filing and moves it to `/data/processed`.
   - Confirm queue table updates status to `PROCESSED`.
4. **Drag-and-Drop Intake**:
   - Upload a test PDF / HTML / JSON document with custom ticker `AAPL`.
   - Confirm document and sidecar appear in `/data/incoming` and transition through lifecycle.
5. **Dead-Letter Quarantine & Re-Queue**:
   - Drop an invalid file to trigger failure.
   - Inspect the forensic drawer showing the error traceback.
   - Click "RE-QUEUE FILE" and verify the file is returned to `/data/incoming` for retry.
