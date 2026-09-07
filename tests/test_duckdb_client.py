"""Unit tests for Phase 6 DuckDB Lakehouse Client and Vector Retriever (SEAM-DUCKDB-RETRIEVER).

Follows TREM principles:
- Testable: In-memory DuckDB connection over isolated temporary Hive Parquet directory.
- Readable: Explicit assertions comparing known-vector cosine similarities against expected order.
- Extensible: Tests DuckDBClientProtocol contract compliance.
- Maintainable: Clean fixtures with synthetic PyArrow Parquet tables matching PRD Section 4.3 schema.
"""

from __future__ import annotations

import os
from datetime import date
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from src.common.config import Settings
from src.common.models import QueryRequest, RetrievedContextChunk
from src.query_engine.duckdb_client import (
    DuckDBClientProtocol,
    DuckDBLakehouseClient,
    get_duckdb_client,
)


@pytest.fixture
def test_lake_dir(tmp_path: Path) -> Path:
    """Create a temporary Hive-partitioned Parquet lakehouse with known synthetic vectors."""
    lake_base = tmp_path / "lake"

    # 1. Finance partition (2024-02-21)
    fin_dir = lake_base / "domain=finance" / "year=2024" / "month=02" / "day=21"
    fin_dir.mkdir(parents=True, exist_ok=True)

    schema = pa.schema(
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

    # Chunk 1: [1.0, 0.0, 0.0] - NVDA MD&A text
    # Chunk 2: [0.0, 1.0, 0.0] - NVDA Balance sheet table
    fin_table = pa.Table.from_pydict(
        {
            "chunk_id": ["c1", "c2"],
            "doc_id": ["doc_nvda_2024", "doc_nvda_2024"],
            "domain": ["finance", "finance"],
            "source_filename": ["NVDA_10-K_20240221.htm", "NVDA_10-K_20240221.htm"],
            "form_type": ["10-K", "10-K"],
            "filing_date": [date(2024, 2, 21), date(2024, 2, 21)],
            "section": ["Item 7 - MD&A", "Item 8 - Consolidated Financial Statements"],
            "is_table": [False, True],
            "text": [
                "NVIDIA gross margin expanded significantly to 75.0% for fiscal year 2024.",
                "Cash and cash equivalents totaled $7,280 million.",
            ],
            "embedding": [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]],
            "metadata_json": ['{"page_number": 45}', '{"page_number": 72}'],
        },
        schema=schema,
    )
    pq.write_table(fin_table, fin_dir / "batch_fin_01.parquet")

    # 2. Finance partition (2024-05-15) - 10-Q filing
    # Chunk 3: [0.7071, 0.7071, 0.0] - NVDA 10-Q text
    fin_q_dir = lake_base / "domain=finance" / "year=2024" / "month=05" / "day=15"
    fin_q_dir.mkdir(parents=True, exist_ok=True)
    fin_q_table = pa.Table.from_pydict(
        {
            "chunk_id": ["c3"],
            "doc_id": ["doc_nvda_q1_2025"],
            "domain": ["finance"],
            "source_filename": ["NVDA_10-Q_20240515.htm"],
            "form_type": ["10-Q"],
            "filing_date": [date(2024, 5, 15)],
            "section": ["Item 2 - Management Discussion"],
            "is_table": [False],
            "text": ["Data Center revenue continued exponential growth across hyperscale customers."],
            "embedding": [[0.70710678, 0.70710678, 0.0]],
            "metadata_json": ['{"page_number": 18}'],
        },
        schema=schema,
    )
    pq.write_table(fin_q_table, fin_q_dir / "batch_fin_02.parquet")

    # 3. Literature partition (2023-01-10)
    # Chunk 4: [1.0, 0.0, 0.0] - Tale of Two Cities
    lit_dir = lake_base / "domain=literature" / "year=2023" / "month=01" / "day=10"
    lit_dir.mkdir(parents=True, exist_ok=True)
    lit_table = pa.Table.from_pydict(
        {
            "chunk_id": ["c4"],
            "doc_id": ["doc_dickens"],
            "domain": ["literature"],
            "source_filename": ["two_cities.txt"],
            "form_type": ["BOOK"],
            "filing_date": [date(2023, 1, 10)],
            "section": ["Chapter 1"],
            "is_table": [False],
            "text": ["It was the best of times, it was the worst of times."],
            "embedding": [[1.0, 0.0, 0.0]],
            "metadata_json": ['{"page_number": 1}'],
        },
        schema=schema,
    )
    pq.write_table(lit_table, lit_dir / "batch_lit_01.parquet")

    return lake_base


