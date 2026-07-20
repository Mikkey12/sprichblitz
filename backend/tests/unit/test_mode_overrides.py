"""/me/modes CRUD + Validierung + Self-Scope (c2)."""

from __future__ import annotations

from sqlmodel import Session

from sprichblitz_backend.auth import hash_token
from sprichblitz_backend.db.models import ApiToken, User


def _add_user(engine, name: str, token: str) -> None:
    with Session(engine) as s:
        user = User(name=name, processing_location="online")
        s.add(user)
        s.commit()
        s.refresh(user)
        s.add(ApiToken(user_id=user.id, token_hash=hash_token(token), label=name))
        s.commit()


def test_put_get_delete_roundtrip(client, auth_headers) -> None:
    res = client.put(
        "/me/modes/mail",
        headers=auth_headers,
        json={
            "display_name": "Mail!",
            "system_prompt": "P",
            "llm_provider": "lm_studio",
            "enabled": True,
        },
    )
    assert res.status_code == 200
    body = res.json()
    assert body["display_name"] == "Mail!"
    assert body["llm_provider"] == "lm_studio"  # effektiv = gewähltes LLM
    assert body["is_overridden"] is True

    modes = {m["mode_key"]: m for m in client.get("/me/modes", headers=auth_headers).json()}
    assert modes["mail"]["display_name"] == "Mail!"
    assert modes["mail"]["is_overridden"] is True
    assert modes["exact_de"]["is_overridden"] is False  # nicht überschrieben

    res = client.delete("/me/modes/mail", headers=auth_headers)
    assert res.status_code == 200
    assert res.json()["is_overridden"] is False
    modes = {m["mode_key"]: m for m in client.get("/me/modes", headers=auth_headers).json()}
    assert modes["mail"]["is_overridden"] is False
    assert modes["mail"]["display_name"] == "Schriftsprachlich"  # Default


def test_put_full_edit_roundtrip(client, auth_headers) -> None:
    # Voll editierbar: STT + LLM + Modell + apply_llm + Prompt round-trippen.
    res = client.put(
        "/me/modes/exact_de",
        headers=auth_headers,
        json={
            "display_name": "1:1",
            "system_prompt": "POLISH",
            "stt_provider": "lm_studio_whisper",
            "llm_provider": "anthropic",
            "llm_model": "claude-x",
            "apply_llm": True,
            "enabled": True,
        },
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["stt_provider"] == "lm_studio_whisper"  # effektiv
    assert body["llm_provider"] == "anthropic"
    assert body["llm_model"] == "claude-x"
    assert body["apply_llm"] is True
    raw = body["override"]
    assert raw["stt_provider"] == "lm_studio_whisper"
    assert raw["llm_model"] == "claude-x"
    assert raw["apply_llm"] is True
    # Defaults bleiben für die Editor-Platzhalter erhalten.
    assert body["default_stt"] == "openai_whisper"
    assert body["default_apply_llm"] is False


def test_modes_expose_raw_override(client, auth_headers) -> None:
    # d2a: /me/modes liefert den ROHEN Override (für den Konsolen-Editor) – distinkt
    # vom effektiven Wert, damit ein Edit den Default nicht einfriert.
    client.put(
        "/me/modes/mail",
        headers=auth_headers,
        json={
            "display_name": "Mail!",
            "system_prompt": None,
            "llm_provider": "lm_studio",
            "enabled": False,
        },
    )
    modes = {m["mode_key"]: m for m in client.get("/me/modes", headers=auth_headers).json()}
    raw = modes["mail"]["override"]
    assert raw == {
        "display_name": "Mail!",
        "system_prompt": None,  # roh None, nicht der effektive Default
        "stt_provider": None,
        "llm_provider": "lm_studio",
        "llm_model": None,
        "apply_llm": None,
        "enabled": False,
    }
    assert modes["exact_de"]["override"] is None  # nicht überschrieben → kein roher Override


def test_put_caps_enforced(client, auth_headers) -> None:
    assert (
        client.put(
            "/me/modes/mail", headers=auth_headers, json={"system_prompt": "x" * 4001}
        ).status_code
        == 422
    )
    assert (
        client.put(
            "/me/modes/mail", headers=auth_headers, json={"display_name": "y" * 81}
        ).status_code
        == 422
    )


def test_put_invalid_llm_provider(client, auth_headers) -> None:
    res = client.put(
        "/me/modes/mail", headers=auth_headers, json={"llm_provider": "does-not-exist"}
    )
    assert res.status_code == 422
    assert res.json()["code"] == "invalid_llm_provider"


def test_put_invalid_stt_provider(client, auth_headers) -> None:
    res = client.put(
        "/me/modes/mail", headers=auth_headers, json={"stt_provider": "does-not-exist"}
    )
    assert res.status_code == 422
    assert res.json()["code"] == "invalid_stt_provider"


def test_put_apply_llm_on_without_prompt_rejected(client, auth_headers) -> None:
    # exact_de hat keinen Default-Prompt: apply_llm=an ohne Prompt → 422 (kein 500 später).
    res = client.put(
        "/me/modes/exact_de",
        headers=auth_headers,
        json={"apply_llm": True, "llm_provider": "anthropic"},
    )
    assert res.status_code == 422
    assert res.json()["code"] == "llm_requires_prompt_and_provider"


def test_put_apply_llm_on_with_prompt_and_llm_ok(client, auth_headers) -> None:
    res = client.put(
        "/me/modes/exact_de",
        headers=auth_headers,
        json={"apply_llm": True, "llm_provider": "anthropic", "system_prompt": "P"},
    )
    assert res.status_code == 200, res.text
    assert res.json()["apply_llm"] is True


def test_unknown_mode_key_404(client, auth_headers) -> None:
    # Config-getrieben: ein nicht konfigurierter Mode-Key wird von _require_mode
    # gegen die Config validiert → 404 (statt Enum-Path-Validator 422).
    res = client.put("/me/modes/bogus", headers=auth_headers, json={})
    assert res.status_code == 404
    assert res.json()["code"] == "mode_not_configured"


def test_me_modes_requires_auth(client) -> None:
    assert client.get("/me/modes").status_code == 401


def test_me_modes_self_scoped(client, db_engine, auth_headers) -> None:
    client.put("/me/modes/mail", headers=auth_headers, json={"display_name": "Mine"})
    _add_user(db_engine, "other2", "o2-tok")
    modes = {
        m["mode_key"]: m
        for m in client.get("/me/modes", headers={"Authorization": "Bearer o2-tok"}).json()
    }
    assert modes["mail"]["is_overridden"] is False
    assert modes["mail"]["display_name"] == "Schriftsprachlich"
