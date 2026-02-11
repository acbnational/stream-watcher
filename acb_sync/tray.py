"""System tray icon for Stream Watcher.

Provides a persistent system-tray presence with a context menu
to open settings, view status, pause/resume sync, copy now, and quit.
The tooltip dynamically shows the current state and copy count.
"""

import contextlib
import logging
import threading
from typing import Protocol, Any

import pystray
from PIL import Image, ImageDraw
from PIL.Image import Image as PILImage

logger = logging.getLogger(__name__)


class TrayCallbacks(Protocol):
    """Expected callback interface for the tray icon owner."""

    def on_open_status(self) -> None:
        """Open the status window."""
        ...

    def on_open_settings(self) -> None:
        """Open the settings window."""
        ...

    def on_toggle_sync(self) -> None:
        """Toggle sync on or off."""
        ...

    def on_copy_now(self) -> None:
        """Trigger an immediate copy sweep."""
        ...

    def on_quit(self) -> None:
        """Quit the application."""
        ...

    def is_sync_enabled(self) -> bool:
        """Return whether sync is currently active."""
        ...

    def get_status_summary(self) -> str:
        """Return a human-readable status string."""
        ...


def _create_icon_image(color: str = "#0078D4", size: int = 64) -> PILImage:
    """Create a simple solid-colour square icon with an inner circle indicator."""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    # Background rounded-ish square
    draw.rounded_rectangle(
        [(2, 2), (size - 2, size - 2)],
        radius=10,
        fill=color,
    )
    # Inner white circle as a sync indicator
    margin = size // 4
    draw.ellipse(
        [(margin, margin), (size - margin, size - margin)],
        fill="white",
    )
    return img


class SysTray:
    """Manages the system-tray icon and its context menu.

    The tray runs on its own thread so it does not block the tkinter main loop.
    """

    def __init__(self, callbacks: TrayCallbacks):
        """Create the tray icon bound to *callbacks*."""
        self._callbacks = callbacks
        self._icon: Any | None = None
        self._thread: threading.Thread | None = None

    def _build_menu(self) -> pystray.Menu:
        """Build the context menu with current status."""
        sync_label = (
            "Pause Sync" if self._callbacks.is_sync_enabled() else "Resume Sync"
        )
        status_text = self._callbacks.get_status_summary()
        return pystray.Menu(
            pystray.MenuItem(f"Stream Watcher — {status_text}", None, enabled=False),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Status Window", lambda: self._callbacks.on_open_status()),
            pystray.MenuItem("Settings", lambda: self._callbacks.on_open_settings()),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(sync_label, lambda: self._callbacks.on_toggle_sync()),
            pystray.MenuItem("Copy All Now", lambda: self._callbacks.on_copy_now()),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Quit", lambda: self._callbacks.on_quit()),
        )

    def start(self) -> None:
        """Start the tray icon on a daemon thread."""
        icon_img = _create_icon_image()
        self._icon = pystray.Icon(
            name="StreamWatcher",
            icon=icon_img,
            title="Stream Watcher",
            menu=self._build_menu(),
        )

        # Capture local reference so type-checker knows it's not None
        icon = self._icon
        if icon is None:
            return
        self._thread = threading.Thread(target=icon.run, daemon=True, name="SysTray")
        self._thread.start()
        logger.info("System tray icon started.")

    def stop(self) -> None:
        """Remove the tray icon and stop its thread."""
        if self._icon:
            with contextlib.suppress(Exception):
                self._icon.stop()
            self._icon = None
        logger.info("System tray icon stopped.")

    def update_tooltip(self, text: str) -> None:
        """Update the hover tooltip text."""
        if self._icon:
            self._icon.title = text

    def update_icon_color(self, color: str) -> None:
        """Change the icon colour to reflect state (e.g. green=active, grey=paused)."""
        if self._icon:
            self._icon.icon = _create_icon_image(color)

    def refresh_menu(self) -> None:
        """Rebuild the context menu (e.g. after toggling sync)."""
        if self._icon:
            self._icon.menu = self._build_menu()
            self._icon.update_menu()
