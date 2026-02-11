"""Screen reader / speech notification helper for Stream Watcher.

On Windows, uses accessible_output2 to speak announcements through
the active screen reader (JAWS, NVDA, Narrator).  On macOS, falls
back to the built-in ``say`` command so VoiceOver users get spoken
alerts.  On other platforms the notifications are silently discarded.
"""

import logging
import subprocess
import threading

from acb_sync.platform_utils import IS_MACOS, IS_WINDOWS

logger = logging.getLogger(__name__)

# ---- accessible_output2 (Windows screen readers) ----
_HAS_AO2 = False
if IS_WINDOWS:
    try:
        from accessible_output2.outputs.auto import (
            Auto as _AO2Auto,  # type: ignore[import-untyped]
        )

        _HAS_AO2 = True
    except ImportError:
        logger.warning(
            "accessible_output2 not installed — screen reader notifications disabled."
        )


class ScreenReaderNotifier:
    """Thread-safe cross-platform speech notifier.

    - Windows: accessible_output2 (JAWS / NVDA / Narrator)
    - macOS: ``say`` CLI command (heard by VoiceOver users)
    - Other: silent no-op

    Call ``speak(text)`` to push an announcement.
    The call is non-blocking — speech is dispatched on a daemon thread.
    """

    def __init__(self) -> None:
        """Detect and bind to the active screen reader output."""
        self._output = _AO2Auto() if _HAS_AO2 else None  # type: ignore[name-defined]

    def speak(self, text: str, interrupt: bool = True) -> None:
        """Announce *text* via the active screen reader or system TTS.

        Parameters
        ----------
        text : str
            The message to speak.
        interrupt : bool
            If True, interrupt any in-progress speech first.

        """
        if not self._output and not IS_MACOS:
            logger.debug("SR notify (no output): %s", text)
            return

        # Fire-and-forget on a daemon thread so we never block
        threading.Thread(
            target=self._do_speak,
            args=(text, interrupt),
            daemon=True,
            name="SRNotify",
        ).start()

    def _do_speak(self, text: str, interrupt: bool) -> None:
        try:
            if self._output:
                self._output.speak(text, interrupt=interrupt)
                logger.debug("SR spoke: %s", text)
            elif IS_MACOS:
                # macOS: use the built-in `say` command
                subprocess.run(
                    ["say", text],
                    timeout=15,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                logger.debug("macOS say: %s", text)
        except Exception:
            logger.debug("Speech notification failed.", exc_info=True)

    @property
    def available(self) -> bool:
        """True if a speech backend is available."""
        return _HAS_AO2 or IS_MACOS


# Module-level singleton — import and use from anywhere.
notifier = ScreenReaderNotifier()
