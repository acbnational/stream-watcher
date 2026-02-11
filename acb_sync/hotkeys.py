"""Global hotkey support for Stream Watcher.

Registers system-wide keyboard shortcuts so the user can
pause/resume sync, trigger an immediate copy, open the
status / settings windows, and quit — from any application.

Uses the ``keyboard`` library for low-level hook-based hotkeys.
Supported on Windows and macOS (macOS requires Accessibility
permissions in System Settings > Privacy & Security > Accessibility).
"""

import logging
from collections.abc import Callable

logger = logging.getLogger(__name__)

try:
    import keyboard as _kb  # type: ignore[import-untyped]

    _HAS_KEYBOARD = True
except ImportError:
    _HAS_KEYBOARD = False
    logger.warning("keyboard library not installed — global hotkeys disabled.")


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
