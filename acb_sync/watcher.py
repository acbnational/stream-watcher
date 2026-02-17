"""File system watcher for Stream Watcher.

Uses the watchdog library to monitor a source folder for new or
modified files, then queues them for stability checking and copying.
"""

from __future__ import annotations

import fnmatch
import logging
import os
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from watchdog.events import (
    FileCreatedEvent,
    FileModifiedEvent,
    FileSystemEventHandler,
)
from watchdog.observers import Observer

logger = logging.getLogger(__name__)


class _StabilityTracker:
    """Tracks files until they have been stable (unchanged) for a given duration."""

    def __init__(self, stable_seconds: int, on_stable: Callable[[Path], None]):
        self._stable_seconds = stable_seconds
        self._on_stable = on_stable
        # file_path -> (last_modified_time, last_size)
        # Use simple assignment to avoid pyright type-expression quirks
        self._pending = {}
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = threading.Thread(
            target=self._poll, daemon=True, name="StabilityTracker"
        )

    @property
    def stable_seconds(self) -> int:
        return self._stable_seconds

    @stable_seconds.setter
    def stable_seconds(self, value: int) -> None:
        self._stable_seconds = max(0, value)

    def start(self) -> None:
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._poll, daemon=True, name="StabilityTracker"
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def track(self, path: Path) -> None:
        """Register or update a file for stability tracking."""
        if not path.is_file():
            return
        try:
            stat = path.stat()
        except OSError:
            return
        with self._lock:
            self._pending[path] = (time.time(), stat.st_size)
        logger.debug("Tracking %s (size=%d)", path, stat.st_size)

    @property
    def pending_count(self) -> int:
        with self._lock:
            return len(self._pending)

    @property
    def pending_files(self) -> list[str]:
        with self._lock:
            return [str(p) for p in self._pending]

    def _poll(self) -> None:
        """Periodically check if tracked files have stabilised."""
        while not self._stop.is_set():
            stable = []  # type: list[Path]
            now = time.time()
            with self._lock:
                for path, (last_seen, last_size) in list(self._pending.items()):
                    try:
                        current_size = path.stat().st_size
                    except OSError:
                        # File vanished — drop it
                        del self._pending[path]
                        continue
                    if current_size != last_size:
                        # Still changing — update
                        self._pending[path] = (now, current_size)
                    elif now - last_seen >= self._stable_seconds:
                        stable.append(path)
                for p in stable:
                    del self._pending[p]

            for p in stable:
                logger.info("File stable: %s", p)
                try:
                    self._on_stable(p)
                except Exception:
                    logger.exception("Error in on_stable callback for %s", p)

            self._stop.wait(timeout=5)


class NewFileHandler(FileSystemEventHandler):
    """Watchdog handler that feeds new/modified files into the stability tracker."""

    def __init__(
        self,
        tracker: _StabilityTracker,
        extensions: list[str] | None = None,
        include_patterns: list[str] | None = None,
        exclude_patterns: list[str] | None = None,
    ):
        """Initialise the handler with optional filters."""
        super().__init__()
        self._tracker = tracker
        self._extensions = extensions  # None or empty = accept all
        self._include_patterns = include_patterns or []
        self._exclude_patterns = exclude_patterns or []

    def _should_track(self, path: str) -> bool:
        name = os.path.basename(path)
        # Check include patterns first — file must match at least one
        if self._include_patterns:
            matched = any(
                fnmatch.fnmatch(name.lower(), p.lower()) for p in self._include_patterns
            )
            if not matched:
                logger.debug(
                    "Ignoring %s (does not match any include pattern)",
                    name,
                )
                return False
        # Check exclude patterns (glob-style)
        for pattern in self._exclude_patterns:
            if fnmatch.fnmatch(name.lower(), pattern.lower()):
                logger.debug("Excluding %s (matches %s)", name, pattern)
                return False
        # Check allowed extensions
        if not self._extensions:
            return True
        ext = os.path.splitext(path)[1].lower().lstrip(".")
        return ext in self._extensions

    def on_created(self, event: FileCreatedEvent) -> None:  # type: ignore[override]
        """Handle a new file creation event."""
        if event.is_directory:
            return
        if self._should_track(event.src_path):
            self._tracker.track(Path(event.src_path))

    def on_modified(self, event: FileModifiedEvent) -> None:  # type: ignore[override]
        """Handle a file modification event."""
        if event.is_directory:
            return
        if self._should_track(event.src_path):
            self._tracker.track(Path(event.src_path))


class FolderWatcher:
    """High-level watcher that combines watchdog + stability tracking.

    Usage:
        watcher = FolderWatcher(source, on_ready, stable_secs=60, extensions=[])
        watcher.start()
        ...
        watcher.stop()
    """

    def __init__(
        self,
        source_folder: str,
        on_file_ready: Callable[[Path], None],
        stable_seconds: int = 60,
        extensions: list[str] | None = None,
        include_patterns: list[str] | None = None,
        exclude_patterns: list[str] | None = None,
        recursive: bool = False,
    ):
        """Create a new folder watcher."""
        self.source_folder = source_folder
        self._recursive = recursive
        self._tracker = _StabilityTracker(stable_seconds, on_file_ready)
        self._handler = NewFileHandler(
            self._tracker,
            extensions or None,
            include_patterns or None,
            exclude_patterns or None,
        )
        self._observer: Any | None = None

    # ---- lifecycle ----

    def start(self) -> None:
        """Start watching the source folder."""
        if not os.path.isdir(self.source_folder):
            logger.error("Source folder does not exist: %s", self.source_folder)
            raise FileNotFoundError(
                f"Source folder does not exist: {self.source_folder}"
            )

        observer = Observer()
        self._observer = observer
        observer.schedule(self._handler, self.source_folder, recursive=self._recursive)
        observer.start()
        self._tracker.start()
        logger.info(
            "Watching '%s' (recursive=%s, stable=%ds)",
            self.source_folder,
            self._recursive,
            self._tracker.stable_seconds,
        )

    def stop(self) -> None:
        """Stop watching and release resources."""
        if self._observer:
            self._observer.stop()
            self._observer.join(timeout=5)
            self._observer = None
        self._tracker.stop()
        logger.info("Watcher stopped.")

    @property
    def is_running(self) -> bool:
        """Return whether the watcher is currently active."""
        return self._observer is not None and self._observer.is_alive()

    # ---- config hot-update ----

    def update_stable_time(self, seconds: int) -> None:
        """Hot-update the stability threshold."""
        self._tracker.stable_seconds = seconds

    def update_extensions(self, extensions: list[str]) -> None:
        """Hot-update the allowed file extensions."""
        self._handler._extensions = extensions or None

    # ---- status ----

    @property
    def pending_count(self) -> int:
        """Return the number of files awaiting stability."""
        return self._tracker.pending_count

    @property
    def pending_files(self) -> list[str]:
        """Return paths of files currently being tracked."""
        return self._tracker.pending_files
