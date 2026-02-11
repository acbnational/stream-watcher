"""
Main application controller for Stream Watcher.

Ties together configuration, file watching, copying, the system tray,
global hotkeys, screen-reader notifications, and the accessible tkinter UI.

Cross-platform: Windows, macOS, and Linux.
"""

import logging
import logging.handlers
import sys
import threading
from pathlib import Path

from acb_sync import __app_name__, __version__
from acb_sync.config import Config, get_log_path
from acb_sync.copier import CopyRecord, CopyStats, FileCopier
from acb_sync.hotkeys import GlobalHotkeys
from acb_sync.notify import notifier
from acb_sync.platform_utils import (
    IS_MACOS,
    play_error_sound,
    register_autostart,
    unregister_autostart,
)
from acb_sync.tray import SysTray
from acb_sync.ui import SettingsWindow, StatusWindow
from acb_sync.watcher import FolderWatcher

logger = logging.getLogger(__name__)

# Tray colours
_COLOR_ACTIVE = "#0A6E0A"  # green — sync running
_COLOR_PAUSED = "#888888"  # grey  — sync paused
_COLOR_ERROR = "#C4001A"   # red   — error / not configured


class App:
    """
    Central orchestrator.

    Implements the TrayCallbacks protocol expected by SysTray.
    """

    def __init__(self) -> None:
        self.config = Config()
        self.watcher: FolderWatcher | None = None
        self.copier: FileCopier | None = None

        # tkinter root — hidden, used only to drive the event loop
        import tkinter as tk

        self._root = tk.Tk()
        self._root.title(__app_name__)
        self._root.withdraw()  # Hide the root window

        self._settings_win = SettingsWindow(self)
        self._status_win = StatusWindow(self)
        self._tray = SysTray(self)

        # Global hotkeys (all five user-configurable slots)
        cfg = self.config
        self._hotkeys = GlobalHotkeys(
            pause_resume_key=cfg.hotkey_pause_resume,
            copy_now_key=cfg.hotkey_copy_now,
            status_key=cfg.hotkey_status,
            settings_key=cfg.hotkey_settings,
            quit_key=cfg.hotkey_quit,
            on_pause_resume=self.on_toggle_sync,
            on_copy_now=self.on_copy_now,
            on_status=self.on_open_status,
            on_settings=self.on_open_settings,
            on_quit=self.on_quit,
        )

        # Ensure clean shutdown on WM_DELETE_WINDOW of root
        self._root.protocol("WM_DELETE_WINDOW", self.on_quit)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def run(self) -> None:
        """Start the application (tray + optional sync, then enter tk mainloop)."""
        self._setup_logging()

        logger.info("%s %s starting.", __app_name__, __version__)

        # Manage autostart registration
        self._sync_autostart()

        # Start system tray
        self._tray.start()

        # Register global hotkeys
        self._hotkeys.register()

        # Auto-start sync if configured and enabled
        if self.config.is_configured() and self.config.sync_enabled:
            self._start_sync()
        else:
            self._update_tray_state()

        # If not configured, open settings automatically
        if not self.config.is_configured():
            self._root.after(300, self.on_open_settings)
        elif not self.config.start_minimized:
            self._root.after(300, self.on_open_status)

        notifier.speak(f"{__app_name__} is running.")

        # Enter the tkinter main loop
        self._root.mainloop()

    # ------------------------------------------------------------------
    # Sync control
    # ------------------------------------------------------------------

    def _start_sync(self) -> None:
        """Start the watcher + copier."""
        cfg = self.config
        if not cfg.is_configured():
            logger.warning("Cannot start sync: not configured.")
            return

        try:
            self.copier = FileCopier(
                source_root=cfg.source_folder,
                destination_root=cfg.destination_folder,
                on_copy_complete=self._on_copy_complete,
                preserve_structure=cfg.copy_subdirectories,
                collision_mode=cfg.collision_mode,
                rename_pattern=cfg.rename_pattern,
                verify=cfg.verify_copies,
                min_size=cfg.min_file_size,
                max_size=cfg.max_file_size,
                retry_count=cfg.retry_count,
                retry_delay=cfg.retry_delay,
            )
            self.watcher = FolderWatcher(
                source_folder=cfg.source_folder,
                on_file_ready=self.copier.copy_file,
                stable_seconds=cfg.stable_time,
                extensions=cfg.file_extensions or None,
                include_patterns=cfg.include_patterns or None,
                exclude_patterns=cfg.exclude_patterns or None,
                recursive=cfg.copy_subdirectories,
            )
            self.watcher.start()
            cfg.sync_enabled = True
            cfg.save()
            logger.info("Sync started.")
        except FileNotFoundError as exc:
            logger.error("Cannot start sync: %s", exc)
            cfg.sync_enabled = False
        except Exception:
            logger.exception("Failed to start sync.")
            cfg.sync_enabled = False

        self._update_tray_state()

    def _stop_sync(self) -> None:
        """Stop the watcher (copier finishes active copies)."""
        if self.watcher:
            self.watcher.stop()
            self.watcher = None
        self.config.sync_enabled = False
        self.config.save()
        self._update_tray_state()
        logger.info("Sync stopped.")

    def restart_sync(self) -> None:
        """Restart sync with current config (called after settings change)."""
        self._stop_sync()
        # Refresh hotkey bindings with potentially updated keys
        cfg = self.config
        self._hotkeys.update_keys(
            pause_resume_key=cfg.hotkey_pause_resume,
            copy_now_key=cfg.hotkey_copy_now,
            status_key=cfg.hotkey_status,
            settings_key=cfg.hotkey_settings,
            quit_key=cfg.hotkey_quit,
        )
        # Sync autostart with current setting
        self._sync_autostart()
        if cfg.is_configured():
            cfg.sync_enabled = True
            self._start_sync()
        notifier.speak("Settings saved. Sync restarted.")

    # ------------------------------------------------------------------
    # TrayCallbacks implementation
    # ------------------------------------------------------------------

    def on_open_status(self) -> None:
        """Show the status window (thread-safe)."""
        self._root.after(0, self._status_win.show)

    def on_open_settings(self) -> None:
        """Show the settings window (thread-safe)."""
        self._root.after(0, self._settings_win.show)

    def on_toggle_sync(self) -> None:
        """Pause or resume sync."""
        if self.config.sync_enabled:
            self._stop_sync()
            notifier.speak("Sync paused.")
        else:
            self._start_sync()
            notifier.speak("Sync resumed.")
        self._tray.refresh_menu()

    def on_copy_now(self) -> None:
        """Trigger an immediate copy of all pending stable files."""
        if self.copier is None:
            notifier.speak("Sync is not running. Cannot copy.")
            return

        notifier.speak("Copying all pending files now.")

        def _do():
            count = self.copier.copy_all_now()
            msg = f"Queued {count} file{'s' if count != 1 else ''} for copy."
            notifier.speak(msg)
            self._update_tray_state()

        threading.Thread(target=_do, daemon=True, name="CopyNow").start()

    def on_quit(self) -> None:
        """Cleanly shut down the application."""
        logger.info("Shutting down\u2026")
        self._hotkeys.unregister()
        self._stop_sync()
        self._tray.stop()
        notifier.speak(f"{__app_name__} closing.")
        self._root.quit()
        self._root.destroy()

    def is_sync_enabled(self) -> bool:
        return self.config.sync_enabled

    def get_status_summary(self) -> str:
        """Return a short human-readable status string for the tray menu."""
        cfg = self.config
        if not cfg.is_configured():
            return "Not configured"
        if not cfg.sync_enabled:
            return "Paused"
        stats = self.copier.stats if self.copier else None
        if stats:
            return f"Active \u2014 {stats.total_copied} copied, {stats.total_failed} failed"
        return "Active"

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _on_copy_complete(self, rec: CopyRecord) -> None:
        """Called (from copier thread) after each copy finishes."""
        name = Path(rec.destination).name if rec.destination else "unknown"
        if rec.skipped:
            self._tray.update_tooltip(f"Skipped: {name}")
            notifier.speak(f"Skipped {name}.")
        elif rec.success:
            suffix = " (verified)" if rec.verified else ""
            self._tray.update_tooltip(f"Copied: {name}{suffix}")
            notifier.speak(f"Copied {name}{suffix}.")
        else:
            short_err = (rec.error or "unknown error")[:60]
            self._tray.update_tooltip(f"Copy failed: {short_err}")
            notifier.speak(f"Copy failed: {short_err}.")
            # Play error sound if enabled
            if self.config.play_sound_on_error:
                play_error_sound()
        self._tray.refresh_menu()

    def _update_tray_state(self) -> None:
        """Update tray icon colour and tooltip to reflect current state."""
        cfg = self.config
        summary = self.get_status_summary()
        if not cfg.is_configured():
            self._tray.update_icon_color(_COLOR_ERROR)
        elif cfg.sync_enabled:
            self._tray.update_icon_color(_COLOR_ACTIVE)
        else:
            self._tray.update_icon_color(_COLOR_PAUSED)
        self._tray.update_tooltip(f"Stream Watcher \u2014 {summary}")
        self._tray.refresh_menu()

    def _sync_autostart(self) -> None:
        """Register or unregister autostart based on config."""
        if self.config.start_with_windows:
            register_autostart()
        else:
            unregister_autostart()

    def _setup_logging(self) -> None:
        """Configure rotating file log and stderr handler."""
        log_path = get_log_path()
        level = getattr(logging, self.config.log_level.upper(), logging.INFO)
        root_logger = logging.getLogger()
        root_logger.setLevel(level)

        fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")

        # Rotating file handler
        max_bytes = self.config.max_log_size_mb * 1024 * 1024
        fh = logging.handlers.RotatingFileHandler(
            str(log_path),
            maxBytes=max_bytes,
            backupCount=self.config.log_backup_count,
            encoding="utf-8",
        )
        fh.setLevel(level)
        fh.setFormatter(fmt)
        root_logger.addHandler(fh)

        # Stderr handler (for development)
        sh = logging.StreamHandler(sys.stderr)
        sh.setLevel(level)
        sh.setFormatter(fmt)
        root_logger.addHandler(sh)
