"""Document processing lifecycle management and dead-letter handling.

Follows TREM-Python principles:
- Testable: Injected directories, processors, and pure deterministic atomic moves.
- Readable: Explicit state transitions, typed models, and structured logging.
- Extensible: DocumentProcessorProtocol enabling Phase 4 parser and Phase 5 embedder integration.
- Maintainable: Atomic file relocations, collision avoidance, and detailed dead-letter JSON traces.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol, runtime_checkable
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from src.common.models import (
    DeadLetterRecord,
    DocumentMetadata,
    DomainType,
    FormType,
    IngestionStatus,
    IngestionSummary,
)

logger = logging.getLogger(__name__)


# -----------------------------------------------------------------------------
# Processor Contract & Result DTO
# -----------------------------------------------------------------------------


class IngestionResult(BaseModel):
    """Result returned by a document processor."""

    model_config = ConfigDict(use_enum_values=True)

    success: bool = Field(description="Whether processing completed without fatal error")
    status: IngestionStatus = Field(default=IngestionStatus.COMPLETED, description="Lifecycle status")
    metadata: DocumentMetadata | None = Field(default=None, description="Extracted or matched document metadata")
    chunk_count: int = Field(default=0, ge=0, description="Total chunks generated")
    token_total: int = Field(default=0, ge=0, description="Total tokens extracted")
    parquet_paths: list[str] = Field(
        default_factory=list, description="Lakehouse Parquet files generated"
    )
    duration_seconds: float = Field(default=0.0, ge=0.0, description="Processing duration in seconds")
    error_message: str | None = Field(default=None, description="Error details if unsuccessful")



@runtime_checkable
class DocumentProcessorProtocol(Protocol):
    """Protocol for document processors (implemented in Phase 3 default, Phase 4 parser, Phase 5 embedder)."""

    def process(self, file_path: Path, metadata: DocumentMetadata | None = None) -> IngestionResult:
        """Process an input document file."""
        ...


class DefaultDocumentProcessor:
    """Default lightweight document processor for Phase 3 ingestion verification.

    Performs file integrity checks, reads companion .meta.json sidecar files if available,
    and returns a valid IngestionResult envelope.
    """

    def process(self, file_path: Path, metadata: DocumentMetadata | None = None) -> IngestionResult:
        start_time = time.perf_counter()

        if not file_path.is_file():
            raise FileNotFoundError(f"File not found for processing: {file_path}")

        # Check if companion .meta.json exists
        resolved_meta = metadata
        if resolved_meta is None:
            sidecar_candidates = [
                file_path.with_name(f"{file_path.name}.meta.json"),
                file_path.with_name(f"{file_path.stem}.meta.json"),
            ]
            for candidate in sidecar_candidates:
                if candidate.is_file():
                    try:
                        with open(candidate, "r", encoding="utf-8") as f:
                            data = json.load(f)
                            resolved_meta = DocumentMetadata(**data)
                            logger.info("Loaded companion metadata from %s", candidate.name)
                            break
                    except Exception as exc:
                        logger.warning("Failed to parse sidecar metadata at %s: %s", candidate, exc)

        if resolved_meta is None:
            resolved_meta = DocumentMetadata(
                doc_id=f"doc-{uuid4().hex[:12]}",
                source_filename=file_path.name,
                domain=DomainType.FINANCE,
                form_type=FormType.MISC,
            )

        # File readability validation
        file_size = file_path.stat().st_size
        with open(file_path, "rb") as f:
            content_sample = f.read()

        # Format syntax validation for structured formats (e.g. .json)
        if file_path.suffix.lower() == ".json":
            json.loads(content_sample.decode("utf-8"))

        elapsed = time.perf_counter() - start_time
        return IngestionResult(
            success=True,
            status=IngestionStatus.COMPLETED,
            metadata=resolved_meta,
            chunk_count=0,
            token_total=0,
            duration_seconds=elapsed,
        )


# -----------------------------------------------------------------------------
# Lifecycle Manager
# -----------------------------------------------------------------------------


def get_default_processor() -> DocumentProcessorProtocol:
    """Resolve default processor: prefers DocumentParser (ING-03) with graceful fallback."""
    try:
        from src.ingestion.parser import DocumentParser

        return DocumentParser()
    except Exception as exc:
        logger.debug("DocumentParser unavailable (%s); falling back to DefaultDocumentProcessor", exc)
        return DefaultDocumentProcessor()


class LifecycleManager:
    """Coordinates atomic document state transitions, processed archiving, and dead-letter handling."""

    def __init__(
        self,
        processed_dir: str | Path,
        failed_dir: str | Path,
        processor: DocumentProcessorProtocol | None = None,
    ) -> None:
        self.processed_dir = Path(processed_dir)
        self.failed_dir = Path(failed_dir)
        self.processor = processor or get_default_processor()

        self.processed_dir.mkdir(parents=True, exist_ok=True)
        self.failed_dir.mkdir(parents=True, exist_ok=True)

    def _resolve_unique_dest(self, dest_dir: Path, original_name: str) -> Path:
        """Resolve a destination path, appending a collision-safe timestamp/hash if file already exists."""
        target = dest_dir / original_name
        if not target.exists():
            return target

        stem = Path(original_name).stem
        suffix = Path(original_name).suffix
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        rand = uuid4().hex[:6]
        return dest_dir / f"{stem}_{ts}_{rand}{suffix}"

    def _find_sidecars(self, file_path: Path) -> list[Path]:
        """Find companion sidecar files (e.g. .meta.json) associated with the file."""
        candidates = [
            file_path.with_name(f"{file_path.name}.meta.json"),
            file_path.with_name(f"{file_path.stem}.meta.json"),
        ]
        return [c for c in candidates if c.is_file()]

    def atomic_move_to_processed(self, file_path: Path) -> Path:
        """Atomically relocate file and its sidecars to the processed archive."""
        dest_path = self._resolve_unique_dest(self.processed_dir, file_path.name)
        shutil.move(str(file_path), str(dest_path))

        # Move companion sidecars alongside if present
        for sidecar in self._find_sidecars(file_path):
            sidecar_dest = self.processed_dir / sidecar.name
            if sidecar_dest.exists():
                sidecar_dest = self._resolve_unique_dest(self.processed_dir, sidecar.name)
            shutil.move(str(sidecar), str(sidecar_dest))

        logger.info("Atomically relocated %s -> %s", file_path.name, dest_path)
        return dest_path

    def atomic_move_to_failed(
        self,
        file_path: Path,
        exc: Exception,
        metadata: dict[str, Any] | None = None,
    ) -> tuple[Path, Path]:
        """Atomically relocate failed file to /data/failed/ and generate dead-letter .error.json record."""
        dest_path = self._resolve_unique_dest(self.failed_dir, file_path.name)
        file_size = file_path.stat().st_size if file_path.exists() else 0
        shutil.move(str(file_path), str(dest_path))

        # Move companion sidecars if present
        for sidecar in self._find_sidecars(file_path):
            sidecar_dest = self.failed_dir / sidecar.name
            if sidecar_dest.exists():
                sidecar_dest = self._resolve_unique_dest(self.failed_dir, sidecar.name)
            shutil.move(str(sidecar), str(sidecar_dest))

        # Generate DeadLetterRecord artifact
        dead_letter = DeadLetterRecord(
            source_filename=dest_path.name,
            file_size_bytes=file_size,
            error_type=type(exc).__name__,
            error_message=str(exc),
            stack_trace=traceback.format_exc(),
            metadata=metadata or {},
        )

        error_json_path = dest_path.with_name(f"{dest_path.name}.error.json")
        with open(error_json_path, "w", encoding="utf-8") as f:
            f.write(dead_letter.model_dump_json(indent=2))

        logger.error(
            "File processing failed: %s -> %s; logged dead-letter error record at %s",
            file_path.name,
            dest_path,
            error_json_path,
        )
        return dest_path, error_json_path

    def handle_file(
        self,
        file_path: Path,
        metadata: DocumentMetadata | None = None,
    ) -> IngestionSummary:
        """Coordinate full ingestion lifecycle for a candidate file."""
        start_time = time.perf_counter()
        logger.info("Beginning lifecycle processing for: %s", file_path)

        try:
            result = self.processor.process(file_path, metadata)
            if not result.success:
                raise RuntimeError(result.error_message or "Unknown processor failure")

            moved_path = self.atomic_move_to_processed(file_path)
            duration = time.perf_counter() - start_time

            summary = IngestionSummary(
                file_path=str(moved_path),
                status=IngestionStatus.COMPLETED,
                duration_seconds=duration,
                chunk_count=result.chunk_count,
                token_total=result.token_total,
                parquet_paths=result.parquet_paths,
            )
            logger.info(
                "Ingestion successfully completed for %s in %.3fs (chunks: %d, tokens: %d)",
                moved_path.name,
                duration,
                result.chunk_count,
                result.token_total,
            )
            return summary

        except Exception as exc:
            duration = time.perf_counter() - start_time
            dest_failed, _ = self.atomic_move_to_failed(
                file_path,
                exc,
                metadata=metadata.model_dump() if metadata else None,
            )
            summary = IngestionSummary(
                file_path=str(dest_failed),
                status=IngestionStatus.FAILED,
                duration_seconds=duration,
                chunk_count=0,
                token_total=0,
                error_message=str(exc),
            )
            return summary

