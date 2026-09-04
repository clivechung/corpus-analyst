"""Continuous drop-directory watcher monitoring /data/incoming with complete write detection.

Follows TREM-Python principles:
- Testable: Injected lifecycle manager, configurable intervals, and independent scan methods.
- Readable: Clear state checks for complete writes, temporary file exclusions, and deduplication.
- Extensible: Configurable observer backends and supported file extensions.
- Maintainable: Graceful observer lifecycle management and non-blocking background thread teardown.
"""

from __future__ import annotations

import logging
import os
import time
from pathlib import Path
from typing import Any

from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer

from src.common.config import WatcherSettings
from src.ingestion.lifecycle import LifecycleManager

logger = logging.getLogger(__name__)


class CompleteWriteDetector:
    """Detects whether incoming files have completed filesystem writes."""

    IGNORED_SUFFIXES: set[str] = {".tmp", ".crdownload", ".part", ".lock", ".temp"}

    def __init__(
        self,
        write_detection_interval_seconds: float = 1.0,
        stability_checks: int = 2,
    ) -> None:
        self.interval_seconds = write_detection_interval_seconds
        self.stability_checks = stability_checks
        self._tracked: dict[Path, dict[str, Any]] = {}

    def is_write_complete(self, path: Path) -> bool:
        """Evaluate if the file write is complete and file is stable."""
        # 1. Reject hidden files or known incomplete download extensions
        if path.name.startswith("."):
            return False
        if any(path.name.lower().endswith(suffix) for suffix in self.IGNORED_SUFFIXES):
            return False

        if not path.is_file():
            self._tracked.pop(path, None)
            return False

        try:
            stat_info = path.stat()
            current_size = stat_info.st_size
            current_mtime = stat_info.st_mtime
        except OSError:
            return False

        # 2. Reject empty (0-byte) files
        if current_size == 0:
            return False

        # 3. Test non-blocking read access
        try:
            with open(path, "rb") as f:
                _ = f.read(min(current_size, 1024))
        except OSError:
            return False

        # 4. Evaluate size and modification stability over time window
        now = time.monotonic()
        record = self._tracked.get(path)

        if record is None:
            # First observation: begin stability tracking
            self._tracked[path] = {
                "size": current_size,
                "mtime": current_mtime,
                "last_check": now,
                "stability_count": 0,
            }
            return False

        if (now - record["last_check"]) < self.interval_seconds:
            # Insufficient time elapsed since previous sample
            return False

        # Check if size and mtime remained unchanged
        if current_size == record["size"] and current_mtime == record["mtime"]:
            record["stability_count"] += 1
            record["last_check"] = now
            if record["stability_count"] >= self.stability_checks:
                # Target stability threshold reached
                self._tracked.pop(path, None)
                logger.info("Complete write verified for file: %s (%d bytes)", path.name, current_size)
                return True
            return False
        else:
            # File grew or was modified; reset stability counter
            record["size"] = current_size
            record["mtime"] = current_mtime
            record["last_check"] = now
            record["stability_count"] = 0
            return False


class DropDirHandler(FileSystemEventHandler):
    """Watches directory events and enqueues newly detected files."""

    def __init__(self, watcher: IncomingWatcher) -> None:
        super().__init__()
        self.watcher = watcher

    def on_created(self, event: FileSystemEvent) -> None:
        if not event.is_directory:
            self.watcher.enqueue_candidate(Path(event.src_path))

    def on_modified(self, event: FileSystemEvent) -> None:
        if not event.is_directory:
            self.watcher.enqueue_candidate(Path(event.src_path))


class IncomingWatcher:
    """Continuous filesystem watcher monitoring incoming directory with complete write detection."""

    def __init__(
        self,
        incoming_path: str | Path,
        lifecycle_manager: LifecycleManager,
        settings: WatcherSettings | None = None,
        observer_cls: type[Observer] | None = None,
    ) -> None:
        self.incoming_path = Path(incoming_path)
        self.lifecycle_manager = lifecycle_manager
        self.settings = settings or WatcherSettings()
        self.observer_cls = observer_cls or Observer

        self.write_detector = CompleteWriteDetector(
            write_detection_interval_seconds=self.settings.write_detection_interval_seconds,
            stability_checks=self.settings.stability_checks,
        )

        self._active_files: set[Path] = set()
        self._pending_files: set[Path] = set()
        self._observer: Observer | None = None
        self._running = False

    @property
    def is_running(self) -> bool:
        """Whether the background observer thread is active."""
        return self._running

    def enqueue_candidate(self, path: Path) -> None:
        """Enqueue a detected candidate file path."""
        if path.name.lower().endswith(".meta.json"):
            # Skip sidecars from direct processing (paired with documents)
            return

        ext = path.suffix.lower()
        if ext in self.settings.supported_extensions:
            self._pending_files.add(path)

    def start(self) -> None:
        """Start the watchdog filesystem observer thread."""
        if self._running:
            return

        self.incoming_path.mkdir(parents=True, exist_ok=True)
        self._observer = self.observer_cls()
        handler = DropDirHandler(self)
        self._observer.schedule(handler, str(self.incoming_path), recursive=False)
        self._observer.start()
        self._running = True
        logger.info("IncomingWatcher started monitoring: %s", self.incoming_path)

    def stop(self) -> None:
        """Gracefully stop and join the filesystem observer."""
        if not self._running:
            return

        logger.info("Stopping IncomingWatcher...")
        if self._observer:
            self._observer.stop()
            self._observer.join(timeout=2.0)
            self._observer = None
        self._running = False
        logger.info("IncomingWatcher stopped.")

    def scan_incoming(self) -> None:
        """Periodic scan sweep of the incoming directory to catch missed or pre-existing files."""
        if not self.incoming_path.exists():
            return

        for entry in self.incoming_path.iterdir():
            if not entry.is_file():
                continue
            if entry.name.lower().endswith(".meta.json"):
                continue
            if entry.suffix.lower() in self.settings.supported_extensions:
                self._pending_files.add(entry)

        self.process_pending()

    def process_pending(self) -> None:
        """Evaluate complete write detection for all pending files and dispatch stable files."""
        candidates = list(self._pending_files)

        for candidate in candidates:
            if candidate in self._active_files:
                continue

            if not candidate.exists():
                self._pending_files.discard(candidate)
                continue

            if self.write_detector.is_write_complete(candidate):
                self._pending_files.discard(candidate)
                self._active_files.add(candidate)
                try:
                    logger.info("Dispatching %s to processing lifecycle...", candidate.name)
                    self.lifecycle_manager.handle_file(candidate)
                except Exception as exc:
                    logger.error("Unhandled error dispatching %s: %s", candidate.name, exc)
                finally:
                    self._active_files.discard(candidate)

