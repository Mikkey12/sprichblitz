"""ASGI-Middleware: markiert, ob ein Request über den vertrauenswürdigen
Tunnel-Ingress (cloudflared, Loopback) kam – anhand des **rohen TCP-Peers**,
nicht eines fälschbaren Headers.

Setzt ``scope["state"]["via_trusted_ingress"]`` (lesbar als
``request.state.via_trusted_ingress``) und – **nur für trusted ingress** – die
``scope["scheme"]`` aus ``X-Forwarded-Proto`` (cloudflared terminiert TLS, der
Origin-Hop ist http). Das Schema ist KEIN PII und ersetzt die mit
``proxy_headers=False`` entfallene uvicorn-Inferenz; ohne sie zeigten Redirects
(inkl. FastAPI-Trailing-Slash-307), absolute URLs und die OpenAPI-Server-URL über
den Tunnel fälschlich auf ``http://``. Die echte Client-IP wird bewusst NICHT
rekonstruiert oder geloggt (PII – die Logging-Invariante erlaubt nur
Zähler/Latenz/Provider; zudem liest kein Code ``request.client``).

Voraussetzung: uvicorn mit ``proxy_headers=False`` – sonst überschriebe uvicorns
X-Forwarded-For-Rewrite den Peer, bevor diese Middleware ihn sieht, und ein
LAN-Client könnte sich per Header als Loopback ausgeben.
"""

from __future__ import annotations

from collections.abc import Iterable

from starlette.types import ASGIApp, Receive, Scope, Send


def _forwarded_proto(scope: Scope) -> str | None:
    for name, value in scope.get("headers", []):
        if name == b"x-forwarded-proto":
            first = value.decode("latin-1").split(",")[0].strip().lower()
            return first if first in ("http", "https") else None
    return None


class TrustedIngressMiddleware:
    def __init__(self, app: ASGIApp, trusted_proxy_ips: Iterable[str]) -> None:
        self.app = app
        self._trusted = frozenset(trusted_proxy_ips)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            client = scope.get("client")
            peer = client[0] if client else None
            trusted = peer in self._trusted
            scope.setdefault("state", {})["via_trusted_ingress"] = trusted
            if trusted:
                proto = _forwarded_proto(scope)
                if proto:
                    scope["scheme"] = proto
        await self.app(scope, receive, send)
