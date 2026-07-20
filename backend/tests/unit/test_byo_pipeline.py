"""End-to-end BYO-Key-Verhalten über /full.

Config: ``mail`` = STT ``openai_whisper`` (kein Key nötig) + LLM ``anthropic``
(``key_provider=anthropic``). So isoliert der Test die LLM-Key-Logik.
"""

from __future__ import annotations

from collections.abc import Callable

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from loguru import logger
from sqlalchemy.engine import Engine
from sqlmodel import Session, select

from sprichblitz_backend.app import create_app
from sprichblitz_backend.crypto import KeyVault, VaultConfigError
from sprichblitz_backend.db.models import ProviderKey, User
from sprichblitz_backend.models.config_models import (
    AppConfig,
    LLMProviderConfig,
    ModeConfig,
    STTProviderConfig,
)
from sprichblitz_backend.models.domain import CompletionResult
from sprichblitz_backend.providers.registry import ProviderRegistry
from sprichblitz_backend.services import provider_keys
from sprichblitz_backend.util.errors import ProviderAuthError

from ..conftest import StubLLM, StubSTT, _minimal_config


def _byo_config() -> AppConfig:
    return AppConfig(
        stt_providers={
            "openai_whisper": STTProviderConfig(
                type="openai_compatible",
                base_url="https://api.openai.com/v1",
                model="whisper-1",
                # key_provider None → STT braucht keinen Key (Test isoliert LLM-Key)
            )
        },
        llm_providers={
            "anthropic": LLMProviderConfig(
                type="anthropic",
                default_model="claude-haiku-4-5-20251001",
                key_provider="anthropic",
            )
        },
        modes={
            "mail": ModeConfig(
                description="mail",
                stt="openai_whisper",
                apply_llm=True,
                llm="anthropic",
                system_prompt="Schreibe sauber.",
            )
        },
    )


def _build_client(
    db_engine: Engine, key_vault: KeyVault, llm: StubLLM
) -> TestClient:
    registry = ProviderRegistry(
        stt={"openai_whisper": StubSTT("openai_whisper", text="roh")},
        llm={"anthropic": llm},
    )
    app = create_app(_byo_config(), registry=registry, db_engine=db_engine, key_vault=key_vault)
    return TestClient(app)


def _uid(engine: Engine) -> int:
    with Session(engine) as s:
        return s.exec(select(User)).first().id


def _post_mail(client: TestClient, auth_headers: dict[str, str], wav: bytes):
    return client.post(
        "/full",
        headers=auth_headers,
        files={"file": ("a.wav", wav, "audio/wav")},
        data={"mode": "mail"},
    )


class _RejectingLLM(StubLLM):
    async def complete(
        self,
        system: str,
        user: str,
        model: str | None = None,
        max_tokens: int = 1000,
        prefill: str | None = None,
        api_key: str | None = None,
    ) -> CompletionResult:
        raise ProviderAuthError("Key abgelehnt", provider=self.name)


def test_user_with_key_gets_200_and_key_reaches_provider(
    db_engine: Engine,
    key_vault: KeyVault,
    auth_headers: dict[str, str],
    make_wav_bytes: Callable[[int, float], bytes],
) -> None:
    llm = StubLLM("anthropic", default_model="claude-haiku-4-5-20251001", text="poliert")
    client = _build_client(db_engine, key_vault, llm)
    secret = "sk-ant-USERKEY"
    with Session(db_engine) as s:
        provider_keys.set_user_key(s, key_vault, _uid(db_engine), "anthropic", secret)

    res = _post_mail(client, auth_headers, make_wav_bytes(16_000, 2.0))
    assert res.status_code == 200
    assert llm.calls[-1]["api_key"] == secret  # Per-User-Key kam an
    assert secret not in res.text


def test_user_without_key_gets_412(
    db_engine: Engine,
    key_vault: KeyVault,
    auth_headers: dict[str, str],
    make_wav_bytes: Callable[[int, float], bytes],
) -> None:
    llm = StubLLM("anthropic", default_model="claude-haiku-4-5-20251001")
    client = _build_client(db_engine, key_vault, llm)
    res = _post_mail(client, auth_headers, make_wav_bytes(16_000, 2.0))
    assert res.status_code == 412
    assert res.json()["code"] == "missing_provider_key"
    assert llm.calls == []  # Provider nie aufgerufen