@pytest.fixture
def test_settings(test_lake_dir: Path) -> Settings:
    """Create settings instance pointing to the test lakehouse."""
    settings = Settings()
    settings.paths.lake_path = str(test_lake_dir)
    return settings


class TestDuckDBLakehouseClientSeam:
    """Test suite for SEAM-DUCKDB-RETRIEVER."""

    def test_satisfies_protocol(self, test_settings: Settings) -> None:
        """Verify DuckDBLakehouseClient conforms to DuckDBClientProtocol."""
        client = DuckDBLakehouseClient(settings=test_settings)
        assert isinstance(client, DuckDBClientProtocol)

    def test_vector_similarity_ordering(self, test_settings: Settings) -> None:
        """Verify chunks are returned in descending order of cosine similarity score.

        Target vector is [1.0, 0.0, 0.0]:
        - c1 ([1.0, 0.0, 0.0]): cosine similarity = 1.0
        - c3 ([0.7071, 0.7071, 0.0]): cosine similarity ~ 0.7071
        - c2 ([0.0, 1.0, 0.0]): cosine similarity = 0.0
        """
        client = DuckDBLakehouseClient(settings=test_settings)
        request = QueryRequest(
            question="What was NVIDIA's gross margin?",
            domain="finance",
            top_k=5,
            similarity_threshold=-1.0,
        )
        query_vector = [1.0, 0.0, 0.0]

        results = client.search(request, query_vector=query_vector)

        assert len(results) == 3
        assert results[0].chunk_id == "c1"
        assert pytest.approx(results[0].similarity_score, abs=1e-4) == 1.0
        assert results[1].chunk_id == "c3"
        assert pytest.approx(results[1].similarity_score, abs=1e-4) == 0.7071
        assert results[2].chunk_id == "c2"
        assert pytest.approx(results[2].similarity_score, abs=1e-4) == 0.0

    def test_hive_partition_pushdown_domain(self, test_settings: Settings) -> None:
        """Verify querying domain='finance' excludes chunks from 'literature' partition."""
        client = DuckDBLakehouseClient(settings=test_settings)
        request = QueryRequest(
            question="Any query",
            domain="finance",
            top_k=10,
        )
        # Even though c4 has vector [1, 0, 0], it is in domain=literature and should be pruned
        results = client.search(request, query_vector=[1.0, 0.0, 0.0])

        chunk_ids = [r.chunk_id for r in results]
        assert "c4" not in chunk_ids
        assert "c1" in chunk_ids

    def test_metadata_predicate_is_table(self, test_settings: Settings) -> None:
        """Verify is_table_only=True restricts results strictly to tabular chunks."""
        client = DuckDBLakehouseClient(settings=test_settings)
        request = QueryRequest(
            question="Cash reserves table",
            domain="finance",
            top_k=5,
            is_table_only=True,
        )
        results = client.search(request, query_vector=[0.0, 1.0, 0.0])

        assert len(results) == 1
        assert results[0].chunk_id == "c2"
        assert results[0].is_table is True

    def test_metadata_predicate_form_type(self, test_settings: Settings) -> None:
        """Verify filtering by form_type excludes other document classifications."""
        client = DuckDBLakehouseClient(settings=test_settings)
        request = QueryRequest(
            question="Quarterly update",
            domain="finance",
            form_type="10-Q",
            top_k=5,
        )
        results = client.search(request, query_vector=[0.7071, 0.7071, 0.0])

        assert len(results) == 1
        assert results[0].chunk_id == "c3"
        assert results[0].form_type == "10-Q"

    def test_date_range_filtering(self, test_settings: Settings) -> None:
        """Verify temporal filtering with start_date and end_date."""
        client = DuckDBLakehouseClient(settings=test_settings)
        # Filter for documents filed on or after 2024-03-01 (should exclude c1 and c2 from 2024-02-21)
        request = QueryRequest(
            question="Recent Q1 update",
            domain="finance",
            start_date=date(2024, 3, 1),
            top_k=5,
        )
        results = client.search(request, query_vector=[1.0, 0.0, 0.0])

        assert len(results) == 1
        assert results[0].chunk_id == "c3"
        assert results[0].filing_date == date(2024, 5, 15)

    def test_similarity_threshold_cutoff(self, test_settings: Settings) -> None:
        """Verify chunks with similarity below threshold are excluded."""
        client = DuckDBLakehouseClient(settings=test_settings)
        request = QueryRequest(
            question="Gross margin",
            domain="finance",
            similarity_threshold=0.8,
            top_k=5,
        )
        results = client.search(request, query_vector=[1.0, 0.0, 0.0])

        # Only c1 (1.0) exceeds 0.8; c3 (0.7071) and c2 (0.0) are cut off
        assert len(results) == 1
        assert results[0].chunk_id == "c1"

    def test_top_k_truncation(self, test_settings: Settings) -> None:
        """Verify top_k correctly limits candidate output length."""
        client = DuckDBLakehouseClient(settings=test_settings)
        request = QueryRequest(
            question="All finance chunks",
            domain="finance",
            top_k=1,
            similarity_threshold=-1.0,
        )
        results = client.search(request, query_vector=[1.0, 0.0, 0.0])

        assert len(results) == 1
        assert results[0].chunk_id == "c1"

    def test_empty_lakehouse_returns_empty_list(self, tmp_path: Path) -> None:
        """Verify querying a non-existent or empty lake returns [] without error."""
        settings = Settings()
        settings.paths.lake_path = str(tmp_path / "empty_lake")
        client = DuckDBLakehouseClient(settings=settings)

        request = QueryRequest(question="Anything", domain="finance", top_k=5)
        results = client.search(request, query_vector=[1.0, 0.0, 0.0])

        assert results == []

    def test_lake_stats_telemetry(self, test_settings: Settings) -> None:
        """Verify get_lake_stats returns accurate partition and file statistics."""
        client = DuckDBLakehouseClient(settings=test_settings)
        stats = client.get_lake_stats()

        assert stats["total_parquet_files"] == 3
        assert "finance" in stats["domains"]
        assert "literature" in stats["domains"]
        assert stats["total_size_bytes"] > 0

    def test_read_only_sql_console_execution(self, test_settings: Settings) -> None:
        """Verify execute_sql runs read-only SQL queries and returns columns and rows."""
        client = DuckDBLakehouseClient(settings=test_settings)
        cols, rows = client.execute_sql("SELECT 42 AS answer, 'corpus' AS name")
        assert cols == ["answer", "name"]
        assert rows == [(42, "corpus")]

    def test_read_only_sql_console_rejects_mutations(self, test_settings: Settings) -> None:
        """Verify execute_sql raises PermissionError when mutative SQL statements are submitted."""
        client = DuckDBLakehouseClient(settings=test_settings)
        mutative_queries = [
            "DROP TABLE users",
            "DELETE FROM chunks",
            "INSERT INTO t VALUES (1)",
            "UPDATE chunks SET text = 'hack'",
            "ALTER TABLE chunks ADD COLUMN x INT",
            "ATTACH 'test.db' AS db2",
        ]
        for query in mutative_queries:
            with pytest.raises(PermissionError):
                client.execute_sql(query)

