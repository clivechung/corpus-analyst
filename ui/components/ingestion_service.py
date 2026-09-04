"""Service layer for document ingestion monitoring, queue inspection, and SEC triggers.

Follows TREM-Python principles:
- Testable: Fully injectable filesystem paths, mockable SecFetcher class, zero GUI dependencies.
- Readable: Strictly typed Pydantic models (QueueItem, QueueMetrics), descriptive signatures, and logging.
- Extensible: Clean abstractions for queue status filtering, dead-letter parsing, and re-queueing.
- Maintainable: Robust file handling with atomic operations, collision safety, and companion sidecars.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Type
from uuid import uuid4

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


# -----------------------------------------------------------------------------
# Data Models
# -----------------------------------------------------------------------------


class QueueItem(BaseModel):
    """Represents a single document in the ingestion pipeline."""

    filename: str = Field(description="Base filename of the document")
    status: str = Field(description="Lifecycle status: 'PENDING', 'PROCESSED', or 'FAILED'")
    file_size_bytes: int = Field(ge=0, description="File size in bytes")
    mtime: float = Field(description="POSIX modification timestamp")
    ticker: str | None = Field(default=None, description="Extracted stock ticker symbol")
    form_type: str | None = Field(default=None, description="Filing or document form type (e.g. 10-K, 10-Q)")
    company_name: str | None = Field(default=None, description="Resolved entity or company name")
    domain: str | None = Field(default="finance", description="Corpus domain profile")
    error_type: str | None = Field(default=None, description="Dead-letter error type if failed")
    error_message: str | None = Field(default=None, description="Dead-letter error description if failed")
    has_metadata: bool = Field(default=False, description="Whether a companion .meta.json sidecar exists")

    @property
    def formatted_size(self) -> str:
        """Format byte size into human-readable metric string."""
        if self.file_size_bytes < 1024:
            return f"{self.file_size_bytes} B"
        elif self.file_size_bytes < 1024 * 1024:
            return f"{self.file_size_bytes / 1024:.1f} KB"
        else:
            return f"{self.file_size_bytes / (1024 * 1024):.2f} MB"

    @property
    def formatted_time(self) -> str:
        """Format modification timestamp into UTC string."""
        dt = datetime.fromtimestamp(self.mtime, tz=timezone.utc)
        return dt.strftime("%Y-%m-%d %H:%M:%S")


class QueueMetrics(BaseModel):
    """Consolidated telemetry metrics for the ingestion pipeline HUD."""

    incoming_count: int = Field(default=0, ge=0, description="Documents queued in incoming")
    processed_count: int = Field(default=0, ge=0, description="Documents settled in processed archive")
    failed_count: int = Field(default=0, ge=0, description="Documents quarantined in dead-letter")
    total_processed_bytes: int = Field(default=0, ge=0, description="Total byte volume of processed corpus")
    failure_rate_pct: float = Field(default=0.0, ge=0.0, le=100.0, description="Failure percentage")
    latest_ingest_time: str | None = Field(default=None, description="Timestamp of most recent processed document")

    @property
    def formatted_volume(self) -> str:
        """Format total volume into MB or GB."""
        mb = self.total_processed_bytes / (1024 * 1024)
        if mb < 1024:
            return f"{mb:.1f} MB"
        return f"{mb / 1024:.2f} GB"


# -----------------------------------------------------------------------------
# Ingestion Service Core
# -----------------------------------------------------------------------------


class IngestionService:
    """Business logic coordinator for ingestion monitoring and manual triggering."""

    IGNORED_EXTENSIONS = {".meta.json", ".error.json", ".tmp", ".crdownload", ".part"}

    def __init__(
        self,
        incoming_dir: str | Path | None = None,
        processed_dir: str | Path | None = None,
        failed_dir: str | Path | None = None,
        sec_fetcher_cls: Any = None,
    ) -> None:
        self.incoming_dir = Path(
            incoming_dir
            or os.environ.get("DATA_INCOMING_PATH")
            or "./data/incoming"
        )
        self.processed_dir = Path(
            processed_dir
            or os.environ.get("DATA_PROCESSED_PATH")
            or "./data/processed"
        )
        self.failed_dir = Path(
            failed_dir
            or os.environ.get("DATA_FAILED_PATH")
            or "./data/failed"
        )

        # Lazy import of SecFetcher to decouple unit tests if not provided
        self._sec_fetcher_cls = sec_fetcher_cls

        self.incoming_dir.mkdir(parents=True, exist_ok=True)
        self.processed_dir.mkdir(parents=True, exist_ok=True)
        self.failed_dir.mkdir(parents=True, exist_ok=True)

    @property
    def sec_fetcher_cls(self) -> Any:
        """Resolve SecFetcher class lazily."""
        if self._sec_fetcher_cls is not None:
            return self._sec_fetcher_cls
        try:
            from src.ingestion.sec_fetcher import SecFetcher
            return SecFetcher
        except Exception as exc:
            logger.warning("Could not import SecFetcher: %s", exc)
            return None

    def _is_primary_file(self, path: Path) -> bool:
        """Check if path is a candidate document (not a sidecar, error log, or hidden file)."""
        if not path.is_file():
            return False
        if path.name.startswith("."):
            return False
        for ext in self.IGNORED_EXTENSIONS:
            if path.name.endswith(ext):
                return False
        return True

    def _extract_sidecar_metadata(self, parent_dir: Path, filename: str) -> dict[str, Any] | None:
        """Load companion .meta.json sidecar if present."""
        candidates = [
            parent_dir / f"{filename}.meta.json",
            parent_dir / f"{Path(filename).stem}.meta.json",
        ]
        for candidate in candidates:
            if candidate.is_file():
                try:
                    with open(candidate, "r", encoding="utf-8") as f:
                        return json.load(f)
                except Exception as exc:
                    logger.debug("Error reading sidecar %s: %s", candidate, exc)
        return None

    def _extract_dead_letter_info(self, filename: str) -> tuple[str | None, str | None]:
        """Extract error_type and error_message from {filename}.error.json in failed dir."""
        error_file = self.failed_dir / f"{filename}.error.json"
        if error_file.is_file():
            try:
                with open(error_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    return data.get("error_type"), data.get("error_message")
            except Exception as exc:
                logger.debug("Error reading dead letter log %s: %s", error_file, exc)
        return None, None

    def scan_queue(
        self,
        status_filter: str | None = None,
        search_query: str | None = None,
    ) -> list[QueueItem]:
        """Scan all ingestion directories and return structured, sorted QueueItems."""
        items: list[QueueItem] = []

        # 1. Scan Incoming (PENDING)
        if self.incoming_dir.is_dir():
            for p in self.incoming_dir.iterdir():
                if self._is_primary_file(p):
                    stat = p.stat()
                    meta = self._extract_sidecar_metadata(self.incoming_dir, p.name)
                    items.append(
                        QueueItem(
                            filename=p.name,
                            status="PENDING",
                            file_size_bytes=stat.st_size,
                            mtime=stat.st_mtime,
                            ticker=meta.get("ticker") if meta else None,
                            form_type=meta.get("form_type") if meta else None,
                            company_name=meta.get("company_name") if meta else None,
                            domain=meta.get("domain", "finance") if meta else "finance",
                            has_metadata=meta is not None,
                        )
                    )

        # 2. Scan Processed (PROCESSED)
        if self.processed_dir.is_dir():
            for p in self.processed_dir.iterdir():
                if self._is_primary_file(p):
                    stat = p.stat()
                    meta = self._extract_sidecar_metadata(self.processed_dir, p.name)
                    items.append(
                        QueueItem(
                            filename=p.name,
                            status="PROCESSED",
                            file_size_bytes=stat.st_size,
                            mtime=stat.st_mtime,
                            ticker=meta.get("ticker") if meta else None,
                            form_type=meta.get("form_type") if meta else None,
                            company_name=meta.get("company_name") if meta else None,
                            domain=meta.get("domain", "finance") if meta else "finance",
                            has_metadata=meta is not None,
                        )
                    )

        # 3. Scan Failed (FAILED)
        if self.failed_dir.is_dir():
            for p in self.failed_dir.iterdir():
                if self._is_primary_file(p):
                    stat = p.stat()
                    meta = self._extract_sidecar_metadata(self.failed_dir, p.name)
                    err_type, err_msg = self._extract_dead_letter_info(p.name)
                    items.append(
                        QueueItem(
                            filename=p.name,
                            status="FAILED",
                            file_size_bytes=stat.st_size,
                            mtime=stat.st_mtime,
                            ticker=meta.get("ticker") if meta else None,
                            form_type=meta.get("form_type") if meta else None,
                            company_name=meta.get("company_name") if meta else None,
                            domain=meta.get("domain", "finance") if meta else "finance",
                            error_type=err_type,
                            error_message=err_msg,
                            has_metadata=meta is not None,
                        )
                    )

        # Filter by status if requested
        if status_filter and status_filter.upper() != "ALL":
            target = status_filter.upper()
            items = [item for item in items if item.status == target]

        # Filter by search query if specified
        if search_query:
            query = search_query.strip().lower()
            items = [
                item for item in items
                if (
                    query in item.filename.lower()
                    or (item.ticker and query in item.ticker.lower())
                    or (item.form_type and query in item.form_type.lower())
                    or (item.company_name and query in item.company_name.lower())
                )
            ]

        # Sort by mtime descending (newest first)
        items.sort(key=lambda x: x.mtime, reverse=True)
        return items

    def get_metrics(self) -> QueueMetrics:
        """Calculate consolidated telemetry metrics for the HUD."""
        all_items = self.scan_queue()

        incoming_count = sum(1 for i in all_items if i.status == "PENDING")
        processed_items = [i for i in all_items if i.status == "PROCESSED"]
        failed_count = sum(1 for i in all_items if i.status == "FAILED")

        processed_count = len(processed_items)
        total_processed_bytes = sum(i.file_size_bytes for i in processed_items)

        resolved_total = processed_count + failed_count
        failure_rate = (failed_count / resolved_total * 100.0) if resolved_total > 0 else 0.0

        latest_time = None
        if processed_items:
            latest_mtime = max(i.mtime for i in processed_items)
            latest_time = datetime.fromtimestamp(latest_mtime, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

        return QueueMetrics(
            incoming_count=incoming_count,
            processed_count=processed_count,
            failed_count=failed_count,
            total_processed_bytes=total_processed_bytes,
            failure_rate_pct=round(failure_rate, 2),
            latest_ingest_time=latest_time,
        )

    def get_dead_letter_details(self, filename: str) -> dict[str, Any] | None:
        """Load dead-letter error record for a failed document."""
        error_file = self.failed_dir / f"{filename}.error.json"
        if error_file.is_file():
            try:
                with open(error_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as exc:
                logger.error("Failed to read error JSON for %s: %s", filename, exc)
        return None

    def get_metadata_details(
        self,
        filename: str,
        status: str | None = None,
    ) -> dict[str, Any] | None:
        """Load companion .meta.json sidecar across directories, checking status directory first if provided."""
        target_dirs: list[Path] = []
        if status:
            s = status.upper()
            if s == "PROCESSED":
                target_dirs.append(self.processed_dir)
            elif s == "PENDING":
                target_dirs.append(self.incoming_dir)
            elif s == "FAILED":
                target_dirs.append(self.failed_dir)

        # Fallback to check all directories
        for d in [self.processed_dir, self.incoming_dir, self.failed_dir]:
            if d not in target_dirs:
                target_dirs.append(d)

        for d in target_dirs:
            meta = self._extract_sidecar_metadata(d, filename)
            if meta:
                return meta
        return None

    def requeue_failed_file(self, filename: str) -> bool:
        """Atomically relocate failed file back to incoming to trigger watcher retry."""
        src_path = self.failed_dir / filename
        if not src_path.is_file():
            logger.warning("Target file %s not found in failed dir", filename)
            return False

        dest_path = self.incoming_dir / filename
        shutil.move(str(src_path), str(dest_path))

        # Relocate companion sidecar if exists
        sidecar_candidates = [
            self.failed_dir / f"{filename}.meta.json",
            self.failed_dir / f"{Path(filename).stem}.meta.json",
        ]
        for sc in sidecar_candidates:
            if sc.is_file():
                shutil.move(str(sc), str(self.incoming_dir / sc.name))

        # Remove stale error log
        error_log = self.failed_dir / f"{filename}.error.json"
        if error_log.is_file():
            try:
                error_log.unlink()
            except Exception as exc:
                logger.warning("Could not delete stale error log %s: %s", error_log, exc)

        logger.info("Successfully re-queued %s to incoming", filename)
        return True

    def save_uploaded_file(
        self,
        file_name: str,
        file_bytes: bytes,
        ticker: str | None = None,
        form_type: str | None = None,
        domain: str | None = "finance",
    ) -> Path:
        """Save uploaded document bytes to incoming directory with companion metadata sidecar."""
        target_path = self.incoming_dir / file_name
        temp_path = self.incoming_dir / f".{file_name}.{uuid4().hex[:8]}.tmp"

        with open(temp_path, "wb") as f:
            f.write(file_bytes)

        # Atomic rename to trigger complete write detection
        os.replace(temp_path, target_path)

        # Generate companion metadata sidecar if tags are provided
        sidecar_payload: dict[str, Any] = {
            "doc_id": f"upload-{uuid4().hex[:12]}",
            "source_filename": file_name,
            "domain": domain or "finance",
            "form_type": form_type or "MISC",
            "filing_date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        }
        if ticker:
            sidecar_payload["ticker"] = ticker.strip().upper()

        sidecar_path = target_path.with_name(f"{target_path.name}.meta.json")
        with open(sidecar_path, "w", encoding="utf-8") as f:
            json.dump(sidecar_payload, f, indent=2)

        logger.info("Saved uploaded file %s with companion sidecar", file_name)
        return target_path

    def execute_sec_fetch(
        self,
        ticker: str,
        form_type: str = "10-K",
        start_date: str | None = None,
        end_date: str | None = None,
        user_agent: str | None = None,
    ) -> dict[str, Any]:
        """Trigger SEC EDGAR download utility for target ticker and form."""
        clean_ticker = ticker.strip().upper()
        clean_form = form_type.strip().upper()

        fetcher_cls = self.sec_fetcher_cls
        if fetcher_cls is None:
            return {
                "success": False,
                "ticker": clean_ticker,
                "error": "SecFetcher module is unavailable in this environment.",
            }

        try:
            fetcher = fetcher_cls(
                output_dir=self.incoming_dir,
                user_agent=user_agent or os.environ.get("SEC_USER_AGENT"),
            )
            downloaded = fetcher.download_filing(
                ticker=clean_ticker,
                form_type=clean_form,
                start_date=start_date,
                end_date=end_date,
            )
            return {
                "success": True,
                "ticker": clean_ticker,
                "form_type": clean_form,
                "file_path": str(downloaded),
                "filename": downloaded.name,
            }
        except Exception as exc:
            logger.error("SEC fetch execution failed for %s: %s", clean_ticker, exc)
            return {
                "success": False,
                "ticker": clean_ticker,
                "form_type": clean_form,
                "error": str(exc),
            }
