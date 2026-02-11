"""
Cross-platform utilities for Stream Watcher.

Centralises all OS-detection logic so every other module can import
a single canonical set of helpers rather than scattering ``sys.platform``
checks throughout the codebase.

Supported platforms:
  - Windows 10/11
  - macOS 12+ (Monterey and newer)
  - Linux (best-effort; no service support yet)
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

# ---- platform flags ----------------------------------------------------

IS_WINDOWS: bool = sys.platform == "win32"
IS_MACOS: bool = sys.platform == "darwin"
IS_LINUX: bool = sys.platform.startswith("linux")

# ---- directories -------------------------------------------------------


def get_config_dir() -> Path:
    """
    Return the application config directory, created if needed.

    - Windows : ``%APPDATA%\\StreamWatcher``
    - macOS   : ``~/Library/Application Support/StreamWatcher``
    - Linux   : ``$XDG_CONFIG_HOME/StreamWatcher`` (default ``~/.config``)
    """
    if IS_WINDOWS:
        base = os.environ.get("APPDATA", str(Path.home()))
    elif IS_MACOS:
        base = str(Path.home() / "Library" / "Application Support")
    else:
        base = os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config"))

    config_dir = Path(base) / "StreamWatcher"
    config_dir.mkdir(parents=True, exist_ok=True)
    return config_dir


def get_log_path() -> Path:
    """Return the path to the log file (inside the config directory)."""
    return get_config_dir() / "stream_watcher.log"


# ---- UI helpers ---------------------------------------------------------


def get_system_font() -> str:
    """Return a good default UI font for the current platform."""
    if IS_MACOS:
        return "Helvetica Neue"
    if IS_LINUX:
        return "DejaVu Sans"
    return "Segoe UI"


def get_super_modifier_label() -> str:
    """Return the human-readable name of the 'super' modifier key.

    - macOS: ``command`` (⌘)
    - Windows/Linux: ``win``
    """
    return "command" if IS_MACOS else "win"


# ---- desktop integration -----------------------------------------------


def open_file_in_default_app(filepath: str | Path) -> None:
    """Open a file with the OS default application."""
    fp = str(filepath)
    try:
        if IS_WINDOWS:
            os.startfile(fp)  # type: ignore[attr-defined]
        elif IS_MACOS:
            subprocess.Popen(["open", fp])
        else:
            subprocess.Popen(["xdg-open", fp])
    except Exception:
        logger.warning("Could not open file: %s", fp, exc_info=True)


def play_error_sound() -> None:
    """Play the OS error/alert sound.  Silent on unsupported platforms."""
    try:
        if IS_WINDOWS:
            import winsound  # type: ignore[import-untyped]
            winsound.MessageBeep(winsound.MB_ICONHAND)
        elif IS_MACOS:
            # Basso is the standard macOS alert sound
            subprocess.Popen(
                ["afplay", "/System/Library/Sounds/Basso.aiff"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        # Linux: no universal system sound — skip
    except Exception:
        logger.debug("Could not play error sound.", exc_info=True)


# ---- auto-start / login items ------------------------------------------

_AUTOSTART_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
_AUTOSTART_NAME = "StreamWatcher"
_LAUNCHD_LABEL = "com.acbmedia.streamwatcher"


def register_autostart() -> bool:
    """Register Stream Watcher to start at login.  Returns True on success."""
    exe = sys.executable
    cmd = f'"{exe}" -m acb_sync'

    if IS_WINDOWS:
        try:
            import winreg  # type: ignore[import-untyped]
            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER, _AUTOSTART_KEY, 0, winreg.KEY_SET_VALUE
            ) as key:
                winreg.SetValueEx(key, _AUTOSTART_NAME, 0, winreg.REG_SZ, cmd)
            logger.info("Registered Windows autostart.")
            return True
        except Exception:
            logger.exception("Failed to register Windows autostart.")
            return False

    if IS_MACOS:
        plist_dir = Path.home() / "Library" / "LaunchAgents"
        plist_dir.mkdir(parents=True, exist_ok=True)
        plist_path = plist_dir / f"{_LAUNCHD_LABEL}.plist"
        plist_content = f"""\
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
        <string>acb_sync</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <false/>
</dict>
</plist>
"""
        try:
            plist_path.write_text(plist_content, encoding="utf-8")
            logger.info("Created launchd plist at %s", plist_path)
            return True
        except Exception:
            logger.exception("Failed to create launchd plist.")
            return False

    if IS_LINUX:
        autostart_dir = Path(
            os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config"))
        ) / "autostart"
        autostart_dir.mkdir(parents=True, exist_ok=True)
        desktop_path = autostart_dir / "stream-watcher.desktop"
        desktop_content = f"""\
[Desktop Entry]
Type=Application
Name=Stream Watcher
Exec={exe} -m acb_sync
Hidden=false
NoDisplay=false
X-GNOME-Autostart-enabled=true
"""
        try:
            desktop_path.write_text(desktop_content, encoding="utf-8")
            logger.info("Created autostart desktop entry at %s", desktop_path)
            return True
        except Exception:
            logger.exception("Failed to create autostart desktop entry.")
            return False

    return False


def unregister_autostart() -> bool:
    """Remove Stream Watcher from login items.  Returns True on success."""
    if IS_WINDOWS:
        try:
            import winreg
            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER, _AUTOSTART_KEY, 0, winreg.KEY_SET_VALUE
            ) as key:
                winreg.DeleteValue(key, _AUTOSTART_NAME)
            logger.info("Removed Windows autostart.")
            return True
        except FileNotFoundError:
            return True  # already absent
        except Exception:
            logger.exception("Failed to remove Windows autostart.")
            return False

    if IS_MACOS:
        plist_path = Path.home() / "Library" / "LaunchAgents" / f"{_LAUNCHD_LABEL}.plist"
        try:
            plist_path.unlink(missing_ok=True)
            logger.info("Removed launchd plist.")
            return True
        except Exception:
            logger.exception("Failed to remove launchd plist.")
            return False

    if IS_LINUX:
        desktop_path = Path(
            os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config"))
        ) / "autostart" / "stream-watcher.desktop"
        try:
            desktop_path.unlink(missing_ok=True)
            return True
        except Exception:
            logger.exception("Failed to remove autostart desktop entry.")
            return False

    return False
