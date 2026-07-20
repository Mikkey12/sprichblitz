from __future__ import annotations

import pytest
import respx
from httpx import Response

from sprichblitz_backend.providers.stt.openai_whisper import OpenAIWhisperProvider
from sprichblitz_backend.util.errors import (
    ProviderEmptyResult,
    ProviderInvalidResponse,
    ProviderUnavailable,
)


@respx.mock
async def test_openai_whisper_returns_text(audio_16k_wav: bytes) -> None:
    route = respx.post("https://api.openai.com/v1/audio/transcriptions").mock(
        return_value=Response(200, json={"text": "Hallo Welt"})
    )

    provider = OpenAIWhisperProvider(
        name="openai_whisper",
        base_url="https://api.openai.com/v1",
        api_key_env="OPENAI_API_KEY",
        model="whisper-1",
    )
    result = await provider.transcribe(audio_16k_wav, language="de", api_key="test-key")

    assert result.text == "Hallo Welt"
    assert result.provider == "openai_whisper"
    assert result.model == "whisper-1"
    assert route.called

    # Verify Bearer + multipart fields reached the server:
    sent = route.calls.last.request
    assert sent.headers["authorization"] == "Bearer test-key"
    body = sent.content
    assert b"whisper-1" in body
    assert b'name="language"' in body and b"\r\nde\r\n" in body


@respx.mock
async def test_no_auth_header_for_local_provider_without_key() -> None:
    """Lokale Provider (WhisperKit, LM Studio) laufen OHNE Key – dann darf auch
    kein ``Authorization``-Header rausgehen.

    Seit die STT-Dispatch type-basiert laeuft, bedient genau diese Klasse auch die
    lokalen ``openai_compatible``-Endpunkte (Config-Provider ``lm_studio_whisper``
    mit ``api_key_env: ""``). Ein versehentlich mitgeschickter leerer Bearer waere
    bestenfalls Muell, schlimmstenfalls ein 401 gegen den eigenen Daemon.
    """
    route = respx.post("http://localhost:8080/v1/audio/transcriptions").mock(
        return_value=Response(200, json={"text": "Grüezi"})
    )
    provider = OpenAIWhisperProvider(
        name="lm_studio_whisper",
        base_url="http://localhost:8080/v1",
        api_key_env="",
        model="whisper-large-v3-turbo",
    )
    result = await provider.transcribe(b"\x00\x00", language="de")

    assert result.text == "Grüezi"
    assert "authorization" not in {k.lower() for k in route.calls.last.request.headers}


@respx.mock
async def test_openai_whisper_passes_prompt_hint(audio_16k_wav: bytes) -> None:
    route = respx.post("https://api.openai.com/v1/audio/transcriptions").mock(
        return_value=Response(200, json={"text": "x"})
    )
    provider = OpenAIWhisperProvider(
        name="openai_whisper",
        base_url="https://api.openai.com/v1",
        api_key_env="OPENAI_API_KEY",
        model="whisper-1",
    )
    await provider.transcribe(b"\x00", language="de", prompt_hint="Mundart-Aufnahme")

    body = route.calls.last.request.content
    assert b"Mundart-Aufnahme" in body


@respx.mock
async def test_missing_text_surfaces_as_empty_result() -> None:
    """Eine 200-Antwort OHNE ``text`` (Provider-Fehlverhalten) muss als
    ProviderEmptyResult herauskommen, damit transcribe_for_mode auf fallback_stt
    umschaltet. ProviderEmptyResult ist Subklasse von ProviderInvalidResponse →
    Client-Code (``provider_invalid_response``) unverändert."""
    respx.post("https://api.openai.com/v1/audio/transcriptions").mock(
        return_value=Response(200, json={"language": "de"})  # kein "text"
    )
    provider = OpenAIWhisperProvider(
        name="openai_whisper",
        base_url="https://api.openai.com/v1",
        api_key_env="OPENAI_API_KEY",
        model="whisper-1",
    )
    with pytest.raises(ProviderEmptyResult) as exc:
        await provider.transcribe(b"\x00", language="de", api_key="k")
    assert isinstance(exc.value, ProviderInvalidResponse)
    assert exc.value.code == "provider_invalid_response"


@respx.mock
async def test_malformed_success_json_maps_to_invalid_response() -> None:
    respx.post("https://api.openai.com/v1/audio/transcriptions").mock(
        return_value=Response(200, text="not-json")
    )
    provider = OpenAIWhisperProvider(
        name="openai_whisper",
        base_url="https://api.openai.com/v1",
        api_key_env="OPENAI_API_KEY",
        model="whisper-1",
    )
    with pytest.raises(ProviderInvalidResponse, match="invalid JSON"):
        await provider.transcribe(b"\x00", language="de", api_key="k")


@respx.mock
async def test_whisperkit_uses_explicit_root_health_path() -> None:
    route = respx.get("http://localhost:8080/health").mock(return_value=Response(200))
    provider = OpenAIWhisperProvider(
        name="whisperkit",
        base_url="http://localhost:8080/v1",
        api_key_env="",
        model="local-model",
        health_path="/health",
    )
    assert await provider.health_check() is True
    assert route.called


@respx.mock
async def test_5xx_surfaces_as_provider_unavailable_after_retries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """P1a-Regression: ein anhaltendes HTTP 5xx muss als ProviderUnavailable
    herauskommen (nicht als httpx.HTTPStatusError), damit transcribe_for_mode
    auf fallback_stt umschalten kann."""
    from tenacity import wait_none

    monkeypatch.setattr(
        "sprichblitz_backend.providers.retry.wait_exponential",
        lambda *a, **k: wait_none(),
    )
    route = respx.post("https://api.openai.com/v1/audio/transcriptions").mock(
        return_value=Response(503, text="upstream down")
    )
    provider = OpenAIWhisperProvider(
        name="openai_whisper",
        base_url="https://api.openai.com/v1",
        api_key_env="OPENAI_API_KEY",
        model="whisper-1",
    )
    with pytest.raises(ProviderUnavailable) as exc:
        await provider.transcribe(b"\x00", language="de")

    assert exc.value.provider == "openai_whisper"
    assert "503" in exc.value.message
    assert route.call_count == 3  # 3 Versuche (Retry), dann ProviderUnavailable
