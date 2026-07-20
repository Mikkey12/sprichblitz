"""/config liefert effektive (override-gemergte) Modi – additiv & self-scoped (c1)."""

from __future__ import annotations

from sqlmodel import Session, select

from sprichblitz_backend.auth import hash_token
from sprichblitz_backend.db.models import ApiToken, User
from sprichblitz_backend.services import mode_overrides


def _uid(engine) -> int:
    with Session(engine) as s:
        return s.exec(select(User).where(User.name == "tester")).first().id


def _add_user(engine, name: str, token: str) -> None:
    with Session(engine) as s:
        user = User(name=name, processing_location="online")
        s.add(user)
        s.commit()
        s.refresh(user)
        s.add(ApiToken(user_id=user.id, token_hash=hash_token(token), label=name))
        s.commit()


def test_config_reflects_override_additively(client, db_engine, auth_headers) -> None:
    with Session(db_engine) as s:
        mode_overrides.upsert_override(
            s,
            _uid(db_engine),
            "mail",
            display_name="Mein Mail",
            system_prompt="X",
            llm_provider="lm_studio",
            enabled=False,
        )
    body = client.get("/config", headers=auth_headers).json()
    modes = {m["name"]: m for m in body["modes"]}
    mail = modes["mail"]
    # Additiv: bestehende Felder bleiben der statische Default (Alt-Client).
    assert mail["description"] == "Schriftsprachlich"
    assert mail["llm_provider"] == "anthropic"  # NICHT die preferred/auflösung
    # Etappe-4-Felder: effektiv.
    assert mail["display_name"] == "Mein Mail"
    assert mail["enabled"] is False
    assert mail["preferred_online_llm"] == "lm_studio"
    # ProviderInfo.local: lokaler Provider (kein key_provider) = True.
    providers = {p["name"]: p for p in body["stt_providers"] + body["llm_providers"]}
    assert providers["lm_studio"]["local"] is True
    assert "local" in providers["anthropic"]


def test_config_is_self_scoped(client, db_engine, auth_headers) -> None:
    with Session(db_engine) as s:
        mode_overrides.upsert_override(
            s,
            _uid(db_engine),
            "mail",
            display_name="Mein Mail",
            system_prompt=None,
            llm_provider=None,
            enabled=True,
        )
    _add_user(db_engine, "other", "other-tok")
    modes = {
        m["name"]: m
        for m in client.get("/config", headers={"Authorization": "Bearer other-tok"}).json()[
            "modes"
        ]
    }
    # Anderer Nutzer sieht den Default, nicht den Override des testers.
    assert modes["mail"]["display_name"] == "Schriftsprachlich"
