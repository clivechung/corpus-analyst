"""Unit tests for UI Ingestion Service seam (SEAM-UI-INGESTION).

Follows TREM-Python principles:
- Testable: Injected temporary directories, mock HTTP/fetcher components, zero live Streamlit runtime required.
- Readable: Clear assertions on queue scanning, status classification, metadata sidecar linkage, dead-letter parsing, and metrics.
- Extensible: Clean QueueItem and QueueMetrics contracts.
- Maintainable: Robust file lifecycle transition tests.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from io import BytesIO
from pathlib import Path
from unittest import mock

from ui.components.ingestion_service import (
    IngestionService,
    QueueItem,
    QueueMetrics,
)


class TestUiIngestionSeam(unittest.TestCase):
    """Test suite verifying UI Ingestion Service logic."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.base_path = Path(self.temp_dir.name)
        self.incoming_dir = self.base_path / "incoming"
        self.processed_dir = self.base_path / "processed"
        self.failed_dir = self.base_path / "failed"

        self.incoming_dir.mkdir(parents=True)
        self.processed_dir.mkdir(parents=True)
        self.failed_dir.mkdir(parents=True)

        self.service = IngestionService(
            incoming_dir=self.incoming_dir,
            processed_dir=self.processed_dir,
            failed_dir=self.failed_dir,
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_scan_queue_empty_directories(self) -> None:
        """Verify empty directories yield zero queue items and zeroed metrics."""
        items = self.service.scan_queue()
        metrics = self.service.get_metrics()

        self.assertEqual(items, [])
        self.assertEqual(metrics.incoming_count, 0)
        self.assertEqual(metrics.processed_count, 0)
        self.assertEqual(metrics.failed_count, 0)
        self.assertEqual(metrics.total_processed_bytes, 0)
        self.assertEqual(metrics.failure_rate_pct, 0.0)

    def test_scan_queue_classifies_statuses_and_ignores_sidecars(self) -> None:
        """Verify files in incoming/processed/failed are correctly classified and sidecars are ignored."""
        # 1. Incoming file
        incoming_file = self.incoming_dir / "report.pdf"
        incoming_file.write_bytes(b"PDF content incoming")

        # 2. Processed file with companion sidecar
        processed_file = self.processed_dir / "NVDA_10-K_20240221.htm"
        processed_file.write_bytes(b"Processed HTML content")
        sidecar_file = self.processed_dir / "NVDA_10-K_20240221.htm.meta.json"
        sidecar_file.write_text(
            json.dumps({
                "ticker": "NVDA",
                "form_type": "10-K",
                "company_name": "NVIDIA CORP",
                "filing_date": "2024-02-21",
                "domain": "finance",
            })
        )

        # 3. Failed file with dead-letter .error.json
        failed_file = self.failed_dir / "bad_data.json"
        failed_file.write_bytes(b"Corrupt JSON {")
        error_file = self.failed_dir / "bad_data.json.error.json"
        error_file.write_text(
            json.dumps({
                "error_type": "JSONDecodeError",
                "error_message": "Unterminated string starting at line 1",
                "source_filename": "bad_data.json",
                "stack_trace": "Traceback (most recent call last)...",
            })
        )

        items = self.service.scan_queue()
        self.assertEqual(len(items), 3)

        item_map = {item.filename: item for item in items}
        self.assertIn("report.pdf", item_map)
        self.assertIn("NVDA_10-K_20240221.htm", item_map)
        self.assertIn("bad_data.json", item_map)

        # Status assertions
        self.assertEqual(item_map["report.pdf"].status, "PENDING")
        self.assertEqual(item_map["NVDA_10-K_20240221.htm"].status, "PROCESSED")
        self.assertEqual(item_map["bad_data.json"].status, "FAILED")

        # Metadata sidecar resolution
        nvda_item = item_map["NVDA_10-K_20240221.htm"]
        self.assertEqual(nvda_item.ticker, "NVDA")
        self.assertEqual(nvda_item.form_type, "10-K")
        self.assertEqual(nvda_item.company_name, "NVIDIA CORP")
        self.assertTrue(nvda_item.has_metadata)

        # Error JSON resolution
        failed_item = item_map["bad_data.json"]
        self.assertEqual(failed_item.error_type, "JSONDecodeError")
        self.assertIn("Unterminated string", failed_item.error_message or "")

        # Verify get_metadata_details with and without status parameter
        meta_with_status = self.service.get_metadata_details("NVDA_10-K_20240221.htm", status="PROCESSED")
        self.assertIsNotNone(meta_with_status)
        self.assertEqual(meta_with_status.get("ticker"), "NVDA")

        meta_without_status = self.service.get_metadata_details("NVDA_10-K_20240221.htm")
        self.assertIsNotNone(meta_without_status)
        self.assertEqual(meta_without_status.get("form_type"), "10-K")

        # Verify get_dead_letter_details
        dead_letter = self.service.get_dead_letter_details("bad_data.json")
        self.assertIsNotNone(dead_letter)
        self.assertEqual(dead_letter.get("error_type"), "JSONDecodeError")

    def test_get_metrics_calculation(self) -> None:
        """Verify queue metrics calculation including volume and failure rate."""
        # 1 incoming (100 bytes)
        (self.incoming_dir / "doc1.pdf").write_bytes(b"a" * 100)

        # 3 processed (200, 300, 500 bytes = 1000 bytes)
        (self.processed_dir / "proc1.htm").write_bytes(b"b" * 200)
        (self.processed_dir / "proc2.htm").write_bytes(b"c" * 300)
        (self.processed_dir / "proc3.htm").write_bytes(b"d" * 500)

        # 1 failed
        (self.failed_dir / "fail1.json").write_bytes(b"e" * 50)
        (self.failed_dir / "fail1.json.error.json").write_text("{}")

        metrics = self.service.get_metrics()
        self.assertEqual(metrics.incoming_count, 1)
        self.assertEqual(metrics.processed_count, 3)
        self.assertEqual(metrics.failed_count, 1)
        self.assertEqual(metrics.total_processed_bytes, 1000)
        # Failure rate: 1 failed out of 4 resolved (3 processed + 1 failed) = 25.0%
        self.assertAlmostEqual(metrics.failure_rate_pct, 25.0, places=1)

    def test_save_uploaded_file_and_meta_sidecar(self) -> None:
        """Verify saving uploaded file writes binary content and companion .meta.json."""
        file_buffer = BytesIO(b"Financial Quantitative Report content")
        file_name = "quant_alpha_2024.pdf"

        saved_path = self.service.save_uploaded_file(
            file_name=file_name,
            file_bytes=file_buffer.getvalue(),
            ticker="AAPL",
            form_type="RESEARCH",
            domain="finance",
        )

        self.assertTrue(saved_path.is_file())
        self.assertEqual(saved_path.read_bytes(), b"Financial Quantitative Report content")

        sidecar_path = saved_path.with_name(f"{saved_path.name}.meta.json")
        self.assertTrue(sidecar_path.is_file())

        with open(sidecar_path, "r", encoding="utf-8") as f:
            meta = json.load(f)

        self.assertEqual(meta["ticker"], "AAPL")
        self.assertEqual(meta["form_type"], "RESEARCH")
        self.assertEqual(meta["domain"], "finance")
        self.assertEqual(meta["source_filename"], file_name)

    def test_requeue_failed_file(self) -> None:
        """Verify re-queuing a failed file moves it to incoming and cleans up error log."""
        failed_doc = self.failed_dir / "malformed.txt"
        failed_doc.write_bytes(b"Retryable content")
        error_doc = self.failed_dir / "malformed.txt.error.json"
        error_doc.write_text(json.dumps({"error_type": "TransientError"}))

        success = self.service.requeue_failed_file("malformed.txt")
        self.assertTrue(success)

        # Confirm moved to incoming
        self.assertTrue((self.incoming_dir / "malformed.txt").is_file())
        self.assertFalse(failed_doc.exists())
        self.assertFalse(error_doc.exists())

    def test_execute_sec_fetch_wrapper(self) -> None:
        """Verify execute_sec_fetch instantiates SecFetcher and downloads filing."""
        mock_fetcher = mock.MagicMock()
        mock_fetcher.download_filing.return_value = self.incoming_dir / "NVDA_10-K_20240221.htm"

        mock_fetcher_cls = mock.MagicMock(return_value=mock_fetcher)
        service = IngestionService(
            incoming_dir=self.incoming_dir,
            processed_dir=self.processed_dir,
            failed_dir=self.failed_dir,
            sec_fetcher_cls=mock_fetcher_cls,
        )

        result = service.execute_sec_fetch(
            ticker="NVDA",
            form_type="10-K",
            start_date="2024-01-01",
            end_date="2024-03-31",
            user_agent="CorpusAnalyst test@corpus-analyst.local",
        )

        self.assertTrue(result["success"])
        self.assertEqual(result["ticker"], "NVDA")
        mock_fetcher_cls.assert_called_once_with(
            output_dir=self.incoming_dir,
            user_agent="CorpusAnalyst test@corpus-analyst.local",
        )
        mock_fetcher.download_filing.assert_called_once_with(
            ticker="NVDA",
            form_type="10-K",
            start_date="2024-01-01",
            end_date="2024-03-31",
        )


if __name__ == "__main__":
    unittest.main()
