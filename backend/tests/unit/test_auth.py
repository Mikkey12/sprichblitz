from __future__ import annotations

from collections.abc import Callable

from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine
from sqlmodel import Session, select

from sprichblitz_backend.auth import hash_token
from sprichblitz_backend.db.models import ApiToken, User

# ---------------------------------------------------------------------------
# Header-/Token-Validierung (über das geseedete client-Fixture)
# ---------------------------------------------------------------------------


def test_config_endpoint_requires_auth(client: TestClient) -> None:
    res = client.get("/config")
    assert res.status_code == 401
    assert res.json()["code"] == "auth_failed"


def test_config_endpoint_rejects_unknown_token(client: TestClient) -> None:
    res = client.get("/config", headers={"Authorization": "Bearer does-not-exist"})
    assert res.status_code == 401


def test_config_endpoint_rejects_non_bearer(client: TestClient, auth_token: str) -> None:
    res = client.get("/config", headers={"Authorization": f"Token {auth_token}"})
    assert res.status_code == 401


def test_config_endpoint_accepts_valid_token(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    assert client.get("/config", headers=auth_headers).status_code == 200


def test_health_does_not_require_auth(client: TestClient) -> None:
    assert client.get("/health").status_code == 200


# ---------------------------------------------------------------------------
# DB-gestützte Identität: revoked / disabled / zweiter Nutzer
# ---------------------------------------------------------------------------


def test_revoked_token_is_rejected(
    client: TestClient, auth_headers: dict[str, str], db_engine: Engine
) -> None:
    with Session(db_engine) as session:
        token = session.exec(select(ApiToken)).first()
        token.revoked = True
        session.add(token)
        session.commit()
    assert client.get("/config", headers=auth_headers).status_code == 401


def test_disabled_user_is_rejected(
    client: TestClient, auth_headers: dict[str, str], db_engine: Engine
) -> None:
    with Session(db_engine) as session:
        user = session.exec(select(User)).first()
        user.disabled = True
        session.add(user)
        session.commit()
    assert client.get("/config", headers=auth_headers).status_code == 401


def test_second_user_with_own_token_can_full(
    client: TestClient,
    db_engine: Engine,
    make_wav_bytes: Callable[[int, float], bytes],
) -> None:
    second_token = "second-user-token-abcdefghij"
    with Session(db_engine) as session:
        user = User(name="second")
        session.add(user)
        session.commit()
        session.refresh(user)
        session.add(ApiToken(user_id=user.id, token_hash=hash_token(second_token), label="second"))
        session.commit()

    res = client.post(
        "/full",
        headers={"Authorization": f"Bearer {second_token}"},
        files={"file": ("a.wav", make_wav_bytes(16_000, 2.0), "audio/wav")},
        data={"mode": "exact_de"},
    )
    assert res.status_code == 200
