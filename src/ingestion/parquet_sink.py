"""Hive-Partitioned Parquet Sink and Pluggable Lakehouse Storage Pipeline (LAK-01, LAK-02s).

Follows TREM-Python principles:
- Testable: Strict ParquetSinkProtocol and pluggable StorageBackendProtocol decoupling
  allowing trivial mock injection and local filesystem verification.
- Readable: Fully type-annotated Arrow schemas, explicit Hive partition resolution,
  and descriptive error messages.
- Extensible: HivePartitionResolver strategy supporting multi-partition batch routing
  and cloud Azure Blob Storage syncing.
- Maintainable: Direct mapping to PRD Section 4.3 Parquet schema with Snappy compression,
  date32 temporal indexing, and vector array embedding persistence.
"""

from __future__ import annotations

import io
import logging
from datetime import UTC, date, datetime
from enum import Enum
from typing import Any, Protocol, runtime_checkable
from uuid import uuid4

import pyarrow as pa
import pyarrow.parquet as pq

from src.common.config import Settings, get_settings
from src.common.models import Chunk, DomainType
from src.common.storage import StorageBackendProtocol, get_storage_backend

logger = logging.getLogger(__name__)


# -----------------------------------------------------------------------------
# Parquet Schema Specification (PRD Section 4.3)
# -----------------------------------------------------------------------------


def get_parquet_schema() -> pa.Schema:
    """Return PyArrow schema conforming to PRD Section 4.3.

    Schema:
    - chunk_id: STRING (UUIDv4)
    - doc_id: STRING
    - domain: STRING (finance, literature, general)
    - source_filename: STRING
    - form_type: STRING (10-K, 10-Q, 8-K, BOOK, MISC)
    - filing_date: DATE32
    - section: STRING
    - is_table: BOOLEAN
    - text: STRING
    - embedding: LIST<FLOAT32>
    - metadata_json: STRING
    """
    return pa.schema(
        [
            pa.field("chunk_id", pa.string(), nullable=False),
            pa.field("doc_id", pa.string(), nullable=False),
            pa.field("domain", pa.string(), nullable=False),
            pa.field("source_filename", pa.string(), nullable=False),
            pa.field("form_type", pa.string(), nullable=False),
            pa.field("filing_date", pa.date32(), nullable=True),
            pa.field("section", pa.string(), nullable=False),
            pa.field("is_table", pa.bool_(), nullable=False),
            pa.field("text", pa.string(), nullable=False),
            pa.field("embedding", pa.list_(pa.float32()), nullable=False),
            pa.field("metadata_json", pa.string(), nullable=False),
        ]
    )


# -----------------------------------------------------------------------------
# Partition Resolver (LAK-01)
# -----------------------------------------------------------------------------


class HivePartitionResolver:
    """Resolves Hive-style partition paths (/domain=.../year=.../month=.../day=.../*.parquet)."""

    def resolve_date(self, filing_date: date | None) -> date:
        """Resolve document date, falling back to current UTC date if None."""
        if filing_date is not None:
            return filing_date
        return datetime.now(UTC).date()

    def resolve_partition_path(
        self,
        domain: str | DomainType,
        filing_date: date | None,
        batch_id: str | None = None,
    ) -> str:
        """Construct relative Hive partition path for a Parquet batch file.

        Format:
        domain={domain}/year={YYYY}/month={MM}/day={DD}/{batch_id}.parquet
        """
        domain_str = domain.value if isinstance(domain, Enum) else str(domain)
        clean_domain = domain_str.lower().strip() or "general"

        dt = self.resolve_date(filing_date)
        year_str = f"{dt.year:04d}"
        month_str = f"{dt.month:02d}"
        day_str = f"{dt.day:02d}"

        uid = batch_id or uuid4().hex
        if not uid.endswith(".parquet"):
            filename = f"{uid}.parquet"
        else:
            filename = uid

        return f"domain={clean_domain}/year={year_str}/month={month_str}/day={day_str}/{filename}"


