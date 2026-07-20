"""admin set-key: Key verschlüsselt im Vault ablegen; unbekannter User → Fehler."""

from __future__ import annotations

import pytest
from cryptography.fernet import Fernet
from sqlalchemy.engine import Engine
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, select

from sprichblitz_backend import admin
from sprichblitz_backend.crypto import KeyVault
from sprichblitz_backend.db.engine import create_db_engine
from sprichblitz_backend.db.models import User
from sprichblitz_backend.services import provider_keys


@pytest.fixture
def engine() -> Engine:
    eng = create_db_engine("sqlite://", poolclass=StaticPool)
    SQLModel.metadata.create_all(eng)
    return eng


def test_set_key_stores_encrypted_and_recoverable(engine: Engine) -> None:
    vault = KeyVault.from_keys(Fernet.generate_key().decode())
    with Session(engine) as s:
        admin.create_user(s, "alice")
        admin.set_key(s, vault, "alice", "anthropic", "sk-secret")

    with Session(engine) as s:
        uid = s.exec(select(User).where(User.name == "alice")).first().id
        assert provider_keys.get_user_key(s, vault, uid, "anthropic") == "sk-secret"


def test_set_key_unknown_user_raises(engine: Engine) -> None:
    vault = KeyVault.from_keys(Fernet.generate_key().decode())
    with Session(engine) as s:
        with pytest.raises(ValueError):
            admin.set_key(s, vault, "ghost", "anthropic", "k")
