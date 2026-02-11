"""Entry point for Stream Watcher.

Usage:
    python -m acb_sync            Launch the GUI tray application
    python -m acb_sync --service   Install/manage the background service
                                   (Windows service, macOS launchd, or Linux daemon)
"""

import sys


def main() -> None:
    """Launch the GUI app or delegate to the service CLI."""
    if len(sys.argv) > 1 and sys.argv[1] in ("--service", "service"):
        from acb_sync.service import main as service_main

        service_main()
    else:
        from acb_sync.app import App

        app = App()
        app.run()


if __name__ == "__main__":
    main()
