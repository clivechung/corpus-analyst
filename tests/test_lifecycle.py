"""Unit tests for document processing lifecycle management seam (SEAM-LIFECYCLE).

Follows TREM-Python principles:
- Testable: In-memory/tempdir testing for atomic moves, collision naming, and dead-letter trace logging.
- Readable: Explicit assertions matching lifecycle state transitions and JSON error envelopes.
- Extensible: DocumentProcessorProtocol verification allowing pluggable processors.
- Maintainable: Verification of error handling and complete trace logging.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from src.common.models import DocumentMetadata, IngestionStatus
from src.ingestion.lifecycle import (
    DefaultDocumentProcessor,
    DocumentProcessorProtocol,
    IngestionResult,
    LifecycleManager,
)


class DummyFailingProcessor:
    """Mock processor simulating a processing failure (e.g. corrupt file)."""

    def process(self, file_path: Path, metadata: DocumentMetadata | None = None) -> IngestionResult:
        raise ValueError("Corrupt file content or unparseable tokens")


class DummyLakehouseProcessor:
    """Mock processor simulating Phase 5 lakehouse storage output."""

    def process(self, file_path: Path, metadata: DocumentMetadata | None = None) -> IngestionResult:
        return IngestionResult(
            success=True,
            status=IngestionStatus.COMPLETED,
            chunk_count=5,
            token_total=500,
            parquet_paths=["/data/lake/domain=finance/year=2026/month=02/day=25/batch-1.parquet"],
        )


class TestLifecycleSeam(unittest.TestCase):
    """Test suite for document ingestion lifecycle and dead-letter handling."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.incoming_dir = self.root / "incoming"
        self.processed_dir = self.root / "processed"
        self.failed_dir = self.root / "failed"

        self.incoming_dir.mkdir(parents=True, exist_ok=True)
        self.processed_dir.mkdir(parents=True, exist_ok=True)
        self.failed_dir.mkdir(parents=True, exist_ok=True)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_default_processor_satisfies_protocol(self) -> None:
        """Verify DefaultDocumentProcessor implements DocumentProcessorProtocol (TREM: Extensible)."""
        processor = DefaultDocumentProcessor()
        self.assertIsInstance(processor, DocumentProcessorProtocol)

    def test_default_processor_successful_processing(self) -> None:
        """Verify DefaultDocumentProcessor processes valid file and extracts metadata."""
        sample_file = self.incoming_dir / "report.pdf"
        sample_file.write_text("%PDF-1.4 Mock valid PDF content")

        meta_file = self.incoming_dir / "report.meta.json"
        meta_file.write_text(
            json.dumps({
                "doc_id": "test-doc-123",
                "source_filename": "report.pdf",
                "ticker": "NVDA",
                "form_type": "10-K",
            })
        )

        processor = DefaultDocumentProcessor()
        result = processor.process(sample_file)

        self.assertTrue(result.success)
        self.assertEqual(result.status, IngestionStatus.COMPLETED)
        self.assertIsNotNone(result.metadata)
        self.assertEqual(result.metadata.ticker, "NVDA")
        self.assertEqual(result.metadata.form_type, "10-K")

    def test_lifecycle_manager_successful_processing_moves_to_processed(self) -> None:
        """Verify successful processing atomically relocates file and sidecar to /data/processed/."""
        sample_file = self.incoming_dir / "filing_2024.htm"
        sample_file.write_text("<html><body>Financial Statements</body></html>")

        meta_file = self.incoming_dir / "filing_2024.meta.json"
        meta_file.write_text(json.dumps({"doc_id": "filing-2024", "ticker": "AAPL"}))

        manager = LifecycleManager(
            processed_dir=self.processed_dir,
            failed_dir=self.failed_dir,
            processor=DefaultDocumentProcessor(),
        )

        summary = manager.handle_file(sample_file)

        self.assertEqual(summary.status, IngestionStatus.COMPLETED)
        self.assertFalse(sample_file.exists(), "Original incoming file should have been moved")
        self.assertFalse(meta_file.exists(), "Original incoming sidecar should have been moved")

        processed_file = self.processed_dir / "filing_2024.htm"
        processed_meta = self.processed_dir / "filing_2024.meta.json"
        self.assertTrue(processed_file.exists())
        self.assertTrue(processed_meta.exists())

    def test_lifecycle_manager_collision_handling(self) -> None:
        """Verify atomic relocation generates unique name when file already exists in processed dir."""
        existing_processed = self.processed_dir / "document.pdf"
        existing_processed.write_text("Existing previous file")

        new_incoming = self.incoming_dir / "document.pdf"
        new_incoming.write_text("New incoming file with identical name")

        manager = LifecycleManager(
            processed_dir=self.processed_dir,
            failed_dir=self.failed_dir,
            processor=DefaultDocumentProcessor(),
        )

        summary = manager.handle_file(new_incoming)

        self.assertEqual(summary.status, IngestionStatus.COMPLETED)
        self.assertTrue(existing_processed.exists(), "Original processed file must remain intact")
        self.assertEqual(existing_processed.read_text(), "Existing previous file")

        # Confirm new file was moved with collision suffix
        processed_files = list(self.processed_dir.glob("document*.pdf"))
        self.assertEqual(len(processed_files), 2)

    def test_lifecycle_manager_failure_moves_to_failed_and_logs_error_json(self) -> None:
        """Verify processing failure moves file to /data/failed/ and writes .error.json trace."""
        bad_file = self.incoming_dir / "corrupted.pdf"
        bad_file.write_text("Corrupt binary data")

        manager = LifecycleManager(
            processed_dir=self.processed_dir,
            failed_dir=self.failed_dir,
            processor=DummyFailingProcessor(),
        )

        summary = manager.handle_file(bad_file)

        self.assertEqual(summary.status, IngestionStatus.FAILED)
        self.assertFalse(bad_file.exists(), "Corrupted incoming file should have been moved")

        failed_file = self.failed_dir / "corrupted.pdf"
        error_json_file = self.failed_dir / "corrupted.pdf.error.json"

        self.assertTrue(failed_file.exists())
        self.assertTrue(error_json_file.exists())

        error_data = json.loads(error_json_file.read_text())
        self.assertEqual(error_data["source_filename"], "corrupted.pdf")
        self.assertEqual(error_data["error_type"], "ValueError")
        self.assertIn("Corrupt file content", error_data["error_message"])
        self.assertIn("Traceback", error_data["stack_trace"])
        self.assertIn("timestamp", error_data)

    def test_lifecycle_manager_propagates_parquet_paths(self) -> None:
        """Verify LifecycleManager propagates generated parquet_paths into IngestionSummary."""
        doc_file = self.incoming_dir / "valid_doc.htm"
        doc_file.write_text("Valid HTML content")

        manager = LifecycleManager(
            processed_dir=self.processed_dir,
            failed_dir=self.failed_dir,
            processor=DummyLakehouseProcessor(),
        )

        summary = manager.handle_file(doc_file)
        self.assertEqual(summary.status, IngestionStatus.COMPLETED)
        self.assertEqual(len(summary.parquet_paths), 1)
        self.assertIn("batch-1.parquet", summary.parquet_paths[0])


if __name__ == "__main__":
    unittest.main()

