"""
File copy engine for Stream Watcher.

Copies files from the watched source folder to the destination,
preserving relative structure when subdirectory mode is on.
Supports collision protection with configurable rename tokens,
SHA-256 post-copy verification, file-size gating, and automatic
retry with configurable count and delay.
Runs copies in background threads to keep the UI responsive.
"""

import hashlib
import logging
import os
import shutil
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable

from acb_sync.config import (
    COLLISION_OVERWRITE,
    COLLISION_RENAME,
    COLLISION_SKIP,
)

logger = logging.getLogger(__name__)

_HASH_CHUNK = 256 * 1024  # 256 KiB read chunks for hashing


def _sha256(filepath: Path) -> str:
    """Return the hex SHA-256 digest of *filepath*."""
    h = hashlib.sha256()
    with open(filepath, "rb") as fh:
        while chunk := fh.read(_HASH_CHUNK):
            h.update(chunk)
    return h.hexdigest()


def _expand_rename_pattern(
    pattern: str,
    name: str,
    ext: str,
    counter: int,
) -> str:
    """
    Expand token-based rename pattern.

    Supported tokens:
      {name}     — filename without extension
      {ext}      — extension without leading dot
      {n}        — collision counter (1, 2, 3, …)
      {date}     — current date YYYY-MM-DD
      {time}     — current time HH-MM-SS
      {datetime} — combined YYYY-MM-DD_HH-MM-SS
      {ts}       — integer Unix timestamp
    """
    now = datetime.now()
    return pattern.format(
        name=name,
        ext=ext,
        n=counter,
        date=now.strftime("%Y-%m-%d"),
        time=now.strftime("%H-%M-%S"),
        datetime=now.strftime("%Y-%m-%d_%H-%M-%S"),
        ts=int(now.timestamp()),
    )


@dataclass
class CopyRecord:
    """Record of a single file copy operation."""
    source: str
    destination: str
    size_bytes: int = 0
    started: float = 0.0
    finished: float = 0.0
    success: bool = False
    verified: bool = False
    skipped: bool = False
    error: str = ""

    @property
    def duration(self) -> float:
        if self.finished and self.started:
            return self.finished - self.started
        return 0.0

    @property
    def timestamp_str(self) -> str:
        """Human-readable timestamp of when the copy finished."""
        if self.finished:
            return datetime.fromtimestamp(self.finished).strftime("%Y-%m-%d %H:%M:%S")
        return ""


@dataclass
class CopyStats:
    """Aggregated copy statistics."""
    total_copied: int = 0
    total_failed: int = 0
    total_skipped: int = 0
    total_bytes: int = 0
    total_verified: int = 0
    last_copied_file: str = ""
    history: list[CopyRecord] = field(default_factory=list)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def record(self, rec: CopyRecord) -> None:
        with self._lock:
            self.history.append(rec)
            if rec.skipped:
                self.total_skipped += 1
            elif rec.success:
                self.total_copied += 1
                self.total_bytes += rec.size_bytes
                self.last_copied_file = rec.destination
                if rec.verified:
                    self.total_verified += 1
            else:
                self.total_failed += 1
            # Keep last 1000 records
            if len(self.history) > 1000:
                self.history = self.history[-1000:]


