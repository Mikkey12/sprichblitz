from __future__ import annotations

import pytest
from sqlalchemy.engine import Engine
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, select

from sprichblitz_backend import admin
from sprichblitz_backend.auth import hash_token
from sprichblitz_backend.db.engine import create_db_engine
from sprichblitz_backend.db.models import ApiToken, User


@pytest.fixture
def engine() -> Engine:
    eng = create_db_engine("sqlite://", poolclass=StaticPool)
    SQLModel.metadata.create_all(eng)
    return eng


def test_create_user_then_issue_token_stores_only_hash(engine: Engine) -> None:
    with Session(engine) as s:
        user = admin.create_user(s, "alice", is_admin=True, location="online")
        assert user.id is not None
        assert user.is_admin is True
        assert user.processing_location == "online"

    with Session(engine) as s:
        plaintext = admin.issue_token(s, "alice", label="win-client")
    assert len(plaintext) > 20

    with Session(engine) as s:
        token = s.exec(select(ApiToken)).first()
        assert token.token_hash == hash_token(plaintext)
        assert token.token_hash != plaintext  # Klartext nie gespeichert
        assert token.label == "win-client"


def test_create_user_duplicate_raises(engine: Engine) -> None:
    with Session(engine) as s:
        user = admin.create_user(s, "bob")
        assert user.processing_location == "online"
        with pytest.raises(ValueError):
            admin.create_user(s, "bob")


def test_issue_token_unknown_user_raises(engine: Engine) -> None:
    with Session(engine) as s:
        with pytest.raises(ValueError):
            admin.issue_token(s, "ghost")


def test_revoke_and_disable(engine: Engine) -> None:
    with Session(engine) as s:
        admin.create_user(s, "carol")
        admin.issue_token(s, "carol")
        token = s.exec(select(ApiToken)).first()

        assert admin.revoke_token(s, token.id) is True
        assert s.get(ApiToken, token.id).revoked is True
        assert admin.revoke_token(s, 9999) is False

        assert admin.disable_user(s, "carol") is True
        assert s.exec(select(User).where(User.name == "carol")).first().disabled is True
        assert admin.disable_user(s, "nope") is False


def test_migrate_single_user_is_idempotent(engine: Engine) -> None:
    token = "env-token-1234567890"

    with Session(engine) as s:
        user1, created1 = admin.migrate_single_user(s, token=token)
        assert created1 is True
        assert user1.is_admin is True
        assert user1.name == "admin"
        assert user1.processing_location == "online"

    with Session(engine) as s:
        _user2, created2 = admin.migrate_single_user(s, token=token)
        assert created2 is False

    # Genau ein Nutzer, ein Token – kein Doppel-Anlegen.
    with Session(engine) as s:
        assert len(s.exec(select(User)).all()) == 1
        tokens = s.exec(select(ApiToken)).all()
        assert len(tokens) == 1
        assert tokens[0].token_hash == hash_token(token)


def test_migrate_single_user_accepts_explicit_local_location(engine: Engine) -> None:
    with Session(engine) as s:
        user, created = admin.migrate_single_user(
            s,
            token="local-token-1234567890",
            location="local",
        )
        assert created is True
        assert user.processing_location == "local"


def test_cli_location_defaults_are_online() -> None:
    create = admin._build_parser().parse_args(["create-user", "--name", "fresh"])
    migrate = admin._build_parser().parse_args(["migrate-single-user"])
    assert create.location == "online"
    assert migrate.location == "online"
