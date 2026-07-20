"""E2E-Beleg: Modi sind VOLL config-getrieben (kein Enum-Gate mehr).

Ein Modus, der in KEINEM Enum existiert und nur als config-Block vorliegt
(``custom_note``), muss end-to-end funktionieren:
- ``POST /full`` liefert 200 und echot den Modus,
- ``GET /me/modes`` listet ihn,
- ``GET /stats`` zählt ihn.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine

from sprichblitz_backend.app import create_app
from sprichblitz_backend.crypto import KeyVault
from sprichblitz_backend.models.config_models import (
    AppConfig,
    LLMProviderConfig,
    ModeConfig,
    ServerConfig,
    STTProviderConfig,
)
from sprichblitz_backend.providers.registry import ProviderRegistry

_NOVEL_MODE = "custom_note"


def _config_with_novel_mode() -> AppConfig:
    """Config mit einem Modus, den es in keinem (früheren) Enum gab."""
    return AppConfig(
        server=ServerConfig(),
        stt_providers={
            "openai_whisper": STTProviderConfig(
                type="openai_compatible",
                base_url="https://api.openai.com/v1",
                api_key_env="OPENAI_API_KEY",
                model="whisper-1",
            ),
        },
        llm_providers={
            "anthropic": LLMProviderConfig(
                type="anthropic",
                api_key_env="ANTHROPIC_API_KEY",
                default_model="claude-haiku-4-5-20251001",
            ),
        },
        modes={
            _NOVEL_MODE: ModeConfig(
                description="Reiner Config-Modus (kein Enum)",
                stt="openai_whisper",
                language="de",
                apply_llm=True,
                llm="anthropic",
                system_prompt="Formatiere den Text als kurze Notiz.",
            ),
        },
    )


@pytest.fixture
def novel_client(
    stub_registry: ProviderRegistry,
    db_engine: Engine,
    key_vault: KeyVault,
) -> Iterator[TestClient]:
    app = create_app(
        _config_with_novel_mode(),
        registry=stub_registry,
        db_engine=db_engine,
        key_vault=key_vault,
    )
    with TestClient(app) as c:
        yield c


def test_novel_config_mode_runs_full(
    novel_client: TestClient, audio_16k_wav: bytes, auth_headers: dict[str, str]
) -> None:
    res = novel_client.post(
        "/full",
        headers=auth_headers,
        files={"file": ("h.wav", audio_16k_wav, "audio/wav")},
        data={"mode": _NOVEL_MODE},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["mode"] == _NOVEL_MODE
    assert body["llm_provider"] == "anthropic"
    assert body["final_text"]  # Stub-LLM liefert Text → LLM-Stufe lief


def test_novel_config_mode_appears_in_me_modes(
    novel_client: TestClient, auth_headers: dict[str, str]
) -> None:
    res = novel_client.get("/me/modes", headers=auth_headers)
    assert res.status_code == 200, res.text
    keys = {m["mode_key"] for m in res.json()}
    assert _NOVEL_MODE in keys


def test_novel_config_mode_appears_in_stats(
    novel_client: TestClient, audio_16k_wav: bytes, auth_headers: dict[str, str]
) -> None:
    # Erst einen Durchlauf buchen, dann muss der Modus im Aggregat stehen.
    novel_client.post(
        "/full",
        headers=auth_headers,
        files={"file": ("h.wav", audio_16k_wav, "audio/wav")},
        data={"mode": _NOVEL_MODE},
    )
    res = novel_client.get("/stats", headers=auth_headers)
    assert res.status_code == 200, res.text
    per_mode = res.json()["per_mode"]
    assert _NOVEL_MODE in per_mode
    assert per_mode[_NOVEL_MODE]["requests"] >= 1
