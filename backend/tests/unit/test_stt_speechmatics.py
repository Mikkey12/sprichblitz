from __future__ import annotations

import pytest

from sprichblitz_backend.providers.stt.speechmatics import SpeechmaticsProvider


def _make() -> SpeechmaticsProvider:
    return SpeechmaticsProvider(
        name="speechmatics",
        base_url="https://asr.api.speechmatics.com/v2",
        api_key_env="SPEECHMATICS_API_KEY",
        model="enhanced",
    )


@pytest.mark.asyncio
async def test_transcribe_raises_not_implemented() -> None:
    provider = _make()
    with pytest.raises(NotImplementedError):
        await provider.transcribe(b"\x00", language="de")


@pytest.mark.asyncio
async def test_health_check_raises_not_implemented() -> None:
    provider = _make()
    with pytest.raises(NotImplementedError):
        await provider.health_check()
