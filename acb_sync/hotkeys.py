"""Global hotkey support for Stream Watcher.

Registers system-wide keyboard shortcuts so the user can
pause/resume sync, trigger an immediate copy, open the
status / settings windows, and quit — from any application.

Uses the ``keyboard`` library for low-level hook-based hotkeys.
Supported on Windows and macOS (macOS requires Accessibility
permissions in System Settings > Privacy & Security > Accessibility).
"""

import logging
import os
import platform
import threading
from collections.abc import Callable

logger = logging.getLogger(__name__)

try:
    import keyboard as _kb  # type: ignore[import-untyped]

    _HAS_KEYBOARD = True
except ImportError:
    _HAS_KEYBOARD = False
    logger.warning("keyboard library not installed — global hotkeys disabled.")

# ---------------------------------------------------------------------------
# macOS root-privilege check
# ---------------------------------------------------------------------------
_MACOS_ROOT_MSG = (
    "Global hotkeys unavailable — the keyboard library requires root on "
    "macOS. Run with sudo, or use the menu/status-window controls instead."
)


def _can_listen() -> bool:
    """Return True if the keyboard listener will work on this OS.

    On macOS the ``keyboard`` library unconditionally checks
    ``os.geteuid() == 0`` before starting its listener thread.  If the
    process is not root the listener raises ``OSError`` in a background
    thread and may trigger a SIGTRAP that kills the process.  We mirror
    that same check here so we can skip registration gracefully.
    """
    if platform.system() != "Darwin":
        return True
    return os.geteuid() == 0


# Safety net: if the keyboard listener thread still dies (e.g. on a platform
# we didn't pre-check), log a warning instead of printing a scary traceback.
_original_excepthook = threading.excepthook


def _hotkey_excepthook(args: threading.ExceptHookArgs) -> None:
    if (
        args.thread is not None
        and args.thread.name == "listen"
        and isinstance(args.exc_value, OSError)
    ):
        logger.warning(_MACOS_ROOT_MSG)
        return
    _original_excepthook(args)


threading.excepthook = _hotkey_excepthook


class GlobalHotkeys:
    """Register and unregister up to five global hotkeys.

    All five slots are user-configurable.  Pass an empty string to
    leave a slot unassigned.

    Parameters
    ----------
    pause_resume_key, copy_now_key, status_key, settings_key, quit_key : str
        Hotkey combo strings, e.g. ``'ctrl+shift+f9'``.
    on_pause_resume, on_copy_now, on_status, on_settings, on_quit : callable
        Callbacks invoked when the corresponding hotkey is pressed.

    """

    def __init__(
        self,
        pause_resume_key: str,
        copy_now_key: str,
        status_key: str,
        settings_key: str,
        quit_key: str,
        on_pause_resume: Callable[[], None],
        on_copy_now: Callable[[], None],
        on_status: Callable[[], None],
        on_settings: Callable[[], None],
        on_quit: Callable[[], None],
    ):
        """Bind the five hotkey slots to their callbacks."""
        self._keys = {
            "pause_resume": pause_resume_key,
            "copy_now": copy_now_key,
            "status": status_key,
            "settings": settings_key,
            "quit": quit_key,
        }
        self._callbacks = {
            "pause_resume": on_pause_resume,
            "copy_now": on_copy_now,
            "status": on_status,
            "settings": on_settings,
            "quit": on_quit,
        }
        self._registered = False

    @property
    def available(self) -> bool:
        """Return whether the keyboard library is importable."""
        return _HAS_KEYBOARD

    def register(self) -> None:
        """Register all global hotkeys."""
        if not _HAS_KEYBOARD:
            logger.info("Global hotkeys unavailable (keyboard library missing).")
            return
        if self._registered:
            return
        if not _can_listen():
            logger.warning(_MACOS_ROOT_MSG)
            return
        try:
            for name, key in self._keys.items():
                if key:
                    _kb.add_hotkey(key, self._callbacks[name], suppress=False)
                    logger.info("Registered hotkey %s = %s", name, key)
            self._registered = True
        except Exception:
            logger.exception("Failed to register global hotkeys.")

    def unregister(self) -> None:
        """Unregister all global hotkeys."""
        if not _HAS_KEYBOARD or not self._registered:
            return
        try:
            _kb.unhook_all_hotkeys()
            self._registered = False
            logger.info("Global hotkeys unregistered.")
        except Exception:
            logger.exception("Error unregistering hotkeys.")

    def update_keys(
        self,
        pause_resume_key: str,
        copy_now_key: str,
        status_key: str,
        settings_key: str = "",
        quit_key: str = "",
    ) -> None:
        """Re-register hotkeys with new key combos."""
        self.unregister()
        self._keys["pause_resume"] = pause_resume_key
        self._keys["copy_now"] = copy_now_key
        self._keys["status"] = status_key
        self._keys["settings"] = settings_key
        self._keys["quit"] = quit_key
        self.register()
