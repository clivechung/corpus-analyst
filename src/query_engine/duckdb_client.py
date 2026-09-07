"""DuckDB Lakehouse In-Process Vector Retrieval & SQL Client (QRY-01, QRY-02).

Follows TREM-Python principles:
- Testable: In-memory or path-based DuckDB client implementing DuckDBClientProtocol.
- Readable: Explicit SQL query construction, type annotations, and structured logging.
- Extensible: Support for arbitrary Parquet metadata predicates, Hive partition keys,
  and dynamic vector dimensionalities.
- Maintainable: Safe read-only guards for ad-hoc console queries, graceful fallback
  when lakehouse partitions are empty or missing, and automatic PyArrow schema bridging.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import date
from enum import Enum
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

import duckdb

from src.common.config import Settings, get_settings
from src.common.models import DomainType, FormType, QueryRequest, RetrievedContextChunk

logger = logging.getLogger(__name__)

# Disallowed SQL statement prefixes for the read-only query console
FORBIDDEN_SQL_PATTERNS = re.compile(
    r"\b(DROP|DELETE|INSERT|UPDATE|ALTER|ATTACH|CREATE|REPLACE|COPY|TRUNCATE|GRANT|REVOKE)\b",
    re.IGNORECASE,
)


# -----------------------------------------------------------------------------
# DuckDB Client Protocol (QRY-01)
# -----------------------------------------------------------------------------


@runtime_checkable
class DuckDBClientProtocol(Protocol):
    """Protocol defining the public interface for DuckDB Lakehouse Retrieval."""

    def search(
        self,
        request: QueryRequest,
        query_vector: list[float],
    ) -> list[RetrievedContextChunk]:
        """Execute vector similarity search with metadata and Hive partition pushdown."""
        ...

    def execute_sql(
        self,
        query: str,
        params: list[Any] | None = None,
    ) -> tuple[list[str], list[tuple[Any, ...]]]:
        """Execute safe read-only SQL query returning (column_names, rows)."""
        ...

    def get_lake_stats(self) -> dict[str, Any]:
        """Inspect lakehouse storage directory and return partition/file metrics."""
        ...


# -----------------------------------------------------------------------------
# DuckDB Lakehouse Client Implementation (QRY-01, QRY-02)
# -----------------------------------------------------------------------------


class DuckDBLakehouseClient:
    """In-process DuckDB query engine client for Hive-partitioned Parquet vector search."""

    def __init__(
        self,
        settings: Settings | None = None,
        database_path: str = ":memory:",
    ) -> None:
        self.settings = settings or get_settings()
        self.database_path = database_path
        # Connect to DuckDB; in-memory database per process avoids write lock contention
        self._con = duckdb.connect(database=self.database_path, read_only=False)
        logger.info(
            "Initialized DuckDBLakehouseClient (db='%s', lake_path='%s')",
            self.database_path,
            self.settings.paths.lake_path,
        )

    @property
    def lake_path(self) -> Path:
        """Resolved path to the Parquet data lake."""
        return Path(self.settings.paths.lake_path)

    def _resolve_glob_pattern(self, domain: str | DomainType | None = None) -> tuple[str, list[Path]]:
        """Resolve Parquet file glob pattern and verify matching files exist."""
        lake = self.lake_path
        if not lake.exists():
            return "", []

        domain_str = domain.value if isinstance(domain, Enum) else str(domain or "").strip()

        if domain_str:
            clean_domain = domain_str.lower()
            pattern = str(lake / f"domain={clean_domain}/**/*.parquet")
            matching_files = list(lake.glob(f"domain={clean_domain}/**/*.parquet"))
        else:
            pattern = str(lake / "**/*.parquet")
            matching_files = list(lake.glob("**/*.parquet"))

        return pattern, matching_files

    def search(
        self,
        request: QueryRequest,
        query_vector: list[float],
    ) -> list[RetrievedContextChunk]:
        """Execute vector similarity search with push-down predicate filtering over Parquet files.

        Implements:
        - QRY-01: array_cosine_similarity over globbed Parquet embeddings.
        - QRY-02: Hive partition pushdown (domain, year, month, day) and metadata predicates.
        """
        if not query_vector:
            logger.warning("Empty query vector provided to search; returning empty list.")
            return []

        pattern, matching_files = self._resolve_glob_pattern(request.domain)
        if not matching_files:
            logger.info("No Parquet files found for domain '%s' at %s", request.domain, self.lake_path)
            return []

        dim = len(query_vector)

        # Build parameterized pushdown WHERE clauses
        pushdown_clauses: list[str] = []
        sql_params: list[Any] = []

        # Predicate 1: Domain filter (Directory & Partition Pushdown)
        if request.domain:
            domain_str = request.domain.value if isinstance(request.domain, Enum) else str(request.domain)
            pushdown_clauses.append("domain = ?")
            sql_params.append(domain_str.lower().strip())

        # Predicate 2: Form Type filter
        if request.form_type:
            form_str = request.form_type.value if isinstance(request.form_type, Enum) else str(request.form_type)
            pushdown_clauses.append("form_type = ?")
            sql_params.append(form_str)

        # Predicate 3: Temporal filters (Filing Date / Year pushdown)
        if request.start_date:
            pushdown_clauses.append("filing_date >= ?")
            sql_params.append(request.start_date)

        if request.end_date:
            pushdown_clauses.append("filing_date <= ?")
            sql_params.append(request.end_date)

        # Predicate 4: Tabular filter
        if request.is_table_only:
            pushdown_clauses.append("is_table = true")

        where_pushdown_sql = " AND ".join(pushdown_clauses)
        if where_pushdown_sql:
            where_pushdown_sql = f"WHERE {where_pushdown_sql}"

        # Outer threshold filter
        threshold = request.similarity_threshold
        top_k = max(1, request.top_k)

        # Parameter order:
        # 1. read_parquet glob pattern
        # 2. query vector parameter for cosine similarity
        # 3. pushdown clause parameters
        # 4. threshold parameter
        # 5. top_k parameter
        query_sql = f"""
        WITH candidates AS (
            SELECT
                chunk_id,
                source_filename,
                section,
                text,
                is_table,
                form_type,
                filing_date,
                metadata_json,
                array_cosine_similarity(embedding::FLOAT[{dim}], ?::FLOAT[{dim}]) AS similarity_score
            FROM read_parquet(?, hive_partitioning=true)
            {where_pushdown_sql}
        )
        SELECT
            chunk_id,
            source_filename,
            section,
            text,
            is_table,
            form_type,
            filing_date,
            metadata_json,
            similarity_score
        FROM candidates
        WHERE similarity_score >= ?
        ORDER BY similarity_score DESC
        LIMIT ?
        """

        full_params: list[Any] = [query_vector, pattern, *sql_params, threshold, top_k]

        cursor = self._con.cursor()
        try:
            results = cursor.execute(query_sql, full_params).fetchall()
        except duckdb.BinderException as exc:
            # If array_cosine_similarity fails due to vector dimension or list typing, fallback to list_cosine_similarity
            logger.warning("array_cosine_similarity failed (%s); trying list_cosine_similarity fallback.", exc)
            fallback_sql = f"""
            WITH candidates AS (
                SELECT
                    chunk_id,
                    source_filename,
                    section,
                    text,
                    is_table,
                    form_type,
                    filing_date,
                    metadata_json,
                    list_cosine_similarity(embedding, ?::FLOAT[]) AS similarity_score
                FROM read_parquet(?, hive_partitioning=true)
                {where_pushdown_sql}
            )
            SELECT
                chunk_id,
                source_filename,
                section,
                text,
                is_table,
                form_type,
                filing_date,
                metadata_json,
                similarity_score
            FROM candidates
            WHERE similarity_score >= ?
            ORDER BY similarity_score DESC
            LIMIT ?
            """
            results = cursor.execute(fallback_sql, full_params).fetchall()
        finally:
            cursor.close()

        chunks: list[RetrievedContextChunk] = []
        for row in results:
            (
                chunk_id,
                source_filename,
                section,
                text,
                is_table,
                form_type,
                filing_date_val,
                meta_json,
                similarity_score,
            ) = row

            # Parse metadata_json safely
            metadata_dict: dict[str, Any] = {}
            if meta_json:
                try:
                    metadata_dict = json.loads(meta_json)
                except Exception:
                    metadata_dict = {"raw": meta_json}

            chunks.append(
                RetrievedContextChunk(
                    chunk_id=str(chunk_id),
                    source_filename=str(source_filename),
                    section=str(section),
                    text=str(text),
                    is_table=bool(is_table),
                    similarity_score=float(similarity_score),
                    form_type=str(form_type) if form_type is not None else None,
                    filing_date=filing_date_val if isinstance(filing_date_val, date) else None,
                    metadata=metadata_dict,
                )
            )

        return chunks

    def execute_sql(
        self,
        query: str,
        params: list[Any] | None = None,
    ) -> tuple[list[str], list[tuple[Any, ...]]]:
        """Execute a read-only SQL query against DuckDB.

        Protected against mutative DDL/DML expressions to ensure safety in the UI console.
        """
        cleaned_query = query.strip()
        if not cleaned_query:
            return [], []

        if FORBIDDEN_SQL_PATTERNS.search(cleaned_query):
            logger.warning("Rejected attempt to execute forbidden SQL query: %s", cleaned_query)
            raise PermissionError("Mutative or administrative SQL operations are strictly forbidden in read-only console.")

        cursor = self._con.cursor()
        try:
            if params:
                cursor.execute(cleaned_query, params)
            else:
                cursor.execute(cleaned_query)

            columns = [desc[0] for desc in cursor.description] if cursor.description else []
            rows = cursor.fetchall()
            return columns, rows
        finally:
            cursor.close()

    def get_lake_stats(self) -> dict[str, Any]:
        """Compute lakehouse partition statistics and file metrics."""
        lake = self.lake_path
        if not lake.exists():
            return {
                "total_parquet_files": 0,
                "total_size_bytes": 0,
                "domains": [],
                "partitions": [],
            }

        files = list(lake.glob("**/*.parquet"))
        total_size = sum(f.stat().st_size for f in files if f.is_file())

        domains: set[str] = set()
        partitions: list[str] = []

        for f in files:
            rel = f.relative_to(lake)
            parts = rel.parts
            for p in parts:
                if p.startswith("domain="):
                    domains.add(p.split("=", 1)[1])
            if len(parts) > 1:
                partitions.append(str(rel.parent))

        return {
            "total_parquet_files": len(files),
            "total_size_bytes": total_size,
            "domains": sorted(domains),
            "partitions": sorted(set(partitions)),
        }


# -----------------------------------------------------------------------------
# Dependency Provider (TREM: Testable)
# -----------------------------------------------------------------------------

_GLOBAL_CLIENT: DuckDBLakehouseClient | None = None


def get_duckdb_client(settings: Settings | None = None) -> DuckDBLakehouseClient:
    """Dependency provider for DuckDBLakehouseClient."""
    global _GLOBAL_CLIENT
    if _GLOBAL_CLIENT is None:
        _GLOBAL_CLIENT = DuckDBLakehouseClient(settings=settings)
    return _GLOBAL_CLIENT

