from __future__ import annotations

import uvicorn

from .app import create_app
from .config import load_config


def main() -> None:
    cfg = load_config()
    app = create_app(cfg)
    uvicorn.run(
        app,
        host=cfg.server.host,
        port=cfg.server.port,
        # Etappe 6: uvicorns X-Forwarded-For-Rewrite AUS. Die TrustedIngressMiddleware
        # braucht den rohen TCP-Peer, um Tunnel (cloudflared, Loopback) hart vom LAN zu
        # trennen; mit proxy_headers ist forwarded_allow_ips ohnehin wirkungslos.
        proxy_headers=False,
        # E7: uvicorn-Access-Log AUS – enthält die Client-Addr (PII) und ist mit
        # proxy_headers=False ohnehin nur 127.0.0.1. uvicorn.error (Startup-Zeilen)
        # läuft über den Loguru-Intercept in logging_setup.
        access_log=False,
        log_config=None,
    )


if __name__ == "__main__":
    main()
