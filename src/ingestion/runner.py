"""Ingestion Daemon Runner process for continuous document ingestion and lifecycle management.

Follows TREM-Python principles:
- Testable: Injected heartbeat path, storage backend, and polling interval.
- Readable: Clear lifecycle states, signal handlers, and structured logging.
- Extensible: Hooks ready for Phase 3 drop-directory watcher (watchdog) and SEC Edgar fetcher.
- Maintainable: Graceful shutdown on SIGTERM/SIGINT with dead-man heartbeat file updates.
"""

from __future__ import annotations

import logging
import os
import signal
import sys
import time
from pathlib import Path
from types import FrameType
from typing import Any

from src.common.config import Settings, get_settings
from src.common.storage import StorageBackendProtocol, get_storage_backend

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


class IngestionRunner:
    """Continuous ingestion background daemon."""

    def __init__(
        self,
        settings: Settings | None = None,
        storage_backend: StorageBackendProtocol | None = None,
        heartbeat_file: str = "/tmp/healthy",
        poll_interval_seconds: float = 5.0,
    ) -> None:
        self.settings = settings or get_settings()
        self.storage_backend = storage_backend or get_storage_backend(self.settings)
        self.heartbeat_file = Path(heartbeat_file)
        self.poll_interval_seconds = poll_interval_seconds
        self._stopped = False
        self._initialized = False

    @property
    def is_stopped(self) -> bool:
        """Indicates whether runner has received termination request."""
        return self._stopped

    def request_stop(self) -> None:
        """Signal runner to terminate main loop."""
        logger.info("Ingestion runner shutdown requested.")
        self._stopped = True

    def _signal_handler(self, signum: int, frame: FrameType | None) -> None:
        """Signal handler for OS process termination (SIGTERM, SIGINT)."""
        logger.info("Received signal %d, initiating graceful stop...", signum)
        self.request_stop()

    def _update_heartbeat(self) -> None:
        """Touch the healthcheck heartbeat probe file."""
        try:
            self.heartbeat_file.parent.mkdir(parents=True, exist_ok=True)
            self.heartbeat_file.touch()
        except Exception as exc:
            logger.warning("Failed to touch heartbeat file at %s: %s", self.heartbeat_file, exc)

    def _initialize_storage(self) -> None:
        """Initialize the active storage backend on startup."""
        if not self._initialized:
            logger.info("Initializing lakehouse storage backend...")
            try:
                self.storage_backend.initialize()
            except Exception as exc:
                logger.error("Error during storage backend initialization: %s", exc)
            self._initialized = True

    def run_cycle(self) -> None:
        """Single tick execution: initialize storage, ensure incoming dirs exist, update heartbeat."""
        self._initialize_storage()
        self._update_heartbeat()

        # In Phase 2: verify directory mounts exist
        incoming_path = Path(self.settings.paths.incoming_path)
        if not incoming_path.exists():
            incoming_path.mkdir(parents=True, exist_ok=True)

        # Drop-directory watcher logic activates in Phase 3

    def run(self) -> None:
        """Main daemon loop running until request_stop() or OS signal."""
        logger.info("Starting Ingestion Daemon Runner...")
        # Register signals if in main thread
        try:
            signal.signal(signal.SIGTERM, self._signal_handler)
            signal.signal(signal.SIGINT, self._signal_handler)
        except (ValueError, AttributeError):
            pass

        while not self._stopped:
            self.run_cycle()
            time.sleep(self.poll_interval_seconds)

        logger.info("Ingestion Daemon Runner stopped cleanly.")


def main() -> None:
    """Entrypoint for ingestion-runner container."""
    runner = IngestionRunner()
    runner.run()


if __name__ == "__main__":
    main()

