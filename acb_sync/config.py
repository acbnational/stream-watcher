"""Configuration management for Stream Watcher.

Stores and retrieves user settings from a JSON config file
in the platform-appropriate application data directory.
"""

import json
import logging
from pathlib import Path
from typing import Any

from acb_sync.platform_utils import (
    get_config_dir as _platform_config_dir,
)
from acb_sync.platform_utils import (
    get_log_path as _platform_log_path,
)

logger = logging.getLogger(__name__)

# Collision resolution strategies
COLLISION_OVERWRITE = "overwrite"
COLLISION_RENAME = "rename"
COLLISION_SKIP = "skip"

# Available tokens for the rename pattern
# {name}     — original filename without extension
# {ext}      — original extension (without dot)
# {n}        — incrementing number (1, 2, 3, …)
# {date}     — date stamp YYYY-MM-DD
# {time}     — time stamp HH-MM-SS
# {datetime} — combined YYYY-MM-DD_HH-MM-SS
# {ts}       — Unix timestamp (integer)
RENAME_PATTERN_HELP = (
    "Tokens: {name} {ext} {n} {date} {time} {datetime} {ts}\n"
    "Example: {name}_copy{n}.{ext}  produces  myfile_copy1.mp3"
)
DEFAULT_RENAME_PATTERN = "{name}_{n}.{ext}"

DEFAULT_CONFIG: dict[str, Any] = {
    "source_folder": "",
    "destination_folder": "",
    "check_interval_seconds": 30,
    "stable_time_seconds": 60,
    "file_extensions": [],  # Empty = all files
    "include_patterns": [],  # Glob patterns to include (e.g. ["ACB_*", "*_stream_*"])
    "exclude_patterns": [],  # Glob patterns to exclude (e.g. ["*.tmp", "~*"])
    "sync_enabled": True,
    "copy_subdirectories": False,
    "log_level": "INFO",
    "start_minimized": True,
    "start_with_windows": False,
    # ---- collision protection ----
    "collision_mode": COLLISION_RENAME,  # overwrite | rename | skip
    "rename_pattern": DEFAULT_RENAME_PATTERN,
    # ---- verification ----
    "verify_copies": True,  # SHA-256 checksum after copy
    # ---- gating ----
    "min_file_size_bytes": 0,  # skip files smaller than this (0 = no minimum)
    "max_file_size_bytes": 0,  # skip files larger than this (0 = no maximum)
    # ---- retry ----
    "retry_count": 2,  # number of retries on failed copy (0 = no retries)
    "retry_delay_seconds": 5,  # seconds between retries
    # ---- notifications ----
    "play_sound_on_error": True,  # system alert sound on copy failure
    # ---- log rotation ----
    "max_log_size_mb": 10,  # rotate log when it exceeds this size
    "log_backup_count": 3,  # number of rotated log files to keep
    # ---- global hotkeys (all user-configurable) ----
    "hotkey_pause_resume": "ctrl+shift+f9",
    "hotkey_copy_now": "ctrl+shift+f10",
    "hotkey_status": "ctrl+shift+f11",
    "hotkey_settings": "ctrl+shift+f12",
    "hotkey_quit": "",  # blank = no hotkey assigned
}


def get_config_dir() -> Path:
    """Return the platform-appropriate application config directory."""
    return _platform_config_dir()


def get_config_path() -> Path:
    """Return the path to the configuration file."""
    return get_config_dir() / "config.json"


def get_log_path() -> Path:
    """Return the path to the log file."""
    return _platform_log_path()


