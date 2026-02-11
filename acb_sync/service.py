"""
Background service / daemon support for Stream Watcher.

Allows the sync engine to run headless (no GUI, no tray icon — just
file watching and copying).

**Windows** — runs as a Windows service via pywin32:
    python -m acb_sync.service install
    python -m acb_sync.service start
    python -m acb_sync.service stop
    python -m acb_sync.service remove

**macOS** — runs via a launchd LaunchAgent:
    python -m acb_sync.service install   (creates ~/Library/LaunchAgents plist)
    python -m acb_sync.service start     (launchctl load)
    python -m acb_sync.service stop      (launchctl unload)
    python -m acb_sync.service remove    (deletes plist)

**Linux** — runs as a headless foreground process:
    python -m acb_sync.service start     (blocks until Ctrl-C)
"""

import logging
import signal
import subprocess
import sys
import time
from pathlib import Path

from acb_sync.platform_utils import IS_MACOS, IS_WINDOWS

logger = logging.getLogger(__name__)

# ---- Windows service (pywin32) -----------------------------------------

_HAS_WIN32 = False
if IS_WINDOWS:
    try:
        import servicemanager  # type: ignore[import-untyped]
        import win32event  # type: ignore[import-untyped]
        import win32service  # type: ignore[import-untyped]
        import win32serviceutil  # type: ignore[import-untyped]
        _HAS_WIN32 = True
    except ImportError:
        pass

# ---- macOS launchd constants -------------------------------------------

_LAUNCHD_LABEL = "com.acbmedia.streamwatcher"
_PLIST_DIR = Path.home() / "Library" / "LaunchAgents" if IS_MACOS else Path("/dev/null")
_PLIST_PATH = _PLIST_DIR / f"{_LAUNCHD_LABEL}.plist" if IS_MACOS else Path("/dev/null")


def _run_sync_loop() -> "tuple[object, object]":
    """
    Start the core sync engine (watcher + copier) without any UI.

    Returns the (watcher, copier) so the caller can stop them.
    """
    from acb_sync.config import Config, get_log_path
    from acb_sync.copier import FileCopier
    from acb_sync.watcher import FolderWatcher

    # Set up file logging
    logging.basicConfig(
        filename=str(get_log_path()),
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    cfg = Config()
    if not cfg.is_configured():
        logger.error("Service cannot start: source/destination not configured.")
        raise RuntimeError("Stream Watcher is not configured.")

    copier = FileCopier(
        source_root=cfg.source_folder,
        destination_root=cfg.destination_folder,
        preserve_structure=cfg.copy_subdirectories,
        collision_mode=cfg.collision_mode,
        rename_pattern=cfg.rename_pattern,
        verify=cfg.verify_copies,
        min_size=cfg.min_file_size,
        max_size=cfg.max_file_size,
        retry_count=cfg.retry_count,
        retry_delay=cfg.retry_delay,
    )
    watcher = FolderWatcher(
        source_folder=cfg.source_folder,
        on_file_ready=copier.copy_file,
        stable_seconds=cfg.stable_time,
        extensions=cfg.file_extensions or None,
        include_patterns=cfg.include_patterns or None,
        exclude_patterns=cfg.exclude_patterns or None,
        recursive=cfg.copy_subdirectories,
    )
    watcher.start()
    return watcher, copier


# ======================================================================
# Windows service
# ======================================================================

if _HAS_WIN32:

    class StreamWatcherService(win32serviceutil.ServiceFramework):
        """Windows service implementation for Stream Watcher."""

        _svc_name_ = "StreamWatcher"
        _svc_display_name_ = "Stream Watcher"
        _svc_description_ = (
            "Watches a folder for new archived streaming content and copies "
            "stable files to a configured destination for the ACB Media team."
        )

        def __init__(self, args):
            super().__init__(args)
            self._stop_event = win32event.CreateEvent(None, 0, 0, None)
            self._watcher = None
            self._copier = None

        def SvcStop(self):
            self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)
            win32event.SetEvent(self._stop_event)
            if self._watcher:
                self._watcher.stop()
            logger.info("Service stop requested.")

        def SvcDoRun(self):
            servicemanager.LogMsg(
                servicemanager.EVENTLOG_INFORMATION_TYPE,
                servicemanager.PYS_SERVICE_STARTED,
                (self._svc_name_, ""),
            )
            try:
                self._watcher, self._copier = _run_sync_loop()
                win32event.WaitForSingleObject(self._stop_event, win32event.INFINITE)
            except Exception as exc:
                logger.exception("Service error: %s", exc)
                servicemanager.LogErrorMsg(f"Stream Watcher error: {exc}")
            finally:
                if self._watcher:
                    self._watcher.stop()
            logger.info("Service stopped.")


# ======================================================================
# macOS launchd helpers
# ======================================================================

