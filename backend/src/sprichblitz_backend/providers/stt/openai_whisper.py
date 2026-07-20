from __future__ import annotations

from ...models.domain import TranscriptionResult
from .._openai_compat import _OpenAICompatibleClient
from ..base import STTProvider
from ..retry import with_retry


class OpenAIWhisperProvider(STTProvider):
    """Cloud OpenAI Whisper (`whisper-1` by default)."""

    def __init__(
        self,
        *,
        name: str,
        base_url: str,
        api_key_env: str,
        model: str,
        health_path: str | None = None,
    ) -> None:
        self.name = name
        self.model = model
        self._client = _OpenAICompatibleClient(
            provider=name,
            base_url=base_url,
            api_key_env=api_key_env,
            health_path=health_path,
        )

    @with_retry
    async def transcribe(
        self,
        audio: bytes,
        language: str = "de",
        prompt_hint: str | None = None,
        api_key: str | None = None,
    ) -> TranscriptionResult:
        text, confidence = await self._client.transcribe_audio(
            audio_wav=audio,
            model=self.model,
            language=language,
            prompt_hint=prompt_hint,
            api_key=api_key,
        )
        return TranscriptionResult(
            text=text,
            language=language,
            confidence=confidence,
            provider=self.name,
            model=self.model,
        )

    async def health_check(self, api_key: str | None = None) -> bool:
        return await self._client.health_check(api_key)
