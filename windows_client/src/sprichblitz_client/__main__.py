"""Entry-Point für ``python -m sprichblitz_client`` und PyInstaller.

PyInstaller-Spec (siehe ``build/sprichblitz.spec``) referenziert dieses
Modul. Der eigentliche Lifecycle steckt in :class:`ClientApp`.
"""

from __future__ import annotations

import sys

from sprichblitz_client.app import ClientApp


def main() -> int:
    # Eigener Webview-Prozess (vom Tray gespawnt): liest die Bootstrap-URL von stdin.
    if "--console-webview" in sys.argv[1:]:
        # Der Child-Prozess durchläuft ClientApp.run() nicht. Ohne eigene
        # Initialisierung blieben Logurus diagnose/backtrace-Defaults aktiv und
        # könnten kurzlebige Bootstrap-Daten aus Exception-Locals protokollieren.
        from sprichblitz_client.logging_setup import configure_logging
        from sprichblitz_client.ui.console_webview import run_from_stdin

        configure_logging()
        return run_from_stdin()
    return ClientApp().run()


if __name__ == "__main__":
    sys.exit(main())