# -----------------------------------------------------------------------------
# Parquet Sink Protocol & Implementation (LAK-01, LAK-02s)
# -----------------------------------------------------------------------------


@runtime_checkable
class ParquetSinkProtocol(Protocol):
    """Protocol contract for Parquet Lakehouse Writers."""

    def write_chunks(self, chunks: list[Chunk]) -> list[str]:
        """Persist list of embedded chunks to partitioned Parquet files and return URIs."""
        ...


class ParquetSink:
    """Hive-partitioned Parquet writer integrating with pluggable StorageBackendProtocol."""

    def __init__(
        self,
        storage_backend: StorageBackendProtocol | None = None,
        partition_resolver: HivePartitionResolver | None = None,
        schema: pa.Schema | None = None,
        compression: str = "snappy",
    ) -> None:
        self.storage_backend = storage_backend or get_storage_backend()
        self.partition_resolver = partition_resolver or HivePartitionResolver()
        self.schema = schema or get_parquet_schema()
        self.compression = compression

    def write_chunks(self, chunks: list[Chunk]) -> list[str]:
        """Partition and persist chunks to lakehouse storage.

        Args:
            chunks: List of Chunk objects containing computed vector embeddings.

        Returns:
            List of URIs or filesystem paths of created Parquet files.

        Raises:
            ValueError: If any chunk lacks an embedding vector.
        """
        if not chunks:
            return []

        # Validate that all chunks have embeddings
        missing_embeddings = [c.chunk_id for c in chunks if c.embedding is None or len(c.embedding) == 0]
        if missing_embeddings:
            raise ValueError(
                f"Cannot write to Parquet lakehouse: {len(missing_embeddings)} chunks "
                f"are missing vector embeddings (e.g. {missing_embeddings[:3]})."
            )

        # Group chunks by partition key (domain, resolved_date)
        partitions: dict[tuple[str, date], list[Chunk]] = {}
        for chunk in chunks:
            domain_val = chunk.domain.value if isinstance(chunk.domain, Enum) else str(chunk.domain)
            resolved_dt = self.partition_resolver.resolve_date(chunk.filing_date)
            key = (domain_val.lower().strip(), resolved_dt)
            partitions.setdefault(key, []).append(chunk)

        written_paths: list[str] = []

        for (dom, dt), group_chunks in partitions.items():
            rel_path = self.partition_resolver.resolve_partition_path(
                domain=dom,
                filing_date=dt,
                batch_id=uuid4().hex,
            )

            # Convert chunks to list of row dicts conforming to Arrow schema
            records: list[dict[str, Any]] = []
            for c in group_chunks:
                row = c.to_parquet_dict()
                # Ensure embedding is a list of floats
                if isinstance(row.get("embedding"), list):
                    row["embedding"] = [float(x) for x in row["embedding"]]
                records.append(row)

            # Build PyArrow Table with explicit schema
            table = pa.Table.from_pylist(records, schema=self.schema)

            # Serialize table to in-memory bytes with Snappy compression
            sink_buffer = io.BytesIO()
            pq.write_table(
                table,
                sink_buffer,
                compression=self.compression,
                version="2.6",
            )
            parquet_bytes = sink_buffer.getvalue()

            # Write through storage backend
            stored_uri = self.storage_backend.write_bytes(rel_path, parquet_bytes)
            written_paths.append(stored_uri)

            logger.info(
                "Wrote %d chunks to Parquet lakehouse: %s (%d bytes)",
                len(group_chunks),
                stored_uri,
                len(parquet_bytes),
            )

        return written_paths


# -----------------------------------------------------------------------------
# Factory Provider
# -----------------------------------------------------------------------------


def get_parquet_sink(
    settings: Settings | None = None,
    storage_backend: StorageBackendProtocol | None = None,
) -> ParquetSink:
    """Dependency injection factory for ParquetSink."""
    cfg = settings or get_settings()
    backend = storage_backend or get_storage_backend(cfg)
    return ParquetSink(storage_backend=backend)
