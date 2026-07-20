from __future__ import annotations

import pytest
from cryptography.fernet import Fernet
from sqlalchemy.engine import Engine
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, select

from sprichblitz_backend.crypto import KeyVault
from sprichblitz_backend.db.engine import create_db_engine
from sprichblitz_backend.db.models import ProviderKey, User
from sprichblitz_backend.services import provider_keys
from sprichblitz_backend.util.errors import ProviderKeyUndecryptable


@pytest.fixture
def engine() -> Engine:
    eng = create_db_engine("sqlite://", poolclass=StaticPool)
    SQLModel.metadata.create_all(eng)
    with Session(eng) as session:
        session.add(User(name="u"))
        session.commit()
    return eng


@pytest.fixture
def vault() -> KeyVault:
    return KeyVault.from_keys(Fernet.generate_key().decode())


def _uid(engine: Engine) -> int:
    with Session(engine) as session:
        return session.exec(select(User)).first().id


def test_set_stores_only_ciphertext_and_get_decrypts(engine: Engine, vault: KeyVault) -> None:
    uid = _uid(engine)
    with Session(engine) as s:
        provider_keys.set_user_key(s, vault, uid, "anthropic", "sk-123")
    with Session(engine) as s:
        row = s.exec(select(ProviderKey)).first()
        assert row.ciphertext != "sk-123"  # verschlüsselt gespeichert
        assert provider_keys.get_user_key(s, vault, uid, "anthropic") == "sk-123"
        assert provider_keys.get_user_key(s, vault, uid, "openai") is None


def test_set_is_upsert(engine: Engine, vault: KeyVault) -> None:
    uid = _uid(engine)
    with Session(engine) as s:
        provider_keys.set_user_key(s, vault, uid, "anthropic", "k1")
        provider_keys.set_user_key(s, vault, uid, "anthropic", "k2")
    with Session(engine) as s:
        assert len(s.exec(select(ProviderKey)).all()) == 1
        assert provider_keys.get_user_key(s, vault, uid, "anthropic") == "k2"


def test_presence_and_delete(engine: Engine, vault: KeyVault) -> None:
    uid = _uid(engine)
    with Session(engine) as s:
        provider_keys.set_user_key(s, vault, uid, "openai", "k")
        assert provider_keys.key_presence(s, uid) == {
            "anthropic": False,
            "openai": True,
            "gemini": False,
            "openrouter": False,
        }
        assert provider_keys.delete_user_key(s, uid, "openai") is True
        assert provider_keys.delete_user_key(s, uid, "openai") is False


def test_undecryptable_key_raises(engine: Engine, vault: KeyVault) -> None:
    uid = _uid(engine)
    other = KeyVault.from_keys(Fernet.generate_key().decode())
    with Session(engine) as s:
        s.add(ProviderKey(user_id=uid, provider="anthropic", ciphertext=other.encrypt("x")))
        s.commit()
    with Session(engine) as s:
        with pytest.raises(ProviderKeyUndecryptable):
            provider_keys.get_user_key(s, vault, uid, "anthropic")
