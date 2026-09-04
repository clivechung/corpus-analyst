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
        self.heartbeat_path = Path(self.temp_dir.name) / "healthy"

    def tearDown(self) -> None:
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


if __name__ == "__main__":
    unittest.main()

