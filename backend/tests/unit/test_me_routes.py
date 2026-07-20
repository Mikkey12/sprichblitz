from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine
from sqlmodel import Session, select

from sprichblitz_backend.db.models import ProviderKey

_NO_KEYS = {"anthropic": False, "openai": False, "gemini": False, "openrouter": False}


def test_me_requires_auth(client: TestClient) -> None:
    assert client.get("/me").status_code == 401


def test_get_me_returns_profile_and_key_booleans(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    res = client.get("/me", headers=auth_headers)
    assert res.status_code == 200
    body = res.json()
    assert body["name"] == "tester"
    assert body["processing_location"] == "online"  # Test-User im Fixture ist online
    assert body["keys"] == _NO_KEYS


def test_put_key_stores_encrypted_and_never_echoes(
    tls_client: TestClient, auth_headers: dict[str, str], db_engine: Engine
) -> None:
    secret = "sk-ant-TOPSECRET"
    res = tls_client.put("/me/keys/anthropic", headers=auth_headers, json={"key": secret})
    assert res.status_code == 200
    assert res.json() == {"provider": "anthropic", "configured": True}
    assert secret not in res.text  # nie zurückgespiegelt

    me = tls_client.get("/me", headers=auth_headers)
    assert me.json()["keys"]["anthropic"] is True
    assert secret not in me.text

    with Session(db_engine) as s:
        row = s.exec(select(ProviderKey)).first()
        assert row.ciphertext != secret  # verschlüsselt persistiert


def test_put_key_over_http_is_403_tls_required(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    # TLS-Sperre: Key-Upload über http wird abgewiesen (Secret nie unverschlüsselt).
    res = client.put("/me/keys/anthropic", headers=auth_headers, json={"key": "sk-x"})
    assert res.status_code == 403
    assert res.json()["code"] == "tls_required"


def test_put_empty_key_is_rejected(tls_client: TestClient, auth_headers: dict[str, str]) -> None:
    res = tls_client.put("/me/keys/anthropic", headers=auth_headers, json={"key": "   "})
    assert res.status_code == 422
    assert res.json()["code"] == "empty_key"


def test_put_unknown_provider_is_422(tls_client: TestClient, auth_headers: dict[str, str]) -> None:
    res = tls_client.put("/me/keys/notaprovider", headers=auth_headers, json={"key": "x"})
    assert res.status_code == 422


def test_delete_key_sets_boolean_false(
    tls_client: TestClient, auth_headers: dict[str, str]
) -> None:
    tls_client.put("/me/keys/openai", headers=auth_headers, json={"key": "sk-x"})
    res = tls_client.delete("/me/keys/openai", headers=auth_headers)
    assert res.status_code == 200
    assert res.json() == {"provider": "openai", "configured": False}
    assert tls_client.get("/me", headers=auth_headers).json()["keys"]["openai"] is False
