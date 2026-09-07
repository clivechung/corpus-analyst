"""Tests for Phase 5 Hive-Partitioned Parquet Sink (LAK-01, LAK-02s).

Verifies SEAM-PARQUET-SINK and SEAM-LAKEHOUSE-STORAGE:
- Hive partition directory path resolution (/data/lake/domain=.../year=.../month=.../day=.../*.parquet)
- Date fallback handling when filing_date is None
- Strict PRD Section 4.3 11-column Arrow schema compliance
- Vector embedding list roundtrip and precision
- Multi-partition batch routing
- Pluggable storage backend integration (LocalStorageBackend, AzureBlobStorageBackend)
- Error handling when chunks lack embeddings
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from src.common.models import Chunk, DomainType, FormType
from src.common.storage import LocalStorageBackend, StorageBackendProtocol
from src.ingestion.parquet_sink import (
    HivePartitionResolver,
    ParquetSink,
    ParquetSinkProtocol,
    get_parquet_schema,
)


class TestParquetSinkSeam:
    """Test suite validating SEAM-PARQUET-SINK and SEAM-LAKEHOUSE-STORAGE."""

    def test_satisfies_parquet_sink_protocol(self, tmp_path: Path) -> None:
        """Verify ParquetSink satisfies ParquetSinkProtocol."""
        storage = LocalStorageBackend(base_path=str(tmp_path))
        sink = ParquetSink(storage_backend=storage)
        assert isinstance(sink, ParquetSinkProtocol)

    def test_hive_partition_resolver_formatting(self) -> None:
        """Verify Hive partition path formatting matches PRD specification."""
        resolver = HivePartitionResolver()
        target_date = date(2026, 2, 25)

        rel_path = resolver.resolve_partition_path(
            domain="finance",
            filing_date=target_date,
            batch_id="test-batch-123",
        )
        assert rel_path == "domain=finance/year=2026/month=02/day=25/test-batch-123.parquet"

    def test_hive_partition_resolver_date_fallback(self) -> None:
        """Verify resolver falls back to current UTC date when filing_date is None."""
        resolver = HivePartitionResolver()
        rel_path = resolver.resolve_partition_path(
            domain="literature",
            filing_date=None,
            batch_id="batch-lit",
        )
        assert rel_path.startswith("domain=literature/year=")
        assert "/month=" in rel_path
        assert "/day=" in rel_path
        assert rel_path.endswith("/batch-lit.parquet")

    def test_parquet_schema_definition(self) -> None:
        """Verify schema defines all 11 required columns with strict Arrow types."""
        schema = get_parquet_schema()
        field_names = schema.names

        expected_fields = [
            "chunk_id",
            "doc_id",
            "domain",
            "source_filename",
            "form_type",
            "filing_date",
            "section",
            "is_table",
            "text",
            "embedding",
            "metadata_json",
        ]
        assert field_names == expected_fields
        assert schema.field("filing_date").type == pa.date32()
        assert schema.field("is_table").type == pa.bool_()
        assert schema.field("embedding").type == pa.list_(pa.float32())

    def test_parquet_sink_writes_valid_parquet_file(self, tmp_path: Path) -> None:
        """Verify ParquetSink writes a valid Snappy-compressed Parquet file readable by PyArrow."""
        storage = LocalStorageBackend(base_path=str(tmp_path))
        sink = ParquetSink(storage_backend=storage)

        embedding = [0.1 * (i % 10) for i in range(384)]
        chunk = Chunk(
            doc_id="sec-10k-001",
            domain=DomainType.FINANCE,
            source_filename="nvda_2026.htm",
            form_type=FormType.SEC_10K,
            filing_date=date(2026, 2, 25),
            section="Item 1A - Risk Factors",
            is_table=False,
            text="Market demand for datacenter accelerators remains strong.",
            embedding=embedding,
            page_number=12,
            token_count=120,
            metadata={"parent_chunk_id": "parent-123"},
        )

        written_paths = sink.write_chunks([chunk])
        assert len(written_paths) == 1

        written_file = Path(written_paths[0])
        assert written_file.exists()

        # Read back table with PyArrow
        table = pq.read_table(written_file)
        assert table.num_rows == 1
        assert table.num_columns == 11

        row = table.to_pylist()[0]
        assert row["doc_id"] == "sec-10k-001"
        assert row["domain"] == "finance"
        assert row["source_filename"] == "nvda_2026.htm"
        assert row["form_type"] == "10-K"
        assert row["filing_date"] == date(2026, 2, 25)
        assert row["section"] == "Item 1A - Risk Factors"
        assert row["is_table"] is False
        assert row["text"] == "Market demand for datacenter accelerators remains strong."
        assert len(row["embedding"]) == 384
        assert pytest.approx(row["embedding"][0], abs=1e-4) == 0.0
        assert pytest.approx(row["embedding"][1], abs=1e-4) == 0.1

        # Check metadata_json unpacking
        meta = json.loads(row["metadata_json"])
        assert meta["page_number"] == 12
        assert meta["token_count"] == 120
        assert meta["parent_chunk_id"] == "parent-123"

    def test_parquet_sink_multi_partition_routing(self, tmp_path: Path) -> None:
        """Verify chunks with different domains or dates are routed to separate Hive partitions."""
        storage = LocalStorageBackend(base_path=str(tmp_path))
        sink = ParquetSink(storage_backend=storage)

        emb = [0.05] * 384
        chunk_fin_2026 = Chunk(
            doc_id="doc-1",
            domain=DomainType.FINANCE,
            source_filename="fin1.htm",
            filing_date=date(2026, 2, 25),
            text="Fin 2026",
            embedding=emb,
        )
        chunk_fin_2025 = Chunk(
            doc_id="doc-2",
            domain=DomainType.FINANCE,
            source_filename="fin2.htm",
            filing_date=date(2025, 2, 25),
            text="Fin 2025",
            embedding=emb,
        )
        chunk_lit = Chunk(
            doc_id="doc-3",
            domain=DomainType.LITERATURE,
            source_filename="lit.txt",
            filing_date=date(2026, 2, 25),
            text="Lit 2026",
            embedding=emb,
        )

        written_paths = sink.write_chunks([chunk_fin_2026, chunk_fin_2025, chunk_lit])
        assert len(written_paths) == 3

        # Assert all three partition paths exist
        assert any("domain=finance/year=2026/month=02/day=25" in p for p in written_paths)
        assert any("domain=finance/year=2025/month=02/day=25" in p for p in written_paths)
        assert any("domain=literature/year=2026/month=02/day=25" in p for p in written_paths)

    def test_parquet_sink_missing_embedding_raises_error(self, tmp_path: Path) -> None:
        """Verify writing chunks with missing embeddings raises ValueError."""
        storage = LocalStorageBackend(base_path=str(tmp_path))
        sink = ParquetSink(storage_backend=storage)

        chunk = Chunk(
            doc_id="doc-err",
            domain=DomainType.FINANCE,
            source_filename="err.htm",
            text="Missing embedding chunk",
            embedding=None,
        )
        with pytest.raises(ValueError, match="missing vector embeddings"):
            sink.write_chunks([chunk])

    def test_pluggable_storage_backend_azure_mock(self) -> None:
        """Verify ParquetSink writes via StorageBackendProtocol write_bytes."""
        mock_backend = MagicMock(spec=StorageBackendProtocol)
        mock_backend.write_bytes.return_value = "azure://corpus-lake/domain=finance/year=2026/month=02/day=25/batch.parquet"

        sink = ParquetSink(storage_backend=mock_backend)
        chunk = Chunk(
            doc_id="doc-az",
            domain=DomainType.FINANCE,
            source_filename="az.htm",
            filing_date=date(2026, 2, 25),
            text="Azure upload test",
            embedding=[0.1] * 384,
        )

        paths = sink.write_chunks([chunk])
        assert len(paths) == 1
        assert paths[0].startswith("azure://")
        assert mock_backend.write_bytes.called

        call_path = mock_backend.write_bytes.call_args[0][0]
        assert call_path.startswith("domain=finance/year=2026/month=02/day=25/")
        assert call_path.endswith(".parquet")

    def test_duckdb_vector_search_over_parquet(self, tmp_path: Path) -> None:
        """Verify DuckDB can query Parquet output and calculate array_cosine_similarity."""
        import duckdb

        storage = LocalStorageBackend(base_path=str(tmp_path))
        sink = ParquetSink(storage_backend=storage)

        # Create two chunks with orthogonal embeddings
        chunk1 = Chunk(
            doc_id="sec-1",
            domain=DomainType.FINANCE,
            source_filename="nvda.htm",
            text="High performance GPU computing",
            embedding=[1.0, 0.0, 0.0] + [0.0] * 381,
        )
        chunk2 = Chunk(
            doc_id="sec-2",
            domain=DomainType.FINANCE,
            source_filename="aapl.htm",
            text="Consumer smartphone hardware",
            embedding=[0.0, 1.0, 0.0] + [0.0] * 381,
        )

        sink.write_chunks([chunk1, chunk2])

        con = duckdb.connect(":memory:")
        parquet_glob = f"{tmp_path}/**/*.parquet"

        query_vec = [1.0, 0.0, 0.0] + [0.0] * 381
        query = f"""
        SELECT
            chunk_id,
            source_filename,
            text,
            array_cosine_similarity(embedding::FLOAT[384], ?::FLOAT[384]) AS similarity_score
        FROM read_parquet('{parquet_glob}')
        ORDER BY similarity_score DESC
        """
        results = con.execute(query, [query_vec]).fetchall()
        assert len(results) == 2

        # chunk1 should have similarity ~1.0
        assert results[0][1] == "nvda.htm"
        assert pytest.approx(results[0][3], abs=1e-4) == 1.0

        # chunk2 should have similarity ~0.0
        assert results[1][1] == "aapl.htm"
        assert pytest.approx(results[1][3], abs=1e-4) == 0.0

    def test_end_to_end_parser_embedder_parquet_duckdb_pipeline(self, tmp_path: Path) -> None:
        """Verify full SEAM-INGESTION-LAKE-E2E pipeline: HTML -> Parser -> Splitter -> Embedder -> ParquetSink -> DuckDB."""
        import duckdb

        from src.ingestion.embedder import MockEmbedder
        from src.ingestion.parser import DocumentParser

        lake_dir = tmp_path / "lake"
        storage = LocalStorageBackend(base_path=str(lake_dir))
        sink = ParquetSink(storage_backend=storage)
        embedder = MockEmbedder(dimension=384)

        parser = DocumentParser(embedder=embedder, sink=sink)

        doc_file = tmp_path / "NVDA_10-K_2026.htm"
        doc_file.write_text(
            """
            <html>
                <body>
                    <h1>Item 1A. Risk Factors</h1>
                    <p>Demand for accelerated computing architectures depends on datacenter expansion.</p>
                    <h1>Item 8. Financial Statements</h1>
                    <table>
                        <tr><th>Year</th><th>Revenue ($M)</th></tr>
                        <tr><td>2025</td><td>60922</td></tr>
                        <tr><td>2026</td><td>115000</td></tr>
                    </table>
                </body>
            </html>
            """,
            encoding="utf-8",
        )

        result = parser.process(doc_file)
        assert result.success is True
        assert result.chunk_count >= 2
        assert len(result.parquet_paths) >= 1

        # DuckDB vector and partition verification
        con = duckdb.connect(":memory:")
        con.execute(f"CREATE VIEW lake_chunks AS SELECT * FROM read_parquet('{lake_dir}/**/*.parquet')")

        count_res = con.execute("SELECT count(*), count(distinct is_table) FROM lake_chunks").fetchone()
        assert count_res[0] >= 2
        assert count_res[1] == 2  # Has narrative and tabular

        # Check vector search over the view
        sample_emb = embedder.embed_text("Demand for accelerated computing architectures depends on datacenter expansion.")
        search_res = con.execute(
            """
            SELECT text, section, is_table, array_cosine_similarity(embedding::FLOAT[384], ?::FLOAT[384]) AS sim
            FROM lake_chunks
            ORDER BY sim DESC
            LIMIT 1
            """,
            [sample_emb],
        ).fetchone()

        assert "accelerated computing" in search_res[0]
        assert search_res[1] == "Item 1A - Risk Factors"
        assert search_res[2] is False
        assert pytest.approx(search_res[3], abs=1e-4) == 1.0


