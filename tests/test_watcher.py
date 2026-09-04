"""Unit tests for continuous directory watcher seam (SEAM-WATCHER).

Follows TREM-Python principles:
- Testable: In-memory/tempdir testing for watchdog events, complete write detection, and polling sweeps.
- Readable: Clear behavioral assertions for file stability, temporary file filtering, and deduplication.
- Extensible: Mockable lifecycle manager and configurable stability parameters.
- Maintainable: Verification of graceful observer start/stop lifecycle.
"""

from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from src.common.config import WatcherSettings
from src.common.models import IngestionStatus, IngestionSummary
from src.ingestion.watcher import CompleteWriteDetector, IncomingWatcher


class TestWatcherSeam(unittest.TestCase):
    """Test suite for CompleteWriteDetector and IncomingWatcher."""

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

    def test_complete_write_detector_ignores_temp_and_hidden_files(self) -> None:
        """Verify temporary and hidden files are rejected by the write detector."""
        detector = CompleteWriteDetector(
            write_detection_interval_seconds=0.01,
            stability_checks=1,
        )

        tmp_file = self.incoming_dir / "filing.tmp"
        tmp_file.write_text("partial data")
        self.assertFalse(detector.is_write_complete(tmp_file))

        crdownload_file = self.incoming_dir / "filing.crdownload"
        crdownload_file.write_text("partial data")
        self.assertFalse(detector.is_write_complete(crdownload_file))

        hidden_file = self.incoming_dir / ".DS_Store"
        hidden_file.write_text("hidden")
        self.assertFalse(detector.is_write_complete(hidden_file))

    def test_complete_write_detector_rejects_empty_file(self) -> None:
        """Verify empty (0-byte) files are not treated as write-complete."""
        detector = CompleteWriteDetector(
            write_detection_interval_seconds=0.01,
            stability_checks=1,
        )

        empty_file = self.incoming_dir / "empty.txt"
        empty_file.touch()
        self.assertFalse(detector.is_write_complete(empty_file))

    def test_complete_write_detector_confirms_stable_file(self) -> None:
        """Verify stable file with unchanging size is detected as write-complete."""
        detector = CompleteWriteDetector(
            write_detection_interval_seconds=0.01,
            stability_checks=2,
        )

        valid_file = self.incoming_dir / "report.pdf"
        valid_file.write_text("Valid completed PDF content")

        # First check starts tracking (discovery)
        self.assertFalse(detector.is_write_complete(valid_file))
        time.sleep(0.015)
        # Second check: stability_count = 1 (< 2)
        self.assertFalse(detector.is_write_complete(valid_file))
        time.sleep(0.015)
        # Third check: stability_count = 2 (>= 2), confirms stability
        self.assertTrue(detector.is_write_complete(valid_file))

    def test_complete_write_detector_detects_growing_file_as_incomplete(self) -> None:
        """Verify growing file with changing size is not marked write-complete."""
        detector = CompleteWriteDetector(
            write_detection_interval_seconds=0.01,
            stability_checks=2,
        )

        growing_file = self.incoming_dir / "large_stream.pdf"
        growing_file.write_text("chunk 1")
        self.assertFalse(detector.is_write_complete(growing_file))

        time.sleep(0.01)
        growing_file.write_text("chunk 1 + chunk 2 (grown)")
        # Size changed, should reset stability count and return False
        self.assertFalse(detector.is_write_complete(growing_file))

    def test_incoming_watcher_scan_and_dispatch(self) -> None:
        """Verify IncomingWatcher polling sweep detects and dispatches complete files."""
        mock_lifecycle = mock.MagicMock()
        mock_lifecycle.handle_file.return_value = IngestionSummary(
            file_path="/data/processed/filing.htm",
            status=IngestionStatus.COMPLETED,
            duration_seconds=0.05,
            chunk_count=10,
            token_total=500,
        )

        settings = WatcherSettings(
            poll_interval_seconds=0.05,
            write_detection_interval_seconds=0.01,
            stability_checks=1,
        )

        watcher = IncomingWatcher(
            incoming_path=self.incoming_dir,
            lifecycle_manager=mock_lifecycle,
            settings=settings,
        )

        test_file = self.incoming_dir / "filing.htm"
        test_file.write_text("<html>Sample financial filing</html>")

        # First scan initiates tracking in write detector
        watcher.scan_incoming()
        self.assertEqual(mock_lifecycle.handle_file.call_count, 0)

        # Wait for write detection interval to pass
        time.sleep(0.02)

        # Second scan detects write complete and dispatches
        watcher.scan_incoming()
        mock_lifecycle.handle_file.assert_called_once_with(test_file)

    def test_incoming_watcher_deduplication(self) -> None:
        """Verify active in-progress files are not dispatched concurrently."""
        mock_lifecycle = mock.MagicMock()

        settings = WatcherSettings(
            poll_interval_seconds=0.05,
            write_detection_interval_seconds=0.01,
            stability_checks=1,
        )

        watcher = IncomingWatcher(
            incoming_path=self.incoming_dir,
            lifecycle_manager=mock_lifecycle,
            settings=settings,
        )

        test_file = self.incoming_dir / "in_progress.txt"
        test_file.write_text("Content")

        # Mark file as already active
        watcher._active_files.add(test_file)

        time.sleep(0.02)
        watcher.scan_incoming()

        # Should NOT dispatch because it's in active_files
        mock_lifecycle.handle_file.assert_not_called()

    def test_incoming_watcher_start_and_stop_lifecycle(self) -> None:
        """Verify watcher start and stop methods manage background observer cleanly."""
        mock_lifecycle = mock.MagicMock()
        settings = WatcherSettings(poll_interval_seconds=0.05)

        watcher = IncomingWatcher(
            incoming_path=self.incoming_dir,
            lifecycle_manager=mock_lifecycle,
            settings=settings,
        )

        self.assertFalse(watcher.is_running)
        watcher.start()
        self.assertTrue(watcher.is_running)
        watcher.stop()
        self.assertFalse(watcher.is_running)


if __name__ == "__main__":
    unittest.main()
