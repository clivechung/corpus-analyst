"""Unit tests for Phase 6 UI Presentation Components (SEAM-UI-COMPONENTS).

Follows TREM principles:
- Testable: Pure presentation helpers tested with deterministic inputs and mock HTTP dispatches.
- Readable: Clear assertions on HTML badge attributes, color boundaries, and partition trees.
- Maintainable: Verification of UI data contracts and filesystem partition scanners.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from ui.components.chat import (
    execute_chat_query,
    format_similarity_badge,
    format_table_badge,
)
from ui.components.lake_explorer import format_bytes, scan_hive_partitions


class TestUIChatAndLakeComponents:
    """Test suite verifying UI presentation logic and filesystem partition parsing."""

    def test_format_similarity_badge_color_bands(self) -> None:
        """Verify similarity badge assigns emerald for >=0.80, amber for >=0.60, and slate otherwise."""
        # High confidence >= 0.80
        high_badge = format_similarity_badge(0.8850)
        assert "#10b981" in high_badge
        assert "88.5%" in high_badge
        assert "0.8850" in high_badge

        # Moderate confidence 0.60 - 0.79
        med_badge = format_similarity_badge(0.6520)
        assert "#f59e0b" in med_badge
        assert "65.2%" in med_badge

        # Low confidence < 0.60
        low_badge = format_similarity_badge(0.4120)
        assert "#94a3b8" in low_badge
        assert "41.2%" in low_badge

    def test_format_table_badge(self) -> None:
        """Verify tabular flag assigns distinct badges for tabular data vs prose text."""
        table_badge = format_table_badge(True)
        assert "TABULAR DATA" in table_badge
        assert "#06b6d4" in table_badge

        prose_badge = format_table_badge(False)
        assert "PROSE TEXT" in prose_badge

    def test_format_bytes_scaling(self) -> None:
        """Verify byte formatting converts accurately across magnitude scales."""
        assert format_bytes(500) == "500 B"
        assert format_bytes(2048) == "2.0 KB"
        assert format_bytes(1048576 * 3) == "3.00 MB"
        assert format_bytes(1073741824 * 2) == "2.00 GB"

    def test_scan_hive_partitions_tree_extraction(self, tmp_path: Path) -> None:
        """Verify scan_hive_partitions parses Hive directory keys into structured records."""
        lake = tmp_path / "lake"
        part_dir = lake / "domain=finance" / "year=2024" / "month=02" / "day=21"
        part_dir.mkdir(parents=True, exist_ok=True)
        sample_file = part_dir / "batch_01.parquet"
        sample_file.write_bytes(b"PARQUET_TEST_BYTES")

        records = scan_hive_partitions(lake)
        assert len(records) == 1
        rec = records[0]
        assert rec["domain"] == "finance"
        assert rec["year"] == "2024"
        assert rec["month"] == "02"
        assert rec["day"] == "21"
        assert rec["filename"] == "batch_01.parquet"
        assert rec["size_bytes"] == len(b"PARQUET_TEST_BYTES")
        assert "size_formatted" in rec

    def test_scan_hive_partitions_empty_directory(self, tmp_path: Path) -> None:
        """Verify scan_hive_partitions returns empty list for non-existent path."""
        records = scan_hive_partitions(tmp_path / "does_not_exist")
        assert records == []

    @patch("ui.components.chat.httpx.post")
    def test_execute_chat_query_success(self, mock_post: MagicMock) -> None:
        """Verify execute_chat_query dispatches POST request and returns json on 200 OK."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "answer": "Test answer",
            "citations": [],
            "retrieved_chunks": [],
        }
        mock_post.return_value = mock_response

        res = execute_chat_query("http://localhost:8000", {"question": "Test", "domain": "finance"})
        assert res["answer"] == "Test answer"
        assert not res.get("error")

    @patch("ui.components.chat.httpx.post")
    def test_execute_chat_query_network_failure(self, mock_post: MagicMock) -> None:
        """Verify execute_chat_query handles network exceptions gracefully."""
        mock_post.side_effect = Exception("Connection refused")

        res = execute_chat_query("http://localhost:8000", {"question": "Test"})
        assert res.get("error") is True
        assert "Connection refused" in res.get("message", "")

    def test_get_lakehouse_query_templates_contains_top_10_vector_search(self) -> None:
        """Verify get_lakehouse_query_templates returns Top 10 Vector Search query using array_cosine_similarity."""
        from ui.components.lake_explorer import get_lakehouse_query_templates

        templates = get_lakehouse_query_templates("/data/lake/**/*.parquet")
        assert "Top 10 Vector Search (Cosine Similarity)" in templates
        vs_query = templates["Top 10 Vector Search (Cosine Similarity)"]
        assert "array_cosine_similarity" in vs_query
        assert "embedding::FLOAT[384]" in vs_query
        assert "LIMIT 10" in vs_query
        assert "read_parquet('/data/lake/**/*.parquet', hive_partitioning=true)" in vs_query

    @patch("ui.components.lake_explorer.httpx.post")
    def test_execute_vector_search_api_success(self, mock_post: MagicMock) -> None:
        """Verify execute_vector_search_api calls /api/v1/search and returns parsed chunk candidates."""
        from ui.components.lake_explorer import execute_vector_search_api

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = [
            {
                "chunk_id": "c-1",
                "similarity_score": 0.895,
                "source_filename": "NVDA_10-K.htm",
                "section": "Item 7",
                "is_table": False,
                "text": "Datacenter revenue reached record highs.",
            }
        ]
        mock_post.return_value = mock_resp

        results = execute_vector_search_api("http://localhost:8000", "datacenter revenue", top_k=10)
        assert len(results) == 1
        assert results[0]["similarity_score"] == 0.895
        assert results[0]["source_filename"] == "NVDA_10-K.htm"
        mock_post.assert_called_once_with(
            "http://localhost:8000/api/v1/search",
            json={"question": "datacenter revenue", "top_k": 10, "domain": "finance"},
            timeout=30.0,
        )

    @patch("ui.components.lake_explorer.httpx.post")
    def test_execute_vector_search_api_failure(self, mock_post: MagicMock) -> None:
        """Verify execute_vector_search_api raises RuntimeError on HTTP error code."""
        from ui.components.lake_explorer import execute_vector_search_api

        mock_resp = MagicMock()
        mock_resp.status_code = 500
        mock_resp.text = "Internal Server Error"
        mock_post.return_value = mock_resp

        with pytest.raises(RuntimeError, match="Search failed"):
            execute_vector_search_api("http://localhost:8000", "datacenter revenue", top_k=10)

    @patch("ui.components.lake_explorer.httpx.post")
    def test_generate_vector_search_sql_success(self, mock_post: MagicMock) -> None:
        """Verify generate_vector_search_sql fetches embedding and constructs valid DuckDB query."""
        from ui.components.lake_explorer import generate_vector_search_sql

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "text": "google revenue in 2026",
            "dimension": 384,
            "embedding": [0.0123] * 384,
        }
        mock_post.return_value = mock_resp

        sql = generate_vector_search_sql("http://localhost:8000", "google revenue in 2026", top_k=10)
        assert "array_cosine_similarity(embedding::FLOAT[384]" in sql
        assert "LIMIT 10" in sql
        assert "google revenue in 2026" in sql
        mock_post.assert_called_once_with(
            "http://localhost:8000/api/v1/embed",
            json={"text": "google revenue in 2026", "domain": "finance"},
            timeout=30.0,
        )
