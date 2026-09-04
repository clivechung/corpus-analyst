# Implementation Plan — Pluggable LocalFS Storage Architecture (Replacing Edge Blob)

Refactor the platform storage layer to remove the Azure Edge Blob emulator (`edgeblob` container), transition lakehouse storage to a high-performance **LocalFS** provider by default, and introduce an extensible **Storage Backend Strategy / Protocol** so that Cloud Azure Blob Storage can be plugged in seamlessly later via configuration.

---

## 1. Architectural Overview & Design Decisions

- **Removal of `edgeblob` Container**:
  - The IoT Edge blob container (`mcr.microsoft.com/azure-blob-storage:latest`) and its named volume `edgeblob_data` are removed from `docker-compose.yml`.
  - Simplifies local deployment and eliminates legacy API versioning constraints.
- **Default Storage Provider (`localfs`)**:
  - Lakehouse Parquet storage directly targets `./data/lake` mounted across `ingestion-runner` and `query-engine` (`:ro`).
  - Native DuckDB queries read local Parquet files with zero HTTP emulation overhead.
- **Pluggable Storage Strategy (`TREM: Extensible, Testable`)**:
  - `StorageBackendProtocol`: Standard protocol defining `initialize()`, `is_healthy()`, `list_files()`, `read_bytes()`, and `write_bytes()`.
  - `LocalStorageBackend`: Concrete implementation managing filesystem operations under `local_path` (`/data/lake`).
  - `AzureBlobStorageBackend`: Pluggable adapter prepared for connecting to production Cloud Azure Blob Storage in future phases.
  - `get_storage_backend(settings)`: Central factory selecting the backend based on `settings.storage.provider` (`"localfs"` vs `"azure_blob"`).

---

## 2. Pre-Agreed Testing Seams (TDD)

| Seam ID | Seam Target | Verification Scope |
| :--- | :--- | :--- |
| **`SEAM-STORAGE`** | `src/common/storage.py` | Validates `LocalStorageBackend` initialization, directory creation, read/write/list operations, and factory instantiation for both `localfs` and future `azure_blob`. |
| **`SEAM-COMPOSE`** | `docker-compose.yml` | Validates updated 4-service topology (`nginx`, `query-engine`, `ingestion-runner`, `streamlit`), volume bindings, removal of `edgeblob`, and healthchecks. |
| **`SEAM-RUNNER`** | `src/ingestion/runner.py` | Validates ingestion daemon lifecycle utilizing the pluggable `StorageBackendProtocol`. |
| **`SEAM-QUERY-API`** | `src/query_engine/main.py` | Validates query engine health probes and API endpoints with localfs storage. |
| **`SEAM-E2E-HEALTH`** | Docker Compose Stack (`docker compose up -d`) | Validates all 4 containers boot and reach `(healthy)` state. |

---

## 3. Detailed File Deliverables

### Storage & Configuration Layer
1. **`src/common/storage.py`** [NEW]:
   - `StorageBackendProtocol`, `LocalStorageBackend`, `AzureBlobStorageBackend`, and `get_storage_backend()`.
2. **`src/common/blob_storage.py`** [DELETE]:
   - Superseded by `src/common/storage.py`.
3. **`src/common/config.py`** [MODIFY]:
   - Update `StorageSettings` to `provider: str = "localfs"`, `local_path: str = "/data/lake"`, and cloud Azure Blob settings.
4. **`config/config.yaml` & `.env.example`** [MODIFY]:
   - Update storage configuration to `provider: localfs`.

### Application Services & Infrastructure Layer
5. **`src/ingestion/runner.py`** [MODIFY]:
   - Use `get_storage_backend(settings)` and initialize active backend on startup.
6. **`docker-compose.yml`** [MODIFY]:
   - Remove `edgeblob` service and `edgeblob_data` volume.
   - Streamline stack to 4 microservices (`nginx`, `query-engine`, `ingestion-runner`, `streamlit`).

### Test Suites
7. **`tests/test_storage.py`** [NEW]:
   - Unit tests covering `LocalStorageBackend`, `AzureBlobStorageBackend`, and factory resolution.
8. **`tests/test_blob_storage.py`** [DELETE]:
   - Superseded by `tests/test_storage.py`.
9. **`tests/test_docker_compose.py`** [MODIFY]:
   - Update assertions for 4 services and localfs storage topology.
10. **`tests/test_ingestion_runner.py`** [MODIFY]:
    - Mock `StorageBackendProtocol` for runner test suite.

---

## 4. Execution & Verification Workflow

1. **Red Phase**: Write `tests/test_storage.py` and update `tests/test_docker_compose.py`.
2. **Green Phase**: Implement `src/common/storage.py`, update `config.py`, `runner.py`, and `docker-compose.yml`.
3. **Refactor & Cleanup**: Remove obsolete `src/common/blob_storage.py` and `tests/test_blob_storage.py`.
4. **Automated Verification**: Run full pytest suite with Python 3.13 in `corpus-test:3.13`.
5. **Stack Verification**: Boot new 4-container stack with `docker compose up -d`, confirm all 4 are `healthy`, and verify ingress routing.
