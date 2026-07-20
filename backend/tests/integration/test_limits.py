"""Etappe-5-Verdrahtung über die Routen: Rate-Limit (429), Gate (503),
Usage-Buchung (Provider-Error vs. nicht-gebuchte 412)."""

from __future__ import annotations

import asyncio

import httpx
import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from httpx import ASGITransport
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel

from sprichblitz_backend.app import create_app
from sprichblitz_backend.auth import hash_token
from sprichblitz_backend.crypto import KeyVault
from sprichblitz_backend.db.engine import create_db_engine
from sprichblitz_backend.db.models import ApiToken, User
from sprichblitz_backend.models.config_models import (
    AppConfig,
    LimitsConfig,
    LLMProviderConfig,
    LocalProvidersConfig,
    ModeConfig,
    STTProviderConfig,
)
from sprichblitz_backend.providers.registry import ProviderRegistry
from sprichblitz_backend.util.errors import ProviderUnavailable

from ..conftest import StubLLM, StubSTT


def _cfg(**limits) -> AppConfig:
    return AppConfig(
        limits=LimitsConfig(**limits),
        local_providers=LocalProvidersConfig(stt="lm_studio_whisper", llm="lm_studio"),
        stt_providers={
            "openai_whisper": STTProviderConfig(
                type="openai_compatible", base_url="http://x/v1", model="w", key_provider="openai"
            ),
            "lm_studio_whisper": STTProviderConfig(
                type="openai_compatible", base_url="http://x/v1", model="w"
            ),
        },
        llm_providers={
            "lm_studio": LLMProviderConfig(
                type="openai_compatible", base_url="http://x/v1", default_model="q"
            ),
        },
        modes={"exact_de": ModeConfig(description="exact_de", stt="openai_whisper", apply_llm=False)},
    )


def _registry(stt_override: dict | None = None) -> ProviderRegistry:
    stt = {
        "openai_whisper": StubSTT("openai_whisper", text="cloud"),
        "lm_studio_whisper": StubSTT("lm_studio_whisper", text="local"),
    }
    if stt_override:
        stt.update(stt_override)
    reg = ProviderRegistry(stt=stt, llm={"lm_studio": StubLLM("lm_studio", text="x")})
    reg.stt["openai_whisper"].key_provider = "openai"  # Cloud (braucht Key)
    reg.stt["lm_studio_whisper"].key_provider = None  # lokal (gated, kein Key)
    reg.llm["lm_studio"].key_provider = None
    return reg


def _engine():
    eng = create_db_engine("sqlite://", poolclass=StaticPool)
    SQLModel.metadata.create_all(eng)
    return eng


def _add_user(eng, name: str, location: str, token: str) -> None:
    with Session(eng) as s:
        user = User(name=name, processing_location=location)
        s.add(user)
        s.commit()
        s.refresh(user)
        s.add(ApiToken(user_id=user.id, token_hash=hash_token(token), label=name))
        s.commit()


def _vault() -> KeyVault:
    return KeyVault.from_keys(Fernet.generate_key().decode())


def _files(make_wav_bytes):
    return {"file": ("a.wav", make_wav_bytes(16_000, 2.0), "audio/wav")}


def test_rate_limit_returns_429(make_wav_bytes) -> None:
    eng = _engine()
    _add_user(eng, "u", "local", "tok")
    app = create_app(
        _cfg(rate_limit_capacity=1, rate_limit_refill_per_min=0.0),
        registry=_registry(),
        db_engine=eng,
        key_vault=_vault(),
    )
    c = TestClient(app)
    h = {"Authorization": "Bearer tok"}
    assert c.post("/full", headers=h, files=_files(make_wav_bytes), data={"mode": "exact_de"}).status_code == 200
    r2 = c.post("/full", headers=h, files=_files(make_wav_bytes), data={"mode": "exact_de"})
    assert r2.status_code == 429
    assert r2.json()["code"] == "rate_limited"


async def test_gate_returns_503_when_busy(make_wav_bytes) -> None:
    started = asyncio.Event()
    release = asyncio.Event()

    class _BlockingSTT(StubSTT):
        async def transcribe(self, audio, language="de", prompt_hint=None, api_key=None):
            started.set()
            await release.wait()
            return await StubSTT.transcribe(
                self, audio, language=language, prompt_hint=prompt_hint, api_key=api_key
            )

    eng = _engine()
    _add_user(eng, "u", "local", "tok")  # local → exact_de nutzt lm_studio_whisper (gated)
    reg = _registry(stt_override={"lm_studio_whisper": _BlockingSTT("lm_studio_whisper", text="x")})
    app = create_app(
        _cfg(local_concurrency=1, local_acquire_timeout_s=0.15),
        registry=reg,
        db_engine=eng,
        key_vault=_vault(),
    )
    h = {"Authorization": "Bearer tok"}
    async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        first = asyncio.create_task(
            ac.post("/full", headers=h, files=_files(make_wav_bytes), data={"mode": "exact_de"})
        )
        try:
            await asyncio.wait_for(started.wait(), timeout=5.0)
        except TimeoutError:
            first_response = await first
            pytest.fail(
                "Blocking STT was not reached; "
                f"first request returned {first_response.status_code}: {first_response.text}"
            )
        # Erster Request hält jetzt garantiert den einzigen Gate-Slot.
        r2 = await ac.post(
            "/full", headers=h, files=_files(make_wav_bytes), data={"mode": "exact_de"}
        )
        assert r2.status_code == 503
        assert r2.json()["code"] == "backend_busy"
        release.set()
        r1 = await first
        assert r1.status_code == 200
        # Das 503 am Gate wird NICHT als error verbucht – nur der erfolgreiche zählt:
        pm = (await ac.get("/stats", headers=h)).json()["per_mode"]["exact_de"]
        assert pm["requests"] == 1
        assert pm["errors"] == 0


def test_provider_error_booked_as_error(make_wav_bytes) -> None:
    class _FailingSTT(StubSTT):
        async def transcribe(self, audio, language="de", prompt_hint=None, api_key=None):
            raise ProviderUnavailable("down", provider=self.name)

    eng = _engine()
    _add_user(eng, "u", "local", "tok")
    reg = _registry(stt_override={"lm_studio_whisper": _FailingSTT("lm_studio_whisper", text="x")})
    app = create_app(_cfg(), registry=reg, db_engine=eng, key_vault=_vault())
    c = TestClient(app)
    h = {"Authorization": "Bearer tok"}
    r = c.post("/full", headers=h, files=_files(make_wav_bytes), data={"mode": "exact_de"})
    assert r.status_code == 503  # ProviderUnavailable
    stats = c.get("/stats", headers=h).json()["per_mode"]["exact_de"]
    assert stats["errors"] == 1
    assert stats["requests"] == 0


def test_missing_key_412_not_booked(make_wav_bytes) -> None:
    eng = _engine()
    _add_user(eng, "u", "online", "tok")  # online → openai_whisper (key_provider), kein Key
    app = create_app(_cfg(), registry=_registry(), db_engine=eng, key_vault=_vault())
    c = TestClient(app)
    h = {"Authorization": "Bearer tok"}
    r = c.post("/full", headers=h, files=_files(make_wav_bytes), data={"mode": "exact_de"})
    assert r.status_code == 412
    assert r.json()["code"] == "missing_provider_key"
    stats = c.get("/stats", headers=h).json()["per_mode"]["exact_de"]
    assert stats["requests"] == 0
    assert stats["errors"] == 0