class FileCopier:
    """
    Copies files from source to destination in background threads.

    Parameters
    ----------
    source_root : str
        The root source folder being watched.
    destination_root : str
        The destination folder to copy into.
    on_copy_complete : callable, optional
        Callback invoked after each copy with the CopyRecord.
    preserve_structure : bool
        If True, preserve sub-folder structure relative to source_root.
    collision_mode : str
        One of 'overwrite', 'rename', 'skip'.
    rename_pattern : str
        Token pattern for renamed files on collision.
    verify : bool
        If True, compute SHA-256 checksums and compare after copy.
    min_size : int
        Skip files smaller than this (bytes). 0 = no minimum.
    max_size : int
        Skip files larger than this (bytes). 0 = no maximum.
    retry_count : int
        Number of retries on a failed copy (0 = no retries).
    retry_delay : int
        Seconds to wait between retry attempts.
    """

    def __init__(
        self,
        source_root: str,
        destination_root: str,
        on_copy_complete: Callable[[CopyRecord], None] | None = None,
        preserve_structure: bool = False,
        collision_mode: str = COLLISION_RENAME,
        rename_pattern: str = "{name}_{n}.{ext}",
        verify: bool = True,
        min_size: int = 0,
        max_size: int = 0,
        retry_count: int = 0,
        retry_delay: int = 5,
    ):
        self.source_root = Path(source_root)
        self.destination_root = Path(destination_root)
        self._on_copy_complete = on_copy_complete
        self._preserve_structure = preserve_structure
        self._collision_mode = collision_mode
        self._rename_pattern = rename_pattern
        self._verify = verify
        self._min_size = min_size
        self._max_size = max_size
        self._retry_count = retry_count
        self._retry_delay = retry_delay
        self.stats = CopyStats()
        self._active_copies: int = 0
        self._lock = threading.Lock()

    @property
    def active_copies(self) -> int:
        with self._lock:
            return self._active_copies

    def copy_file(self, source_path: Path) -> None:
        """Queue a background copy of *source_path* to the destination."""
        thread = threading.Thread(
            target=self._do_copy,
            args=(source_path,),
            daemon=True,
            name=f"Copy-{source_path.name}",
        )
        thread.start()

    def copy_all_now(self) -> int:
        """
        Scan the source folder and copy every file that passes gating.

        Returns the number of files queued for copy.
        """
        count = 0
        src = self.source_root
        if not src.is_dir():
            return 0
        pattern = "**/*" if self._preserve_structure else "*"
        for item in src.glob(pattern):
            if item.is_file():
                self.copy_file(item)
                count += 1
        return count

    def _base_destination(self, source_path: Path) -> Path:
        """Compute the base destination path (before collision handling)."""
        if self._preserve_structure:
            try:
                rel = source_path.relative_to(self.source_root)
            except ValueError:
                rel = Path(source_path.name)
        else:
            rel = Path(source_path.name)
        return self.destination_root / rel

    def _resolve_collision(self, dest: Path) -> Path | None:
        """
        Apply the configured collision strategy.

        Returns the final destination path, or None if the file should be skipped.
        """
        if not dest.exists():
            return dest

        if self._collision_mode == COLLISION_OVERWRITE:
            return dest

        if self._collision_mode == COLLISION_SKIP:
            return None  # caller records as skipped

        # COLLISION_RENAME — expand pattern with incrementing counter
        stem = dest.stem
        ext = dest.suffix.lstrip(".")
        parent = dest.parent
        for n in range(1, 10_000):
            new_name = _expand_rename_pattern(self._rename_pattern, stem, ext, n)
            candidate = parent / new_name
            if not candidate.exists():
                return candidate

        # Exhausted counter space — fall back to timestamp
        ts = int(time.time())
        return parent / f"{stem}_{ts}.{ext}"

    def _passes_size_gate(self, size: int) -> tuple[bool, str]:
        """Check whether the file size passes min/max gating."""
        if self._min_size and size < self._min_size:
            return False, f"File too small ({size:,} < {self._min_size:,} bytes)"
        if self._max_size and size > self._max_size:
            return False, f"File too large ({size:,} > {self._max_size:,} bytes)"
        return True, ""

    def _do_copy(self, source_path: Path) -> None:
        rec = CopyRecord(source=str(source_path), destination="")

        with self._lock:
            self._active_copies += 1

        try:
            if not source_path.exists():
                rec.error = "Source file no longer exists"
                logger.warning("Source file vanished before copy: %s", source_path)
                return

            rec.size_bytes = source_path.stat().st_size

            # ---- size gating ----
            ok, reason = self._passes_size_gate(rec.size_bytes)
            if not ok:
                rec.skipped = True
                rec.error = reason
                rec.finished = time.time()
                logger.info("Skipping %s: %s", source_path, reason)
                return

            base_dest = self._base_destination(source_path)
            base_dest.parent.mkdir(parents=True, exist_ok=True)

            # ---- collision resolution ----
            dest = self._resolve_collision(base_dest)
            if dest is None:
                rec.skipped = True
                rec.destination = str(base_dest)
                rec.error = "Skipped (collision, file already exists)"
                rec.finished = time.time()
                logger.info("Skipping (collision): %s", base_dest)
                return

            rec.destination = str(dest)

            # ---- copy with retries ----
            max_attempts = 1 + max(0, self._retry_count)
            for attempt in range(1, max_attempts + 1):
                rec.started = time.time()
                rec.success = False
                rec.verified = False
                rec.error = ""

                try:
                    logger.info(
                        "Copying %s -> %s (%d bytes, attempt %d/%d)",
                        source_path, dest, rec.size_bytes, attempt, max_attempts,
                    )
                    shutil.copy2(str(source_path), str(dest))
                    rec.finished = time.time()

                    # ---- post-copy verification ----
                    if self._verify:
                        src_hash = _sha256(source_path)
                        dst_hash = _sha256(dest)
                        if src_hash == dst_hash:
                            rec.verified = True
                            rec.success = True
                            logger.info(
                                "Verified copy (SHA-256 match) in %.1fs: %s",
                                rec.duration, dest,
                            )
                        else:
                            rec.error = (
                                f"Verification failed: SHA-256 mismatch "
                                f"(src={src_hash[:12]}… dst={dst_hash[:12]}…)"
                            )
                            logger.error("Checksum mismatch for %s", dest)
                    else:
                        if dest.exists() and dest.stat().st_size == rec.size_bytes:
                            rec.success = True
                            logger.info("Copy complete in %.1fs: %s", rec.duration, dest)
                        else:
                            rec.error = "Post-copy size mismatch"
                            logger.error("Size mismatch after copying %s", dest)

                except OSError as exc:
                    rec.error = str(exc)
                    rec.finished = time.time()
                    logger.error("Copy failed for %s: %s", source_path, exc)

                if rec.success:
                    break  # no need to retry

                if attempt < max_attempts:
                    logger.info(
                        "Retrying in %ds (attempt %d failed)…",
                        self._retry_delay, attempt,
                    )
                    time.sleep(self._retry_delay)

        except Exception as exc:
            rec.error = str(exc)
            rec.finished = time.time()
            logger.exception("Unexpected error copying %s", source_path)
        finally:
            with self._lock:
                self._active_copies -= 1
            self.stats.record(rec)
            if self._on_copy_complete:
                try:
                    self._on_copy_complete(rec)
                except Exception:
                    logger.exception("Error in on_copy_complete callback")
