from __future__ import annotations

import io
import wave
from collections.abc import Callable, Iterator
from pathlib import Path

import numpy as np
import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel

from sprichblitz_backend.app import create_app
from sprichblitz_backend.auth import hash_token
from sprichblitz_backend.crypto import KeyVault
from sprichblitz_backend.db.engine import create_db_engine
from sprichblitz_backend.db.models import ApiToken, User
from sprichblitz_backend.models.config_models import (
    AppConfig,
    LLMProviderConfig,
    ModeConfig,
    ServerConfig,
    STTProviderConfig,
)
from sprichblitz_backend.models.domain import CompletionResult, TranscriptionResult
from sprichblitz_backend.providers.base import LLMProvider, STTProvider
from sprichblitz_backend.providers.registry import ProviderRegistry

FIXTURE_DIR = Path(__file__).parent / "fixtures"


def _write_synthetic_wav(path: Path, *, sample_rate: int, duration_s: float = 2.0) -> None:
    """Erzeugt eine synthetische WAV-Datei: 1 s Sinus 440 Hz + 1 s Stille."""
    n = int(sample_rate * duration_s)
    half = n // 2
    t = np.arange(half) / sample_rate
    sine = (0.3 * np.sin(2 * np.pi * 440.0 * t) * 32767).astype(np.int16)
    silence = np.zeros(n - half, dtype=np.int16)
    samples = np.concatenate([sine, silence])

    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        w.writeframes(samples.tobytes())


@pytest.fixture(scope="session", autouse=True)
def _ensure_audio_fixtures() -> None:
    """Schreibt die synthetischen Audio-Fixtures, falls sie fehlen."""
    targets = {
        FIXTURE_DIR / "audio_de_short.wav": 16_000,
        FIXTURE_DIR / "audio_8khz_mono.wav": 8_000,
    }
    for path, rate in targets.items():
        if not path.exists():
            _write_synthetic_wav(path, sample_rate=rate)


@pytest.fixture
def audio_16k_wav() -> bytes:
    return (FIXTURE_DIR / "audio_de_short.wav").read_bytes()


@pytest.fixture
def audio_8k_wav() -> bytes:
    return (FIXTURE_DIR / "audio_8khz_mono.wav").read_bytes()


def _minimal_config() -> AppConfig:
    return AppConfig(
        server=ServerConfig(),
        stt_providers={
            "openai_whisper": STTProviderConfig(
                type="openai_compatible",
                base_url="https://api.openai.com/v1",
                api_key_env="OPENAI_API_KEY",
                model="whisper-1",
            ),
            "lm_studio_whisper": STTProviderConfig(
                type="openai_compatible",
                base_url="http://localhost:1234/v1",
                api_key_env="",
                model="whisper-large-v3-turbo",
            ),
        },
        llm_providers={
            "anthropic": LLMProviderConfig(
                type="anthropic",
                api_key_env="ANTHROPIC_API_KEY",
                default_model="claude-haiku-4-5-20251001",
            ),
            "lm_studio": LLMProviderConfig(
                type="openai_compatible",
                base_url="http://localhost:1234/v1",
                api_key_env="",
                default_model="qwen3.5-9b",
            ),
        },
        modes={
            "exact_de": ModeConfig(
                description="Hochdeutsch wörtlich",
                stt="openai_whisper",
                language="de",
                apply_llm=False,
            ),
            "exact_swiss": ModeConfig(
                description="Schweizerdeutsch (Mundart) → Hochdeutsch",
                stt="lm_studio_whisper",
                language="de",
                prompt_hint="Aufnahme in Mundart.",
                apply_llm=False,
                fallback_stt="openai_whisper",
            ),
            "mail": ModeConfig(
                description="Schriftsprachlich",
                stt="openai_whisper",
                language="de",
                apply_llm=True,
                llm="anthropic",
                system_prompt="Schreibe sauber.",
            ),
        },
    )


# ----------------------------------------------------------------------
# Stub providers used by integration tests so no real HTTP fires.
# ----------------------------------------------------------------------
class StubSTT(STTProvider):
    def __init__(self, name: str, model: str = "stub-whisper", text: str = "stub transcript") -> None:
        self.name = name
        self.model = model
        self._text = text
        self.calls: list[dict[str, object]] = []

    async def transcribe(
        self,
        audio: bytes,
        language: str = "de",
        prompt_hint: str | None = None,
        api_key: str | None = None,
    ) -> TranscriptionResult:
        self.calls.append(
            {"language": language, "prompt_hint": prompt_hint, "audio_len": len(audio), "api_key": api_key}
        )
        return TranscriptionResult(
            text=self._text,
            language=language,
            confidence=None,
            provider=self.name,
            model=self.model,
        )

    async def health_check(self, api_key: str | None = None) -> bool:
        return True


