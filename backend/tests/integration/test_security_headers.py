"""HSTS (Happen 03): Strict-Transport-Security nur auf https-Antworten."""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_hsts_present_on_https(tls_client: TestClient) -> None:
    res = tls_client.get("/health")
    assert res.headers.get("strict-transport-security") == "max-age=31536000"
    assert res.headers.get("x-content-type-options") == "nosniff"


def test_no_hsts_on_plain_http(client: TestClient) -> None:
    res = client.get("/health")
    # LAN-/Loopback-http bekommt bewusst KEIN HSTS.
    assert "strict-transport-security" not in {k.lower() for k in res.headers}
    assert res.headers.get("x-content-type-options") == "nosniff"
