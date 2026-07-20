"""Speechmatics provider – interface skeleton, body intentionally unimplemented.

This may be wired up later; for now the class exists so the registry can
declare the provider type. Calling ``transcribe`` or ``health_check`` raises
``NotImplementedError`` (verified by tests).
"""

from __future__ import annotations

from ...models.domain import TranscriptionResult
from ..base import STTProvider


class SpeechmaticsProvider(STTProvider):
    def __init__(
        self,
        *,
        name: str,
        base_url: str,
        api_key_env: str,
        model: str,
    ) -> None:
        self.name = name
        self.model = model
        self._base_url = base_url
        self._api_key_env = api_key_env

    async def transcribe(
        self,
        audio: bytes,
        language: str = "de",
        prompt_hint: str | None = None,
        api_key: str | None = None,
    ) -> TranscriptionResult:
        raise NotImplementedError(
            "SpeechmaticsProvider is a skeleton – implement before enabling in config.yml"
        )

    async def health_check(self, api_key: str | None = None) -> bool:
        raise NotImplementedError(
            "SpeechmaticsProvider is a skeleton – implement before enabling in config.yml"
        )
