"""§6: processing_location local/online – Provider-Auswahl, Key-Präsenz, Grenze.

local  → alle Modi über WhisperKit + LM Studio (Qwen), ohne jeden Key.
online → Cloud + Per-User-Key; fehlt der Key → 412.
exact_swiss bleibt online für STT auf WhisperKit (Cloud nur Fallback).
local-Modus ist eine harte Grenze: ein Cloud-Override wird abgelehnt.
"""

from __future__ import annotations

from collections.abc import Callable

from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine
from sqlmodel import Session

from sprichblitz_backend.app import create_app
from sprichblitz_backend.auth import hash_token
from sprichblitz_backend.crypto import KeyVault
from sprichblitz_backend.db.models import ApiToken, ProcessingLocation, User
from sprichblitz_backend.models.config_models import (
    AppConfig,
    LLMProviderConfig,
    LocalProvidersConfig,
    ModeConfig,
    STTProviderConfig,
)
from sprichblitz_backend.providers.registry import ProviderRegistry
from sprichblitz_backend.services import provider_keys
from sprichblitz_backend.services.full_pipeline import resolve_mode_for_location

from ..conftest import StubLLM, StubSTT

MODES = ["exact_de", "exact_swiss", "mail", "rage", "emoji"]


def _config() -> AppConfig:
    """5 Modi; Online-Spalte = Mode-Config, Cloud-Provider mit key_provider."""
    return AppConfig(
        local_providers=LocalProvidersConfig(stt="lm_studio_whisper", llm="lm_studio"),
        stt_providers={
            "openai_whisper": STTProviderConfig(
                type="openai_compatible",
                base_url="https://api.openai.com/v1",
                model="whisper-1",
                key_provider="openai",
            ),
            "lm_studio_whisper": STTProviderConfig(
                type="openai_compatible",
                base_url="http://localhost:1234/v1",
                model="whisper-large-v3-turbo",
            ),
        },
        llm_providers={
            "anthropic": LLMProviderConfig(
                type="anthropic",
                default_model="claude-haiku-4-5-20251001",
                key_provider="anthropic",
            ),
            "lm_studio": LLMProviderConfig(
                type="openai_compatible",
                base_url="http://localhost:1234/v1",
                default_model="qwen3.5-9b",
            ),
        },
        modes={
            "exact_de": ModeConfig(description="d", stt="openai_whisper", apply_llm=False),
            "exact_swiss": ModeConfig(
                description="s",
                stt="lm_studio_whisper",  # online STT bleibt WhisperKit
                apply_llm=True,
                llm="anthropic",
                fallback_stt="openai_whisper",
                system_prompt="x",
            ),
            "mail": ModeConfig(
                description="m", stt="openai_whisper", apply_llm=True, llm="anthropic", system_prompt="x"
            ),
            "rage": ModeConfig(
                description="r", stt="openai_whisper", apply_llm=True, llm="anthropic", system_prompt="x"
            ),
            "emoji": ModeConfig(
                description="e", stt="openai_whisper", apply_llm=True, llm="lm_studio", system_prompt="x"
            ),
        },
    )


def _registry() -> ProviderRegistry:
    return ProviderRegistry(
        stt={
            "openai_whisper": StubSTT("openai_whisper", text="cloud-stt"),
            "lm_studio_whisper": StubSTT("lm_studio_whisper", text="local-stt"),
        },
        llm={
            "anthropic": StubLLM("anthropic", text="cloud-llm"),
            "lm_studio": StubLLM("lm_studio", text="local-llm"),
        },
    )


def _client(engine: Engine, vault: KeyVault) -> TestClient:
    app = create_app(_config(), registry=_registry(), db_engine=engine, key_vault=vault)
    return TestClient(app)


def _add_user(engine: Engine, name: str, location: str, token: str) -> int:
    with Session(engine) as s:
        user = User(name=name, processing_location=location)
        s.add(user)
        s.commit()
        s.refresh(user)
        s.add(ApiToken(user_id=user.id, token_hash=hash_token(token), label=name))
        s.commit()
        return user.id


