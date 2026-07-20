"""PATCH /me/settings: processing_location umschalten + Validierung."""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_patch_settings_changes_location(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    # Test-User ist online; auf local umstellen.
    res = client.patch(
        "/me/settings", headers=auth_headers, json={"processing_location": "local"}
    )
    assert res.status_code == 200
    assert res.json()["processing_location"] == "local"
    # GET /me spiegelt die Änderung (frischer Principal-Lookup).
    me = client.get("/me", headers=auth_headers)
    assert me.json()["processing_location"] == "local"


def test_patch_settings_rejects_invalid_location(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    res = client.patch(
        "/me/settings", headers=auth_headers, json={"processing_location": "nirgendwo"}
    )
    assert res.status_code == 422


def test_patch_settings_requires_auth(client: TestClient) -> None:
    res = client.patch("/me/settings", json={"processing_location": "local"})
    assert res.status_code == 401