def _macos_plist_content() -> str:
    """Generate the launchd plist XML for the current Python environment."""
    exe = sys.executable
    log_dir = Path.home() / "Library" / "Logs" / "StreamWatcher"
    log_dir.mkdir(parents=True, exist_ok=True)
    return f"""\
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>{_LAUNCHD_LABEL}</string>
    <key>ProgramArguments</key>
    <array>
        <string>{exe}</string>
        <string>-m</string>
        <string>acb_sync.service</string>
        <string>run</string>
    </array>
    <key>RunAtLoad</key>
    <false/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>{log_dir / 'stdout.log'}</string>
    <key>StandardErrorPath</key>
    <string>{log_dir / 'stderr.log'}</string>
</dict>
</plist>
"""


def _macos_install() -> None:
    _PLIST_DIR.mkdir(parents=True, exist_ok=True)
    _PLIST_PATH.write_text(_macos_plist_content(), encoding="utf-8")
    print(f"Installed launchd plist: {_PLIST_PATH}")


def _macos_start() -> None:
    if _PLIST_PATH.exists():
        subprocess.run(["launchctl", "load", str(_PLIST_PATH)], check=True)
        print("Stream Watcher launchd agent loaded.")
    else:
        print("Plist not found. Run 'install' first.")


def _macos_stop() -> None:
    if _PLIST_PATH.exists():
        subprocess.run(["launchctl", "unload", str(_PLIST_PATH)], check=False)
        print("Stream Watcher launchd agent unloaded.")
    else:
        print("Plist not found.")


def _macos_remove() -> None:
    _macos_stop()
    if _PLIST_PATH.exists():
        _PLIST_PATH.unlink()
        print("Removed launchd plist.")


# ======================================================================
# Cross-platform headless runner (Linux / fallback)
# ======================================================================

def _run_foreground() -> None:
    """Run the sync engine in the foreground until SIGINT/SIGTERM."""
    watcher, _ = _run_sync_loop()
    stop = False

    def _handler(sig, frame):
        nonlocal stop
        stop = True
        watcher.stop()

    signal.signal(signal.SIGINT, _handler)
    signal.signal(signal.SIGTERM, _handler)

    print("Stream Watcher running (press Ctrl-C to stop)\u2026")
    while not stop:
        time.sleep(1)
    print("Stream Watcher stopped.")


# ======================================================================
# CLI entry
# ======================================================================

def main() -> None:
    """Entry point when this module is run for service/daemon control."""
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""

    # ---- Windows ----
    if IS_WINDOWS:
        if not _HAS_WIN32:
            print("ERROR: pywin32 is required for service mode on Windows.")
            print("       pip install pywin32")
            sys.exit(1)
        if cmd == "":
            try:
                servicemanager.Initialize()
                servicemanager.PrepareToHostSingle(StreamWatcherService)
                servicemanager.StartServiceCtrlDispatcher()
            except Exception:
                _show_help()
        else:
            win32serviceutil.HandleCommandLine(StreamWatcherService)
        return

    # ---- macOS ----
    if IS_MACOS:
        actions = {
            "install": _macos_install,
            "start": _macos_start,
            "stop": _macos_stop,
            "remove": _macos_remove,
        }
        if cmd in actions:
            actions[cmd]()
        elif cmd == "run":
            _run_foreground()
        else:
            _show_help()
        return

    # ---- Linux / other ----
    if cmd == "start":
        _run_foreground()
    else:
        _show_help()


def _show_help() -> None:
    platform = "Windows" if IS_WINDOWS else ("macOS" if IS_MACOS else "Linux")
    print(f"Stream Watcher \u2014 Background Service  ({platform})")
    print()
    if IS_WINDOWS:
        print("Usage:")
        print("  python -m acb_sync.service install   Install the Windows service")
        print("  python -m acb_sync.service start     Start the service")
        print("  python -m acb_sync.service stop      Stop the service")
        print("  python -m acb_sync.service remove    Uninstall the service")
    elif IS_MACOS:
        print("Usage:")
        print("  python -m acb_sync.service install   Create launchd plist")
        print("  python -m acb_sync.service start     Load the launchd agent")
        print("  python -m acb_sync.service stop      Unload the launchd agent")
        print("  python -m acb_sync.service remove    Remove the plist")
        print("  python -m acb_sync.service run       Run in foreground")
    else:
        print("Usage:")
        print("  python -m acb_sync.service start     Run in foreground (Ctrl-C to stop)")


def install_service() -> None:
    """Convenience wrapper to install the platform service."""
    if IS_WINDOWS:
        if not _HAS_WIN32:
            print("ERROR: pywin32 is required to install as a service.")
            print("       pip install pywin32")
            sys.exit(1)
        sys.argv = [sys.argv[0], "install"]
        win32serviceutil.HandleCommandLine(StreamWatcherService)
    elif IS_MACOS:
        _macos_install()
    else:
        print("On Linux, use: python -m acb_sync.service start")


if __name__ == "__main__":
    main()