def test_never_falls_back_to_shared_env_key(
    db_engine: Engine,
    key_vault: KeyVault,
    auth_headers: dict[str, str],
    make_wav_bytes: Callable[[int, float], bytes],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Geteilter Env-Key vorhanden – darf NICHT genutzt werden, wenn der Nutzer
    # keinen eigenen Key hat.
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-ENV-must-not-be-used")
    llm = StubLLM("anthropic", default_model="claude-haiku-4-5-20251001")
    client = _build_client(db_engine, key_vault, llm)
    res = _post_mail(client, auth_headers, make_wav_bytes(16_000, 2.0))
    assert res.status_code == 412
    assert llm.calls == []


def test_provider_rejected_key_gets_422(
    db_engine: Engine,
    key_vault: KeyVault,
    auth_headers: dict[str, str],
    make_wav_bytes: Callable[[int, float], bytes],
) -> None:
    client = _build_client(db_engine, key_vault, _RejectingLLM("anthropic"))
    with Session(db_engine) as s:
        provider_keys.set_user_key(s, key_vault, _uid(db_engine), "anthropic", "sk-ant-x")
    res = _post_mail(client, auth_headers, make_wav_bytes(16_000, 2.0))
    assert res.status_code == 422
    assert res.json()["code"] == "provider_key_rejected"


def test_undecryptable_key_gets_422(
    db_engine: Engine,
    key_vault: KeyVault,
    auth_headers: dict[str, str],
    make_wav_bytes: Callable[[int, float], bytes],
) -> None:
    llm = StubLLM("anthropic", default_model="claude-haiku-4-5-20251001")
    client = _build_client(db_engine, key_vault, llm)
    other = KeyVault.from_keys(Fernet.generate_key().decode())
    with Session(db_engine) as s:
        s.add(
            ProviderKey(
                user_id=_uid(db_engine), provider="anthropic", ciphertext=other.encrypt("sk")
            )
        )
        s.commit()
    res = _post_mail(client, auth_headers, make_wav_bytes(16_000, 2.0))
    assert res.status_code == 422
    assert res.json()["code"] == "provider_key_undecryptable"
    assert llm.calls == []


def _assert_secret_absent(secret: str, logs: list[str], response_text: str) -> None:
    assert secret not in response_text
    assert all(secret not in str(message) for message in logs)


def test_key_never_in_response_or_logs_success_path(
    db_engine: Engine,
    key_vault: KeyVault,
    auth_headers: dict[str, str],
    make_wav_bytes: Callable[[int, float], bytes],
) -> None:
    secret = "sk-ant-LEAKCHECK-SUCCESS"
    llm = StubLLM("anthropic", default_model="claude-haiku-4-5-20251001", text="ok")
    client = _build_client(db_engine, key_vault, llm)
    with Session(db_engine) as s:
        provider_keys.set_user_key(s, key_vault, _uid(db_engine), "anthropic", secret)

    captured: list[str] = []
    sink_id = logger.add(captured.append, level="DEBUG")
    try:
        res = _post_mail(client, auth_headers, make_wav_bytes(16_000, 2.0))
    finally:
        logger.remove(sink_id)
    assert res.status_code == 200
    _assert_secret_absent(secret, captured, res.text)


def test_key_never_in_response_or_logs_error_path(
    db_engine: Engine,
    key_vault: KeyVault,
    auth_headers: dict[str, str],
    make_wav_bytes: Callable[[int, float], bytes],
) -> None:
    secret = "sk-ant-LEAKCHECK-ERROR"
    client = _build_client(db_engine, key_vault, _RejectingLLM("anthropic"))
    with Session(db_engine) as s:
        provider_keys.set_user_key(s, key_vault, _uid(db_engine), "anthropic", secret)

    captured: list[str] = []
    sink_id = logger.add(captured.append, level="DEBUG")
    try:
        res = _post_mail(client, auth_headers, make_wav_bytes(16_000, 2.0))
    finally:
        logger.remove(sink_id)
    assert res.status_code == 422
    _assert_secret_absent(secret, captured, res.text)


def test_create_app_without_secret_key_is_fail_closed(
    db_engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("SPRICHBLITZ_SECRET_KEY", raising=False)
    with pytest.raises(VaultConfigError):
        # Kein key_vault übergeben → KeyVault.from_env() → fail-closed.
        create_app(_minimal_config(), db_engine=db_engine)