def _post(client: TestClient, token: str, mode: str, wav: bytes, **extra: str):
    return client.post(
        "/full",
        headers={"Authorization": f"Bearer {token}"},
        files={"file": ("a.wav", wav, "audio/wav")},
        data={"mode": mode, **extra},
    )


# ---------------------------------------------------------------------------


def test_new_user_defaults_to_online_for_cloud_quickstart() -> None:
    """Frische Hosts funktionieren ohne optionale lokale Provider."""
    assert User(name="fresh").processing_location == ProcessingLocation.online.value == "online"


def test_local_all_modes_work_without_any_key(
    db_engine: Engine, key_vault: KeyVault, make_wav_bytes: Callable[[int, float], bytes]
) -> None:
    _add_user(db_engine, "loc", "local", "loc-token")
    client = _client(db_engine, key_vault)
    wav = make_wav_bytes(16_000, 2.0)
    for mode in MODES:
        res = _post(client, "loc-token", mode, wav)
        assert res.status_code == 200, f"{mode}: {res.text}"
        body = res.json()
        assert body["stt_provider"] == "lm_studio_whisper"  # WhisperKit lokal
        if body["llm_provider"] is not None:
            assert body["llm_provider"] == "lm_studio"  # Qwen lokal, kein Cloud-LLM


def test_online_missing_key_gets_412(
    db_engine: Engine, key_vault: KeyVault, make_wav_bytes: Callable[[int, float], bytes]
) -> None:
    _add_user(db_engine, "onl", "online", "onl-token")
    client = _client(db_engine, key_vault)
    res = _post(client, "onl-token", "mail", make_wav_bytes(16_000, 2.0))
    assert res.status_code == 412
    assert res.json()["code"] == "missing_provider_key"


def test_exact_swiss_online_uses_whisperkit_for_stt(
    db_engine: Engine, key_vault: KeyVault, make_wav_bytes: Callable[[int, float], bytes]
) -> None:
    uid = _add_user(db_engine, "sw", "online", "sw-token")
    with Session(db_engine) as s:
        provider_keys.set_user_key(s, key_vault, uid, "anthropic", "sk-ant-x")
    client = _client(db_engine, key_vault)
    res = _post(client, "sw-token", "exact_swiss", make_wav_bytes(16_000, 2.0))
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["stt_provider"] == "lm_studio_whisper"  # WhisperKit, NICHT Cloud
    assert body["llm_provider"] == "anthropic"


def test_local_override_to_cloud_is_rejected_not_routed(
    db_engine: Engine, key_vault: KeyVault, make_wav_bytes: Callable[[int, float], bytes]
) -> None:
    _add_user(db_engine, "loc2", "local", "loc2-token")
    client = _client(db_engine, key_vault)
    res = _post(
        client, "loc2-token", "mail", make_wav_bytes(16_000, 2.0), stt="openai_whisper"
    )
    assert res.status_code == 400
    assert res.json()["code"] == "override_not_allowed"


def test_resolve_mode_for_location_local_vs_online() -> None:
    cfg = _config()
    swiss = cfg.modes["exact_swiss"]

    local = resolve_mode_for_location(swiss, "local", cfg.local_providers)
    assert local.stt == "lm_studio_whisper"
    assert local.llm == "lm_studio"
    assert local.fallback_stt is None  # §6 #5

    online = resolve_mode_for_location(swiss, "online", cfg.local_providers)
    assert online.stt == "lm_studio_whisper"  # WhisperKit online
    assert online.llm == "anthropic"
    assert online.fallback_stt == "openai_whisper"


def test_local_clears_online_llm_model() -> None:
    """local erzwingt den lokalen LLM UND wirft ein online-spezifisches
    ``llm_model`` weg – sonst bekäme LM Studio einen fremden Modellnamen."""
    cfg = _config()
    mode = cfg.modes["mail"].model_copy(
        update={"llm": "anthropic", "llm_model": "claude-haiku-4-5"}
    )
    local = resolve_mode_for_location(mode, "local", cfg.local_providers)
    assert local.llm == "lm_studio"
    assert local.llm_model is None

    # online lässt das Modell unangetastet.
    online = resolve_mode_for_location(mode, "online", cfg.local_providers)
    assert online.llm_model == "claude-haiku-4-5"
