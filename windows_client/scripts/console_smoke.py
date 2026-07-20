"""Standalone-Smoke für die Konsolen-Webview (manuell; braucht pywebview + Tunnel).

Tauscht via ``POST /console/session`` einen Single-Use-Code und öffnet
``/console/bootstrap?code=…`` im Webview. Beweist den E2E:
Bootstrap → 302 → /app/ → app.js holt /me → Name.

Bearer + Host kommen aus dem Env (E2E ohne Keystore-Eingriff) ODER, wenn nicht
gesetzt, aus Keystore + Client-Config:

    pip install pywebview
    SPRICHBLITZ_BACKEND_URL=https://host SPRICHBLITZ_TOKEN=<bearer> python scripts/console_smoke.py
    # ohne Env: nutzt Keystore-Token + config.backend_url
"""

from __future__ import annotations

import os
import sys

from sprichblitz_client import secrets_store
from sprichblitz_client.backend.client import BackendClient
from sprichblitz_client.config import load_config


def main() -> int:
    # E2E-Override: Token/Host via Env (kein Keystore-Eingriff nötig).
    backend_url = os.environ.get("SPRICHBLITZ_BACKEND_URL") or load_config().backend_url
    token = os.environ.get("SPRICHBLITZ_TOKEN") or secrets_store.get_token()
    if not token:
        print(
            "Kein Token (setze SPRICHBLITZ_TOKEN oder richte den Client ein).",
            file=sys.stderr,
        )
        return 1
    with BackendClient(backend_url, token) as client:
        code = client.create_console_session()
    base = backend_url.rstrip("/")
    url = f"{base}/console/bootstrap?code={code}"
    print(f"Öffne Konsole gegen {base} (Code-Prefix {code[:8]}…) …")

    import webview

    webview.create_window("Sprichblitz Konsole (Smoke)", url)
    webview.start()
    return 0


if __name__ == "__main__":
    sys.exit(main())
