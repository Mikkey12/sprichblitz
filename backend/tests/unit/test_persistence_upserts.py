"""Happen 05: race-sichere Upserts (kein 500 bei Doppel-Schreiben) + Orphan-
Bereinigung verwaister mode_overrides beim Modus-Löschen.

Die Atomarität (ON CONFLICT) wird per Konstruktion erreicht; hier verifiziert:
zweimaliges Schreiben desselben Schlüssels ergibt EINE aktualisierte Zeile
(statt Unique-Constraint-Verletzung), und delete_all_for_mode räumt auf.
"""

from __future__ import annotations

import pytest
from cryptography.fernet import Fernet
from sqlalchemy.engine import Engine
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, select

from sprichblitz_backend.crypto import KeyVault
from sprichblitz_backend.db.engine import create_db_engine
from sprichblitz_backend.db.models import ModeDefinition, ModeOverride, ProviderKey, User
from sprichblitz_backend.services import mode_definitions, mode_overrides, provider_keys


@pytest.fixture
def engine() -> Engine:
    eng = create_db_engine("sqlite://", poolclass=StaticPool)
    SQLModel.metadata.create_all(eng)
    with Session(eng) as s:
        s.add(User(name="u"))
        s.commit()
    return eng


def _uid(engine: Engine) -> int:
    with Session(engine) as s:
        return s.exec(select(User)).first().id


def test_set_user_key_twice_updates_single_row(engine: Engine) -> None:
    vault = KeyVault.from_keys(Fernet.generate_key().decode())
    uid = _uid(engine)
    with Session(engine) as s:
        provider_keys.set_user_key(s, vault, uid, "anthropic", "sk-1")
        provider_keys.set_user_key(s, vault, uid, "anthropic", "sk-2")  # kein 500
    with Session(engine) as s:
        rows = s.exec(
            select(ProviderKey).where(ProviderKey.user_id == uid, ProviderKey.provider == "anthropic")
        ).all()
        assert len(rows) == 1
        assert vault.decrypt(rows[0].ciphertext) == "sk-2"


def test_upsert_override_twice_updates_single_row(engine: Engine) -> None:
    uid = _uid(engine)
    with Session(engine) as s:
        mode_overrides.upsert_override(s, uid, "mail", display_name="A")
        out = mode_overrides.upsert_override(s, uid, "mail", display_name="B")  # kein 500
        assert out.display_name == "B"
    with Session(engine) as s:
        rows = s.exec(select(ModeOverride).where(ModeOverride.user_id == uid)).all()
        assert len(rows) == 1
        assert rows[0].display_name == "B"


def test_upsert_definition_twice_preserves_enabled_default(engine: Engine) -> None:
    with Session(engine) as s:
        mode_definitions.upsert_definition(s, "custom", description="d", stt="openai_whisper")
        out = mode_definitions.upsert_definition(s, "custom", description="d2")  # kein 500
        assert out.description == "d2"
        assert out.enabled is True  # Default beim Anlegen erhalten
    with Session(engine) as s:
        rows = s.exec(select(ModeDefinition).where(ModeDefinition.mode_key == "custom")).all()
        assert len(rows) == 1


def test_delete_all_for_mode_removes_orphans(engine: Engine) -> None:
    uid = _uid(engine)
    with Session(engine) as s:
        mode_overrides.upsert_override(s, uid, "custom", display_name="X")
        assert mode_overrides.get_override(s, uid, "custom") is not None
        n = mode_overrides.delete_all_for_mode(s, "custom")
        assert n == 1
        assert mode_overrides.get_override(s, uid, "custom") is None
