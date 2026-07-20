from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from sprichblitz_backend.app import create_app
from sprichblitz_backend.models.domain import TranscriptionResult
from sprichblitz_backend.providers.base import STTProvider
from sprichblitz_backend.providers.registry import ProviderRegistry
from sprichblitz_backend.util.errors import ProviderUnavailable

from ..conftest import StubLLM, StubSTT, _minimal_config


class FailingSTT(STTProvider):
    """STT, der reproduzierbar mit ProviderUnavailable fehlschlägt – so wie der
    @with_retry-Decorator es nach 3 5xx-Versuchen weiterreicht."""

    def __init__(self, name: str = "lm_studio_whisper") -> None:
        self.name = name
        self.model = "stub"
        self.calls = 0

    async def transcribe(
        self,
        audio: bytes,
        language: str = "de",
        prompt_hint: str | None = None,
        api_key: str | None = None,
    ) -> TranscriptionResult:
        self.calls += 1
        raise ProviderUnavailable("Connection error: ConnectError", provider=self.name)

    async def health_check(self) -> bool:
        return False


@pytest.fixture
def fallback_client(db_engine, key_vault):
    failing = FailingSTT(name="lm_studio_whisper")
    cloud = StubSTT("openai_whisper", text="cloud fallback transcript")
    registry = ProviderRegistry(
        stt={
            "lm_studio_whisper": failing,
            "openai_whisper": cloud,
        },
        llm={"anthropic": StubLLM("anthropic")},
    )
    app = create_app(_minimal_config(), registry=registry, db_engine=db_engine, key_vault=key_vault)
    with TestClient(app) as c:
        yield c, failing, cloud


def test_exact_swiss_falls_back_to_openai_when_local_unavailable(
    fallback_client, audio_16k_wav: bytes, auth_headers: dict[str, str]
) -> None:
    client, failing, cloud = fallback_client
    res = client.post(
        "/transcribe",
        headers=auth_headers,
        files={"file": ("a.wav", audio_16k_wav, "audio/wav")},
        data={"mode": "exact_swiss"},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["used_fallback"] is True
    assert body["stt_provider"] == "openai_whisper"
    assert body["text"] == "cloud fallback transcript"
    assert failing.calls == 1
    # Cloud-Whisper wurde mit dem Mundart-Hint gerufen:
    assert cloud.calls[-1]["prompt_hint"] == "Aufnahme in Mundart."


def test_exact_de_does_not_use_fallback(
    client: TestClient, audio_16k_wav: bytes, auth_headers: dict[str, str]
) -> None:
    res = client.post(
        "/transcribe",
        headers=auth_headers,
        files={"file": ("a.wav", audio_16k_wav, "audio/wav")},
        data={"mode": "exact_de"},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["used_fallback"] is False
    assert body["stt_provider"] == "openai_whisper"
