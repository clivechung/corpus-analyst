"""Unit tests for Ingestion Daemon Runner seam (SEAM-RUNNER).

Follows TREM principles:
- Testable: Injectable stop event, heartbeat path, and blob storage client.
- Readable: Direct assertions on lifecycle methods and file touches.
- Maintainable: Verification of graceful signal handling and clean termination.
"""

import os
import signal
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from src.ingestion.runner import IngestionRunner


class TestIngestionRunnerSeam(unittest.TestCase):
    """Test suite for Ingestion Runner lifecycle, heartbeat, and signal handling."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.heartbeat_path = self.root / "healthy"
        self.settings_patcher = mock.patch("src.ingestion.runner.get_settings")
        self.mock_get_settings = self.settings_patcher.start()
        from src.common.config import Settings
        s = Settings()
        s.paths.incoming_path = str(self.root / "incoming")
        s.paths.processed_path = str(self.root / "processed")
        s.paths.failed_path = str(self.root / "failed")
        s.paths.lake_path = str(self.root / "lake")
        self.mock_get_settings.return_value = s

    def tearDown(self) -> None:
        self.settings_patcher.stop()
        self.temp_dir.cleanup()

    def test_runner_initialization_and_single_cycle(self) -> None:
        """Verify runner creates heartbeat file and initializes storage on cycle."""
        mock_storage = mock.MagicMock()

        runner = IngestionRunner(
            heartbeat_file=str(self.heartbeat_path),
            storage_backend=mock_storage,
            poll_interval_seconds=0.05,
        )

        # Execute single tick
        runner.run_cycle()

        self.assertTrue(self.heartbeat_path.exists())
        mock_storage.initialize.assert_called_once()

    def test_runner_start_and_graceful_stop(self) -> None:
        """Verify runner loops and terminates cleanly when stop() is requested."""
        runner = IngestionRunner(
            heartbeat_file=str(self.heartbeat_path),
            poll_interval_seconds=0.01,
        )

        # Set stop immediately before running to verify loop exits gracefully
        runner.request_stop()
        runner.run()

        self.assertTrue(runner.is_stopped)

    def test_signal_handler_requests_stop(self) -> None:
        """Verify SIGTERM handler flags runner for clean shutdown."""
        runner = IngestionRunner(heartbeat_file=str(self.heartbeat_path))
        self.assertFalse(runner.is_stopped)

        runner._signal_handler(signal.SIGTERM, None)
        self.assertTrue(runner.is_stopped)

    def test_runner_integrates_watcher_and_lifecycle(self) -> None:
        """Verify runner initializes IncomingWatcher and drives watcher cycle."""
        mock_watcher = mock.MagicMock()
        mock_watcher.is_running = False
        mock_lifecycle = mock.MagicMock()

        runner = IngestionRunner(
            heartbeat_file=str(self.heartbeat_path),
            watcher=mock_watcher,
            lifecycle_manager=mock_lifecycle,
            poll_interval_seconds=0.01,
        )

        # First cycle should start watcher and scan incoming
        runner.run_cycle()
        mock_watcher.start.assert_called_once()
        mock_watcher.scan_incoming.assert_called_once()

        # Stop should stop watcher
        runner.request_stop()
        mock_watcher.stop.assert_called_once()


if __name__ == "__main__":
    unittest.main()