class StubLLM(LLMProvider):
    def __init__(
        self,
        name: str,
        default_model: str = "stub-haiku",
        text: str = "stub completion",
    ) -> None:
        self.name = name
        self.default_model = default_model
        self._text = text
        self.calls: list[dict[str, object]] = []

    async def complete(
        self,
        system: str,
        user: str,
        model: str | None = None,
        max_tokens: int = 1000,
        prefill: str | None = None,
        api_key: str | None = None,
    ) -> CompletionResult:
        self.calls.append(
            {"system": system, "user": user, "model": model, "max_tokens": max_tokens, "prefill": prefill, "api_key": api_key}
        )
        return CompletionResult(
            text=(prefill or "") + self._text,
            provider=self.name,
            model=model or self.default_model,
            input_tokens=10,
            output_tokens=20,
        )

    async def list_models(self, api_key: str | None = None) -> list[str]:
        return [self.default_model]

    async def health_check(self, api_key: str | None = None) -> bool:
        return True


def _stub_registry() -> ProviderRegistry:
    return ProviderRegistry(
        stt={
            "openai_whisper": StubSTT("openai_whisper", text="cloud transcript"),
            "lm_studio_whisper": StubSTT("lm_studio_whisper", text="local transcript"),
        },
        llm={
            "anthropic": StubLLM(
                "anthropic", default_model="claude-haiku-4-5-20251001", text="polished text"
            ),
            "lm_studio": StubLLM("lm_studio", default_model="qwen3.5-9b", text="local llm text"),
        },
    )


@pytest.fixture
def auth_token() -> str:
    return "test-token-1234567890"


@pytest.fixture
def stub_registry() -> ProviderRegistry:
    return _stub_registry()


@pytest.fixture
def db_engine(auth_token: str) -> Engine:
    """In-Memory-SQLite (StaticPool) mit Schema + einem User+Token, dessen
    Klartext ``auth_token`` ist – so bleiben bestehende Integrationstests grün."""
    engine = create_db_engine("sqlite://", poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        # Bewusst online: hält die bestehenden Online-Provider-Assertions stabil.
        # Der local-Pfad + der local-Default werden separat getestet.
        user = User(name="tester", is_admin=True, processing_location="online")
        session.add(user)
        session.commit()
        session.refresh(user)
        session.add(
            ApiToken(user_id=user.id, token_hash=hash_token(auth_token), label="test")
        )
        session.commit()
    return engine


@pytest.fixture
def key_vault() -> KeyVault:
    return KeyVault.from_keys(Fernet.generate_key().decode())


@pytest.fixture
def client(
    auth_token: str,
    stub_registry: ProviderRegistry,
    db_engine: Engine,
    key_vault: KeyVault,
) -> Iterator[TestClient]:
    app = create_app(
        _minimal_config(), registry=stub_registry, db_engine=db_engine, key_vault=key_vault
    )
    with TestClient(app) as c:
        yield c


@pytest.fixture
def tls_client(
    auth_token: str,
    stub_registry: ProviderRegistry,
    db_engine: Engine,
    key_vault: KeyVault,
) -> Iterator[TestClient]:
    """Wie ``client``, aber über https → für TLS-gesperrte Endpunkte
    (``PUT /me/keys``, ``POST /console/session``)."""
    app = create_app(
        _minimal_config(), registry=stub_registry, db_engine=db_engine, key_vault=key_vault
    )
    with TestClient(app, base_url="https://testserver") as c:
        yield c


@pytest.fixture
def auth_headers(auth_token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {auth_token}"}


@pytest.fixture
def make_wav_bytes() -> Callable[[int, float], bytes]:
    def _factory(sample_rate: int = 16_000, duration_s: float = 2.0) -> bytes:
        n = int(sample_rate * duration_s)
        t = np.arange(n) / sample_rate
        samples = (0.2 * np.sin(2 * np.pi * 440.0 * t) * 32767).astype(np.int16)
        buf = io.BytesIO()
        with wave.open(buf, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(sample_rate)
            w.writeframes(samples.tobytes())
        return buf.getvalue()

    return _factory
