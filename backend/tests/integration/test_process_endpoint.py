from __future__ import annotations

from fastapi.testclient import TestClient
from sqlmodel import Session, select

from sprichblitz_backend.db.models import User
from sprichblitz_backend.services import mode_overrides


def _override(db_engine, mode_key: str, **fields) -> None:
    with Session(db_engine) as session:
        user_id = session.exec(select(User).where(User.name == "tester")).one().id
        mode_overrides.upsert_override(session, user_id, mode_key, **fields)


def test_process_returns_polished_text(client: TestClient, auth_headers: dict[str, str]) -> None:
    res = client.post(
        "/process",
        headers=auth_headers,
        json={"mode": "mail", "text": "hallo alex, melde mich bald"},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["mode"] == "mail"
    assert body["text"] == "polished text"
    assert body["llm_provider"] == "anthropic"


def test_process_rejects_non_llm_mode(client: TestClient, auth_headers: dict[str, str]) -> None:
    res = client.post(
        "/process",
        headers=auth_headers,
        json={"mode": "exact_de", "text": "egal"},
    )
    assert res.status_code == 400
    assert res.json()["code"] == "mode_not_configured"


def test_process_rejects_empty_text(client: TestClient, auth_headers: dict[str, str]) -> None:
    res = client.post(
        "/process",
        headers=auth_headers,
        json={"mode": "mail", "text": ""},
    )
    assert res.status_code == 422


def test_process_llm_model_override_is_applied(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    res = client.post(
        "/process",
        headers=auth_headers,
        json={"mode": "mail", "text": "hi", "llm_model": "claude-opus-4-7"},
    )
    assert res.status_code == 200, res.text
    assert res.json()["llm_model"] == "claude-opus-4-7"


def test_process_rejects_unknown_llm_override(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    res = client.post(
        "/process",
        headers=auth_headers,
        json={"mode": "mail", "text": "hi", "llm": "does_not_exist"},
    )
    assert res.status_code == 400
    assert res.json()["code"] == "override_not_allowed"


def test_process_rejects_mode_disabled_for_llm_by_user(
    client: TestClient, db_engine, auth_headers: dict[str, str]
) -> None:
    _override(db_engine, "mail", apply_llm=False, enabled=True)

    res = client.post(
        "/process",
        headers=auth_headers,
        json={"mode": "mail", "text": "roh lassen"},
    )

    assert res.status_code == 400
    assert res.json()["code"] == "mode_not_configured"


def test_process_accepts_mode_enabled_for_llm_by_user(
    client: TestClient, db_engine, auth_headers: dict[str, str]
) -> None:
    _override(
        db_engine,
        "exact_de",
        apply_llm=True,
        llm_provider="anthropic",
        system_prompt="POLISH",
        enabled=True,
    )

    res = client.post(
        "/process",
        headers=auth_headers,
        json={"mode": "exact_de", "text": "bitte bearbeiten"},
    )

    assert res.status_code == 200, res.text
    assert res.json()["llm_provider"] == "anthropic"


def test_process_reports_effective_llm_misconfiguration(
    client: TestClient, db_engine, auth_headers: dict[str, str]
) -> None:
    _override(
        db_engine,
        "exact_de",
        apply_llm=True,
        llm_provider="anthropic",
        enabled=True,
    )

    res = client.post(
        "/process",
        headers=auth_headers,
        json={"mode": "exact_de", "text": "bitte bearbeiten"},
    )

    assert res.status_code == 409
    assert res.json()["code"] == "mode_misconfigured"
