"""Unit-Tests TrustedIngressMiddleware: Trust-Flag rein anhand des rohen Peers,
plus Scheme-Rekonstruktion (X-Forwarded-Proto) nur für trusted ingress.

scope["client"] wird real gesetzt (sonst wäre der LAN-/Spoof-Test ein No-op).
"""

from __future__ import annotations

import asyncio

from sprichblitz_backend.middleware.trusted_ingress import TrustedIngressMiddleware

TRUSTED = ["127.0.0.1", "::1"]


def _run(scope: dict) -> dict:
    """Lässt die Middleware laufen und gibt den (in-place mutierten) Scope zurück."""

    async def app(scope, receive, send):
        return None

    async def receive():
        return {"type": "http.request"}

    async def send(msg):
        return None

    asyncio.run(TrustedIngressMiddleware(app, TRUSTED)(scope, receive, send))
    return scope


def _flag_for(scope: dict) -> bool:
    return _run(scope).get("state", {}).get("via_trusted_ingress")


def _http(client) -> dict:
    return {"type": "http", "client": client, "headers": [], "scheme": "http"}


def test_loopback_peer_is_trusted() -> None:
    assert _flag_for(_http(("127.0.0.1", 54321))) is True


def test_ipv6_loopback_is_trusted() -> None:
    assert _flag_for(_http(("::1", 54321))) is True


def test_lan_peer_is_untrusted() -> None:
    assert _flag_for(_http(("10.0.0.9", 54321))) is False


def test_spoofed_xff_header_is_ignored() -> None:
    # LAN-Peer setzt X-Forwarded-For: 127.0.0.1 → nur der Peer zählt, Header ignoriert.
    scope = _http(("10.0.0.9", 54321))
    scope["headers"] = [(b"x-forwarded-for", b"127.0.0.1")]
    assert _flag_for(scope) is False


def test_missing_client_is_untrusted() -> None:
    assert _flag_for(_http(None)) is False


def test_non_http_scope_passes_through() -> None:
    seen: dict = {}

    async def app(scope, receive, send):
        seen["called"] = True

    asyncio.run(TrustedIngressMiddleware(app, TRUSTED)({"type": "lifespan"}, None, None))
    assert seen["called"] is True


def test_trusted_ingress_reconstructs_https_scheme() -> None:
    scope = _http(("127.0.0.1", 54321))
    scope["headers"] = [(b"x-forwarded-proto", b"https")]
    assert _run(scope)["scheme"] == "https"


def test_untrusted_peer_scheme_not_rewritten() -> None:
    # Gespoofte X-Forwarded-Proto von einem LAN-Peer darf das Schema nicht kippen.
    scope = _http(("10.0.0.9", 54321))
    scope["headers"] = [(b"x-forwarded-proto", b"https")]
    assert _run(scope)["scheme"] == "http"


def test_trusted_without_forwarded_proto_keeps_scheme() -> None:
    scope = _http(("127.0.0.1", 54321))
    assert _run(scope)["scheme"] == "http"