class Config:
    """Thread-safe configuration manager backed by a JSON file."""

    def __init__(self, path: Path | None = None):
        """Load config from *path*, falling back to the platform default."""
        self._path = path or get_config_path()
        self._data: dict[str, Any] = dict(DEFAULT_CONFIG)
        self.load()

    # ---- persistence ----

    def load(self) -> None:
        """Load configuration from disk, applying defaults for missing keys."""
        if self._path.exists():
            try:
                with open(self._path, encoding="utf-8") as fh:
                    stored = json.load(fh)
                # Merge stored values over defaults so new keys get defaults
                self._data = {**DEFAULT_CONFIG, **stored}
                logger.info("Configuration loaded from %s", self._path)
            except (json.JSONDecodeError, OSError) as exc:
                logger.warning("Could not read config (%s); using defaults.", exc)
                self._data = dict(DEFAULT_CONFIG)
        else:
            self._data = dict(DEFAULT_CONFIG)
            self.save()
            logger.info("Created default configuration at %s", self._path)

    def save(self) -> None:
        """Persist the current configuration to disk."""
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with open(self._path, "w", encoding="utf-8") as fh:
                json.dump(self._data, fh, indent=2)
            logger.info("Configuration saved.")
        except OSError as exc:
            logger.error("Failed to save configuration: %s", exc)

    # ---- accessors ----

    @property
    def source_folder(self) -> str:
        """Return the watched source folder path."""
        return self._data["source_folder"]

    @source_folder.setter
    def source_folder(self, value: str) -> None:
        """Set the watched source folder path."""
        self._data["source_folder"] = value

    @property
    def destination_folder(self) -> str:
        """Return the copy-destination folder path."""
        return self._data["destination_folder"]

    @destination_folder.setter
    def destination_folder(self, value: str) -> None:
        """Set the copy-destination folder path."""
        self._data["destination_folder"] = value

    @property
    def check_interval(self) -> int:
        """Return the poll interval in seconds."""
        return int(self._data["check_interval_seconds"])

    @check_interval.setter
    def check_interval(self, value: int) -> None:
        """Set the poll interval (minimum 5 s)."""
        self._data["check_interval_seconds"] = max(5, int(value))

    @property
    def stable_time(self) -> int:
        """Return the stability threshold in seconds."""
        return int(self._data["stable_time_seconds"])

    @stable_time.setter
    def stable_time(self, value: int) -> None:
        """Set the stability threshold (minimum 0 s)."""
        self._data["stable_time_seconds"] = max(0, int(value))

    @property
    def file_extensions(self) -> list[str]:
        """Return the list of allowed file extensions."""
        return self._data["file_extensions"]

    @file_extensions.setter
    def file_extensions(self, value: list[str]) -> None:
        """Set allowed file extensions, normalising to lowercase."""
        self._data["file_extensions"] = [
            ext.lower().strip().lstrip(".") for ext in value if ext.strip()
        ]

    @property
    def sync_enabled(self) -> bool:
        """Return whether automatic sync is enabled."""
        return bool(self._data["sync_enabled"])

    @sync_enabled.setter
    def sync_enabled(self, value: bool) -> None:
        """Enable or disable automatic sync."""
        self._data["sync_enabled"] = value

    @property
    def copy_subdirectories(self) -> bool:
        """Return whether sub-folder structure is replicated."""
        return bool(self._data["copy_subdirectories"])

    @copy_subdirectories.setter
    def copy_subdirectories(self, value: bool) -> None:
        """Set whether sub-folder structure is replicated."""
        self._data["copy_subdirectories"] = value

    @property
    def start_minimized(self) -> bool:
        """Return whether the app starts minimised to the tray."""
        return bool(self._data["start_minimized"])

    @start_minimized.setter
    def start_minimized(self, value: bool) -> None:
        """Set whether the app starts minimised to the tray."""
        self._data["start_minimized"] = value

    @property
    def start_with_windows(self) -> bool:
        """Return whether auto-start at login is enabled."""
        return bool(self._data["start_with_windows"])

    @start_with_windows.setter
    def start_with_windows(self, value: bool) -> None:
        """Enable or disable auto-start at login."""
        self._data["start_with_windows"] = value

    @property
    def log_level(self) -> str:
        """Return the current logging level name."""
        return self._data.get("log_level", "INFO")

    @log_level.setter
    def log_level(self, value: str) -> None:
        """Set the logging level name."""
        self._data["log_level"] = value

    # ---- collision protection ----

    @property
    def collision_mode(self) -> str:
        """Return the collision resolution strategy."""
        return self._data.get("collision_mode", COLLISION_RENAME)

    @collision_mode.setter
    def collision_mode(self, value: str) -> None:
        """Set the collision resolution strategy."""
        if value not in (COLLISION_OVERWRITE, COLLISION_RENAME, COLLISION_SKIP):
            value = COLLISION_RENAME
        self._data["collision_mode"] = value

    @property
    def rename_pattern(self) -> str:
        """Return the token-based rename pattern."""
        return self._data.get("rename_pattern", DEFAULT_RENAME_PATTERN)

    @rename_pattern.setter
    def rename_pattern(self, value: str) -> None:
        """Set the token-based rename pattern."""
        self._data["rename_pattern"] = value.strip() or DEFAULT_RENAME_PATTERN

    # ---- verification ----

    @property
    def verify_copies(self) -> bool:
        """Return whether SHA-256 verification is enabled."""
        return bool(self._data.get("verify_copies", True))

    @verify_copies.setter
    def verify_copies(self, value: bool) -> None:
        """Enable or disable SHA-256 copy verification."""
        self._data["verify_copies"] = value

    # ---- gating ----

    @property
    def min_file_size(self) -> int:
        """Return the minimum file size in bytes (0 = none)."""
        return int(self._data.get("min_file_size_bytes", 0))

    @min_file_size.setter
    def min_file_size(self, value: int) -> None:
        """Set the minimum file size gate."""
        self._data["min_file_size_bytes"] = max(0, int(value))

    @property
    def max_file_size(self) -> int:
        """Return the maximum file size in bytes (0 = none)."""
        return int(self._data.get("max_file_size_bytes", 0))

    @max_file_size.setter
    def max_file_size(self, value: int) -> None:
        """Set the maximum file size gate."""
        self._data["max_file_size_bytes"] = max(0, int(value))

    # ---- global hotkeys ----

    @property
    def hotkey_pause_resume(self) -> str:
        """Return the pause/resume hotkey combo."""
        return self._data.get("hotkey_pause_resume", "ctrl+shift+f9")

    @hotkey_pause_resume.setter
    def hotkey_pause_resume(self, value: str) -> None:
        """Set the pause/resume hotkey combo."""
        self._data["hotkey_pause_resume"] = value.strip().lower()

    @property
    def hotkey_copy_now(self) -> str:
        """Return the copy-now hotkey combo."""
        return self._data.get("hotkey_copy_now", "ctrl+shift+f10")

    @hotkey_copy_now.setter
    def hotkey_copy_now(self, value: str) -> None:
        """Set the copy-now hotkey combo."""
        self._data["hotkey_copy_now"] = value.strip().lower()

    @property
    def hotkey_status(self) -> str:
        """Return the status-window hotkey combo."""
        return self._data.get("hotkey_status", "ctrl+shift+f11")

    @hotkey_status.setter
    def hotkey_status(self, value: str) -> None:
        """Set the status-window hotkey combo."""
        self._data["hotkey_status"] = value.strip().lower()

    @property
    def hotkey_settings(self) -> str:
        """Return the settings-window hotkey combo."""
        return self._data.get("hotkey_settings", "ctrl+shift+f12")

    @hotkey_settings.setter
    def hotkey_settings(self, value: str) -> None:
        """Set the settings-window hotkey combo."""
        self._data["hotkey_settings"] = value.strip().lower()

    @property
    def hotkey_quit(self) -> str:
        """Return the quit hotkey combo."""
        return self._data.get("hotkey_quit", "")

    @hotkey_quit.setter
    def hotkey_quit(self, value: str) -> None:
        """Set the quit hotkey combo."""
        self._data["hotkey_quit"] = value.strip().lower()

    # ---- include patterns ----

    @property
    def include_patterns(self) -> list[str]:
        """Glob patterns files must match to be watched (empty = all files)."""
        return self._data.get("include_patterns", [])

    @include_patterns.setter
    def include_patterns(self, value: list[str]) -> None:
        """Set glob patterns files must match."""
        self._data["include_patterns"] = [p.strip() for p in value if p.strip()]

    # ---- exclude patterns ----

    @property
    def exclude_patterns(self) -> list[str]:
        """Return glob patterns used to skip files."""
        return self._data.get("exclude_patterns", [])

    @exclude_patterns.setter
    def exclude_patterns(self, value: list[str]) -> None:
        """Set glob patterns used to skip files."""
        self._data["exclude_patterns"] = [p.strip() for p in value if p.strip()]

    # ---- retry ----

    @property
    def retry_count(self) -> int:
        """Return the number of copy retry attempts."""
        return int(self._data.get("retry_count", 2))

    @retry_count.setter
    def retry_count(self, value: int) -> None:
        """Set the number of copy retry attempts."""
        self._data["retry_count"] = max(0, int(value))

    @property
    def retry_delay(self) -> int:
        """Return seconds between retry attempts."""
        return int(self._data.get("retry_delay_seconds", 5))

    @retry_delay.setter
    def retry_delay(self, value: int) -> None:
        """Set seconds between retry attempts (minimum 1)."""
        self._data["retry_delay_seconds"] = max(1, int(value))

    # ---- notifications ----

    @property
    def play_sound_on_error(self) -> bool:
        """Return whether an alert sound plays on failure."""
        return bool(self._data.get("play_sound_on_error", True))

    @play_sound_on_error.setter
    def play_sound_on_error(self, value: bool) -> None:
        """Enable or disable the error alert sound."""
        self._data["play_sound_on_error"] = value

    # ---- log rotation ----

    @property
    def max_log_size_mb(self) -> int:
        """Return the maximum log file size in MB before rotation."""
        return int(self._data.get("max_log_size_mb", 10))

    @max_log_size_mb.setter
    def max_log_size_mb(self, value: int) -> None:
        """Set the maximum log file size in MB (minimum 1)."""
        self._data["max_log_size_mb"] = max(1, int(value))

    @property
    def log_backup_count(self) -> int:
        """Return the number of rotated log backups to keep."""
        return int(self._data.get("log_backup_count", 3))

    @log_backup_count.setter
    def log_backup_count(self, value: int) -> None:
        """Set the number of rotated log backups to keep."""
        self._data["log_backup_count"] = max(0, int(value))

    # ---- convenience ----

    def is_configured(self) -> bool:
        """Return True when both source and destination folders are set."""
        return bool(self.source_folder) and bool(self.destination_folder)
