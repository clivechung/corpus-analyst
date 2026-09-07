"""Tests for Phase 4 Chunk Data Contracts and Lakehouse Compatibility.

Verifies SEAM-CHUNKER:
- Table layout retention in chunk models
- PRD Section 4.3 Parquet schema dictionary conformity
- Secondary lineage fields and metadata serialization
"""

from __future__ import annotations

import json
from pathlib import Path
from uuid import UUID

from src.common.models import Chunk, DomainType, FormType
from src.ingestion.parser import DocumentParser


class TestChunkerSeam:
    """Test suite validating Chunk contracts and lakehouse storage readiness."""

    def test_chunk_data_contract_parquet_compliance(self, tmp_path: Path) -> None:
        """Verify Chunk objects produced by DocumentParser convert cleanly to PRD Parquet schema."""
        html_file = tmp_path / "sample.htm"
        html_file.write_text(
            """
            <html>
                <body>
                    <h2>Item 1A. Risk Factors</h2>
                    <p>Substantial risks exist in AI hardware supply networks.</p>
                </body>
            </html>
            """,
            encoding="utf-8",
        )

        parser = DocumentParser()
        chunks = parser.parse(html_file)

        assert len(chunks) > 0
        chunk = chunks[0]

        parquet_row = chunk.to_parquet_dict()

        # PRD Section 4.3 required schema fields:
        # - chunk_id: STRING (UUIDv4)
        # - doc_id: STRING
        # - domain: STRING
        # - source_filename: STRING
        # - form_type: STRING
        # - filing_date: DATE32
        # - section: STRING
        # - is_table: BOOLEAN
        # - text: STRING
        # - embedding: LIST<FLOAT>
        # - metadata_json: STRING
        assert isinstance(parquet_row["chunk_id"], str)
        UUID(parquet_row["chunk_id"])  # Valid UUID string

        assert isinstance(parquet_row["doc_id"], str)
        assert isinstance(parquet_row["domain"], str)
        assert isinstance(parquet_row["source_filename"], str)
        assert isinstance(parquet_row["form_type"], str)
        assert isinstance(parquet_row["section"], str)
        assert isinstance(parquet_row["is_table"], bool)
        assert isinstance(parquet_row["text"], str)
        assert isinstance(parquet_row["metadata_json"], str)

        meta = json.loads(parquet_row["metadata_json"])
        assert isinstance(meta, dict)
        assert "token_count" in meta

    def test_financial_table_chunks_retain_layout_in_text(self, tmp_path: Path) -> None:
        """Verify financial tables preserve HTML structure in Chunk.text and Chunk.metadata."""
        table_html = """
        <html>
            <body>
                <h1>Item 8. Financial Statements</h1>
                <table class="financial-data">
                    <tr><th>Quarter</th><th>Revenue ($B)</th></tr>
                    <tr><td>Q1</td><td>26.0</td></tr>
                    <tr><td>Q2</td><td>30.0</td></tr>
                </table>
            </body>
        </html>
        """
        html_file = tmp_path / "balance_sheet.htm"
        html_file.write_text(table_html, encoding="utf-8")

        parser = DocumentParser()
        chunks = parser.parse(html_file)

        table_chunks = [c for c in chunks if c.is_table]
        assert len(table_chunks) == 1

        chunk = table_chunks[0]
        assert chunk.is_table is True
        assert "<table" in chunk.text
        assert "<tr>" in chunk.text
        assert "26.0" in chunk.text
        assert chunk.metadata.get("table_html") == chunk.text

    def test_document_parser_bounds_all_chunks_to_max_tokens(self, tmp_path: Path) -> None:
        """Verify DocumentParser with integrated splitter ensures no chunk exceeds 512 tokens."""
        # Create a document with a massive section (~1,500 tokens) in a single continuous paragraph
        sentences = [
            f"Sentence {i}: The company is subject to complex trade regulations and export controls "
            f"impacting advanced graphics processing units and high-bandwidth memory architectures across global markets."
            for i in range(1, 60)
        ]
        html_content = f"""
        <html>
            <body>
                <h1>Item 1A. Risk Factors</h1>
                <p>{' '.join(sentences)}</p>
            </body>
        </html>
        """
        html_file = tmp_path / "oversized_risks.htm"
        html_file.write_text(html_content, encoding="utf-8")

        parser = DocumentParser()
        chunks = parser.parse(html_file)

        assert len(chunks) > 1
        for idx, chunk in enumerate(chunks):
            assert chunk.token_count is not None
            assert chunk.token_count <= 512, f"Chunk {idx} token count {chunk.token_count} exceeds 512"
            assert chunk.section == "Item 1A - Risk Factors"

        # Check that parent lineage was established on split chunks
        split_chunks = [c for c in chunks if c.parent_chunk_id is not None]
        assert len(split_chunks) > 0

        # Verify Parquet contract for split chunk
        sample_split = split_chunks[0]
        parquet_dict = sample_split.to_parquet_dict()
        meta = json.loads(parquet_dict["metadata_json"])
        assert "parent_chunk_id" in meta
        assert "sub_chunk_index" in meta

    def test_oversized_table_split_contract(self, tmp_path: Path) -> None:
        """Verify an oversized table is partitioned while preserving is_table and Parquet compatibility."""
        rows = [
            f"<tr><td>Item {i}</td><td>Value {i * 1234}</td><td>Description of row {i} with financial metrics</td></tr>"
            for i in range(50)
        ]
        html_content = f"""
        <html>
            <body>
                <h1>Item 8. Financial Statements</h1>
                <table>
                    <thead><tr><th>Item</th><th>Value</th><th>Description</th></tr></thead>
                    <tbody>{''.join(rows)}</tbody>
                </table>
            </body>
        </html>
        """
        html_file = tmp_path / "oversized_table.htm"
        html_file.write_text(html_content, encoding="utf-8")

        parser = DocumentParser()
        chunks = parser.parse(html_file)

        table_chunks = [c for c in chunks if c.is_table]
        assert len(table_chunks) >= 1
        for chunk in table_chunks:
            assert chunk.is_table is True
            assert chunk.token_count <= 512
            row = chunk.to_parquet_dict()
            assert row["is_table"] is True

