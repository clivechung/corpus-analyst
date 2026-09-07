"""Tests for Phase 4 ING-03: Structural Document Parsing & Table Preservation.

Verifies SEAM-PARSER:
- Format dispatch (HTML, TXT, JSON, PDF)
- Section hierarchy and context tracking (SEC Items & Book Chapters)
- Table detection and verbatim HTML table preservation (is_table = True)
- Companion .meta.json sidecar propagation
- Token count estimation
- Error handling with DocumentParsingError
- DocumentProcessorProtocol compliance and LifecycleManager integration
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from src.common.models import DomainType, FormType, IngestionStatus
from src.ingestion.lifecycle import DocumentProcessorProtocol, LifecycleManager
from src.ingestion.parser import (
    DocumentParser,
    DocumentParsingError,
    SectionTracker,
    estimate_token_count,
)


class TestParserSeam:
    """Test suite targeting the public boundaries of the document parsing engine."""

    def test_estimate_token_count_heuristic(self) -> None:
        """Verify token estimation produces non-zero, reasonable bounds."""
        assert estimate_token_count("") == 0
        assert estimate_token_count("   ") == 0

        text = "Item 1A. Risk Factors: The company faces competitive pressures in AI semiconductors."
        tokens = estimate_token_count(text)
        assert 10 <= tokens <= 25

    def test_section_tracker_sec_headers(self) -> None:
        """Verify SectionTracker correctly detects SEC 10-K/10-Q items and cascades context."""
        tracker = SectionTracker()
        assert tracker.current_section == "General"

        # SEC Item 1A
        detected = tracker.update("Item 1A. Risk Factors")
        assert detected == "Item 1A - Risk Factors"
        assert tracker.current_section == "Item 1A - Risk Factors"

        # Subsequent narrative element inherits active section
        assert tracker.get_active_section() == "Item 1A - Risk Factors"

        # SEC Item 7
        detected = tracker.update(
            "Item 7. Management's Discussion and Analysis of Financial Condition and Results of Operations"
        )
        assert detected == "Item 7 - Management's Discussion and Analysis"
        assert tracker.current_section == "Item 7 - Management's Discussion and Analysis"

        # Item 8 Financial Statements
        detected = tracker.update("ITEM 8. FINANCIAL STATEMENTS AND SUPPLEMENTARY DATA")
        assert detected == "Item 8 - Financial Statements"
        assert tracker.current_section == "Item 8 - Financial Statements"

    def test_section_tracker_literature_chapters(self) -> None:
        """Verify SectionTracker detects book chapters and literature parts."""
        tracker = SectionTracker()

        detected = tracker.update("Chapter 1: Loomings")
        assert detected == "Chapter 1 - Loomings"
        assert tracker.current_section == "Chapter 1 - Loomings"

        detected = tracker.update("Chapter 2. The Carpet-Bag")
        assert detected == "Chapter 2 - The Carpet-Bag"
        assert tracker.current_section == "Chapter 2 - The Carpet-Bag"

    def test_parse_html_table_preservation(self, tmp_path: Path) -> None:
        """Verify HTML document parsing preserves HTML table markup and tags is_table=True."""
        html_content = """
        <!DOCTYPE html>
        <html>
        <head><title>Q4 Consolidated Statement</title></head>
        <body>
            <h1>Item 8. Financial Statements</h1>
            <p>Below is the condensed balance sheet for fiscal year 2024.</p>
            <table border="1">
                <thead>
                    <tr><th>Metric</th><th>2024 ($M)</th><th>2023 ($M)</th></tr>
                </thead>
                <tbody>
                    <tr><td>Total Revenue</td><td>60,922</td><td>26,974</td></tr>
                    <tr><td>Operating Income</td><td>32,972</td><td>4,224</td></tr>
                    <tr><td>Net Income</td><td>29,760</td><td>4,368</td></tr>
                </tbody>
            </table>
            <p>Subsequent notes form an integral part of these consolidated financial statements.</p>
        </body>
        </html>
        """
        file_path = tmp_path / "financial_stmt.htm"
        file_path.write_text(html_content, encoding="utf-8")

        parser = DocumentParser()
        chunks = parser.parse(file_path)

        assert len(chunks) >= 3

        # Find the tabular chunk
        table_chunks = [c for c in chunks if c.is_table]
        assert len(table_chunks) >= 1

        table_chunk = table_chunks[0]
        assert table_chunk.is_table is True
        assert "<table" in table_chunk.text.lower()
        assert "60,922" in table_chunk.text
        assert "Total Revenue" in table_chunk.text
        assert "table_html" in table_chunk.metadata
        assert "<table" in table_chunk.metadata["table_html"].lower()

        # Section tracking should have cascaded Item 8 to the table
        assert "Item 8" in table_chunk.section

        # Narrative chunk should have is_table = False
        text_chunks = [c for c in chunks if not c.is_table]
        assert any("condensed balance sheet" in c.text for c in text_chunks)
        assert all(c.is_table is False for c in text_chunks)

    def test_companion_meta_sidecar_propagation(self, tmp_path: Path) -> None:
        """Verify companion .meta.json attributes are propagated to all emitted Chunks."""
        html_content = "<html><body><h1>Item 1A. Risk Factors</h1><p>Supply chain disruption risks.</p></body></html>"
        doc_file = tmp_path / "NVDA_10-K_20240221.htm"
        doc_file.write_text(html_content, encoding="utf-8")

        meta_data = {
            "doc_id": "0001045810-24-000029",
            "source_filename": "NVDA_10-K_20240221.htm",
            "domain": "finance",
            "form_type": "10-K",
            "filing_date": "2024-02-21",
            "company_name": "NVIDIA CORP",
            "ticker": "NVDA",
        }
        meta_file = tmp_path / "NVDA_10-K_20240221.htm.meta.json"
        meta_file.write_text(json.dumps(meta_data), encoding="utf-8")

        parser = DocumentParser()
        chunks = parser.parse(doc_file)

        assert len(chunks) > 0
        for chunk in chunks:
            assert chunk.doc_id == "0001045810-24-000029"
            assert chunk.domain == DomainType.FINANCE or chunk.domain == "finance"
            assert chunk.form_type == FormType.SEC_10K or chunk.form_type == "10-K"
            assert chunk.filing_date == date(2024, 2, 21)
            assert chunk.source_filename == "NVDA_10-K_20240221.htm"
            assert "Item 1A" in chunk.section

    def test_parse_plain_text_and_json(self, tmp_path: Path) -> None:
        """Verify parser handles raw text files and JSON payloads."""
        # Test .txt
        txt_file = tmp_path / "sample_book.txt"
        txt_file.write_text(
            "Chapter 1: Loomings\nCall me Ishmael. Some years ago—never mind how long precisely.",
            encoding="utf-8",
        )

        parser = DocumentParser()
        txt_chunks = parser.parse(txt_file)
        assert len(txt_chunks) > 0
        assert any("Ishmael" in c.text for c in txt_chunks)
        assert any("Chapter 1" in c.section for c in txt_chunks)

        # Test .json
        json_file = tmp_path / "market_brief.json"
        json_file.write_text(
            json.dumps({"title": "Morning Market Pulse", "content": "Global equity markets rallied."}),
            encoding="utf-8",
        )
        json_chunks = parser.parse(json_file)
        assert len(json_chunks) > 0
        assert any("equity markets" in c.text for c in json_chunks)

    def test_parse_unreadable_or_corrupt_file_raises_parsing_error(self, tmp_path: Path) -> None:
        """Verify corrupt or non-existent files raise DocumentParsingError."""
        parser = DocumentParser()
        with pytest.raises(DocumentParsingError):
            parser.parse(tmp_path / "non_existent_file.htm")

        empty_file = tmp_path / "empty.htm"
        empty_file.write_text("", encoding="utf-8")
        with pytest.raises(DocumentParsingError):
            parser.parse(empty_file)

    def test_document_processor_protocol_compliance(self, tmp_path: Path) -> None:
        """Verify DocumentParser satisfies DocumentProcessorProtocol."""
        parser = DocumentParser()
        assert isinstance(parser, DocumentProcessorProtocol)

        test_file = tmp_path / "doc.htm"
        test_file.write_text("<html><body><p>Hello world content</p></body></html>", encoding="utf-8")

        result = parser.process(test_file)
        assert result.success is True
        assert result.status == IngestionStatus.COMPLETED
        assert result.chunk_count > 0
        assert result.token_total > 0
        assert result.duration_seconds >= 0.0

    def test_lifecycle_manager_integration_with_parser(self, tmp_path: Path) -> None:
        """Verify LifecycleManager processes files with DocumentParser, advancing to processed directory."""
        processed_dir = tmp_path / "processed"
        failed_dir = tmp_path / "failed"

        parser = DocumentParser()
        manager = LifecycleManager(
            processed_dir=processed_dir,
            failed_dir=failed_dir,
            processor=parser,
        )

        test_file = tmp_path / "valid_filing.htm"
        test_file.write_text(
            "<html><body><h1>Item 1A. Risk Factors</h1><p>Risk narrative paragraph.</p></body></html>",
            encoding="utf-8",
        )

        summary = manager.handle_file(test_file)
        assert summary.status == IngestionStatus.COMPLETED
        assert summary.chunk_count > 0
        assert summary.token_total > 0
        assert not test_file.exists()
        assert (processed_dir / "valid_filing.htm").exists()

