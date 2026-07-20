"""STT-Fallback-Logik in ``transcribe_for_mode``.

Deckt den Review-Befund 04/Befund-1 ab: ein leeres/verhörtes lokales STT-Ergebnis
muss auf ``fallback_stt`` zurückfallen (Resilienz für exact_swiss/mundart), ein
4xx-Status aber NICHT (Quota/Bad-Request bleibt 1:1 sichtbar).
"""

from __future__ import annotations

import pytest

from sprichblitz_backend.models.config_models import ModeConfig
from sprichblitz_backend.models.domain import TranscriptionResult
from sprichblitz_backend.providers.base import STTProvider
from sprichblitz_backend.providers.registry import ProviderRegistry
from sprichblitz_backend.services.transcription import transcribe_for_mode
from sprichblitz_backend.util.errors import (
    ProviderEmptyResult,
    ProviderInvalidResponse,
    ProviderUnavailable,
)


class _FakeSTT(STTProvider):
    """Liefert entweder einen festen Text oder wirft eine vorgegebene Exception."""

    def __init__(self, name: str, *, text: str | None = None, raises: Exception | None = None):
        self.name = name
        self.model = f"{name}-model"
        self.key_provider = None
        self._text = text
        self._raises = raises
        self.calls = 0

    async def transcribe(self, audio, language="de", prompt_hint=None, api_key=None):
        self.calls += 1
        if self._raises is not None:
            raise self._raises
        return TranscriptionResult(
            text=self._text, language=language, confidence=None, provider=self.name, model=self.model
        )

    async def health_check(self, api_key=None):
        return True


def _registry(primary: _FakeSTT, fallback: _FakeSTT | None = None) -> ProviderRegistry:
    stt = {primary.name: primary}
    if fallback is not None:
        stt[fallback.name] = fallback
    return ProviderRegistry(stt=stt, llm={})


def _mode(*, stt: str, fallback_stt: str | None = None) -> ModeConfig:
    return ModeConfig(description="t", stt=stt, language="de", fallback_stt=fallback_stt)


async def _run(mode: ModeConfig, registry: ProviderRegistry):
    return await transcribe_for_mode(
        audio_wav=b"x", mode=mode, registry=registry, api_key_for=lambda _n: None, gate=None
    )


@pytest.mark.asyncio
async def test_fallback_on_empty_result() -> None:
    primary = _FakeSTT("primary", raises=ProviderEmptyResult("no text", provider="primary"))
    fallback = _FakeSTT("fallback", text="aus der Cloud")
    out = await _run(_mode(stt="primary", fallback_stt="fallback"), _registry(primary, fallback))
    assert out.used_fallback is True
    assert out.result.text == "aus der Cloud"


@pytest.mark.asyncio
async def test_fallback_on_unavailable_still_works() -> None:
    primary = _FakeSTT("primary", raises=ProviderUnavailable("5xx", provider="primary"))
    fallback = _FakeSTT("fallback", text="aus der Cloud")
    out = await _run(_mode(stt="primary", fallback_stt="fallback"), _registry(primary, fallback))
    assert out.used_fallback is True
    assert out.result.text == "aus der Cloud"


@pytest.mark.asyncio
async def test_no_fallback_on_4xx_invalid_response() -> None:
    # Basisklasse ProviderInvalidResponse = 4xx-Status (Quota/Bad-Request) → 1:1 durch.
    primary = _FakeSTT("primary", raises=ProviderInvalidResponse("HTTP 429", provider="primary"))
    fallback = _FakeSTT("fallback", text="cloud")
    with pytest.raises(ProviderInvalidResponse):
        await _run(_mode(stt="primary", fallback_stt="fallback"), _registry(primary, fallback))
    assert fallback.calls == 0  # Fallback wurde NICHT angefasst


@pytest.mark.asyncio
async def test_fallback_on_blank_text() -> None:
    primary = _FakeSTT("primary", text="   ")  # gültige Antwort, aber leer
    fallback = _FakeSTT("fallback", text="jetzt echter Text")
    out = await _run(_mode(stt="primary", fallback_stt="fallback"), _registry(primary, fallback))
    assert out.used_fallback is True
    assert out.result.text == "jetzt echter Text"


@pytest.mark.asyncio
async def test_blank_text_without_fallback_returns_empty() -> None:
    # Stille (leeres Ergebnis) OHNE Fallback → gültiges "" , KEIN Fehler.
    primary = _FakeSTT("primary", text="")
    out = await _run(_mode(stt="primary", fallback_stt=None), _registry(primary))
    assert out.used_fallback is False
    assert out.result.text == ""


@pytest.mark.asyncio
async def test_blank_primary_falls_back_but_fallback_error_returns_primary() -> None:
    # Primär leer, Fallback scheitert → das gültige (leere) Primär-Ergebnis, kein 500.
    primary = _FakeSTT("primary", text="")
    fallback = _FakeSTT("fallback", raises=ProviderUnavailable("down", provider="fallback"))
    out = await _run(_mode(stt="primary", fallback_stt="fallback"), _registry(primary, fallback))
    assert out.used_fallback is False
    assert out.result.text == ""


@pytest.mark.asyncio
async def test_empty_result_without_fallback_propagates() -> None:
    primary = _FakeSTT("primary", raises=ProviderEmptyResult("no text", provider="primary"))
    with pytest.raises(ProviderEmptyResult):
        await _run(_mode(stt="primary", fallback_stt=None), _registry(primary))
