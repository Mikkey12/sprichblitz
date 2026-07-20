"""Shared HTTP client for OpenAI-compatible endpoints.

Backs OpenAI Whisper, LM-Studio Whisper, OpenAI Chat, OpenRouter Chat and
LM-Studio Chat. The protocol is a subset of OpenAI's REST API: bearer auth,
`/v1/chat/completions`, `/v1/audio/transcriptions`, `/v1/models`. LM Studio
accepts an empty bearer; OpenAI/OpenRouter require a real key.
"""

from __future__ import annotations

from typing import Any

import httpx

from ..util.errors import (
    ProviderAuthError,
    ProviderEmptyResult,
    ProviderInvalidResponse,
    ProviderUnavailable,
)

_DEFAULT_TIMEOUT = httpx.Timeout(connect=5.0, read=60.0, write=60.0, pool=5.0)
_HEALTH_TIMEOUT = httpx.Timeout(5.0)


class _OpenAICompatibleClient:
    """Thin async wrapper around an OpenAI-compatible HTTP API."""

    def __init__(
        self,
        *,
        provider: str,
        base_url: str,
        api_key_env: str = "",
        health_path: str | None = None,
        timeout: httpx.Timeout | None = None,
    ) -> None:
        self._provider = provider
        self._base_url = base_url.rstrip("/")
        self._api_key_env = api_key_env
        self._health_path = health_path
        self._timeout = timeout or _DEFAULT_TIMEOUT

    # ------------------------------------------------------------------
    # Auth helpers
    # ------------------------------------------------------------------
    def _headers(
        self, *, api_key: str | None = None, extra: dict[str, str] | None = None
    ) -> dict[str, str]:
        # Key kommt ausschliesslich per Request (Per-User-Vault); KEIN Env-Key.
        # Lokale Provider (kein key_provider) → kein Header (leerer Bearer ok).
        headers: dict[str, str] = {}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        if extra:
            headers.update(extra)
        return headers

    # ------------------------------------------------------------------
    # Chat completion
    # ------------------------------------------------------------------
    async def chat_completion(
        self,
        *,
        system: str,
        user: str,
        model: str,
        max_tokens: int = 1000,
        api_key: str | None = None,
    ) -> tuple[str, int | None, int | None]:
        url = f"{self._base_url}/chat/completions"
        body = {
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "max_tokens": max_tokens,
        }

        async with httpx.AsyncClient(timeout=self._timeout) as client:
            try:
                response = await client.post(url, headers=self._headers(api_key=api_key), json=body)
            except httpx.HTTPError as exc:
                raise ProviderUnavailable(
                    f"Connection error: {exc.__class__.__name__}",
                    provider=self._provider,
                ) from exc
            self._raise_for_status(response, context="chat_completion")
            data = self._json_object(response, context="chat_completion")

        try:
            text = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise ProviderInvalidResponse(
                "Missing choices[0].message.content in response",
                provider=self._provider,
            ) from exc

        if not isinstance(text, str):
            raise ProviderInvalidResponse(
                "choices[0].message.content is not a string",
                provider=self._provider,
            )
        usage = data.get("usage")
        if not isinstance(usage, dict):
            usage = {}
        prompt_tokens = usage.get("prompt_tokens")
        completion_tokens = usage.get("completion_tokens")
        return (
            text,
            prompt_tokens if isinstance(prompt_tokens, int) and not isinstance(prompt_tokens, bool) else None,
            completion_tokens
            if isinstance(completion_tokens, int) and not isinstance(completion_tokens, bool)
            else None,
        )

    # ------------------------------------------------------------------
    # Audio transcription (Whisper-compatible)
    # ------------------------------------------------------------------
    async def transcribe_audio(
        self,
        *,
        audio_wav: bytes,
        model: str,
        language: str = "de",
        prompt_hint: str | None = None,
        api_key: str | None = None,
    ) -> tuple[str, float | None]:
        url = f"{self._base_url}/audio/transcriptions"
        files = {"file": ("audio.wav", audio_wav, "audio/wav")}
        data: dict[str, str] = {
            "model": model,
            "language": language,
            "response_format": "json",
        }
        if prompt_hint:
            data["prompt"] = prompt_hint

        async with httpx.AsyncClient(timeout=self._timeout) as client:
            try:
                response = await client.post(
                    url,
                    headers=self._headers(api_key=api_key),
                    files=files,
                    data=data,
                )
            except httpx.HTTPError as exc:
                raise ProviderUnavailable(
                    f"Connection error: {exc.__class__.__name__}",
                    provider=self._provider,
                ) from exc
            self._raise_for_status(response, context="transcribe_audio")
            payload = self._json_object(response, context="transcribe_audio")

        text = payload.get("text")
        if not isinstance(text, str):
            # Fehlendes/kein-String text = Provider-Fehlverhalten → ProviderEmptyResult
            # (löst den STT-Fallback aus, anders als ein 4xx-Status). Ein leerer
            # String "" gilt hier NICHT als Fehler (kann legitime Stille sein) – die
            # Fallback-Entscheidung bei leerem Text trifft transcribe_for_mode.
            raise ProviderEmptyResult(
                "Missing 'text' in transcription response",
                provider=self._provider,
            )
        # OpenAI Whisper does not return confidence in `response_format=json`;
        # LM Studio may include `confidence` for some models.
        confidence: Any = payload.get("confidence")
        return text, float(confidence) if isinstance(confidence, (int, float)) else None

    # ------------------------------------------------------------------
    # Models + health
    # ------------------------------------------------------------------
    async def list_models(self, api_key: str | None = None) -> list[str]:
        url = f"{self._base_url}/models"
        async with httpx.AsyncClient(timeout=_HEALTH_TIMEOUT) as client:
            try:
                response = await client.get(url, headers=self._headers(api_key=api_key))
                response.raise_for_status()
            except httpx.HTTPError:
                return []
            try:
                payload = response.json()
            except ValueError:
                return []

        if not isinstance(payload, dict):
            return []
        items = payload.get("data")
        if not isinstance(items, list):
            return []
        return [
            model_id
            for item in items
            if isinstance(item, dict)
            and isinstance((model_id := item.get("id")), str)
            and model_id
        ]

    async def health_check(self, api_key: str | None = None) -> bool:
        url = self._health_url()
        # Mit Per-User-Key (aus /config) testet der Probe den echten Key: 200 →
        # gesund. Ohne Key meldet ein Cloud-Provider mit Pflicht-Key 401 →
        # „offline" = korrekt „Key fehlt/ungültig" (best effort).
        headers = self._headers(api_key=api_key)
        async with httpx.AsyncClient(timeout=_HEALTH_TIMEOUT) as client:
            try:
                response = await client.get(url, headers=headers)
            except httpx.HTTPError:
                return False
        return 200 <= response.status_code < 300

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _raise_for_status(self, response: httpx.Response, *, context: str) -> None:
        """Map 5xx to ProviderUnavailable and 4xx to ProviderInvalidResponse.

        5xx is ``ProviderUnavailable`` (not a raw ``HTTPStatusError``) so the
        whole transient path is one exception type: ``with_retry`` retries it,
        and after exhaustion ``transcribe_for_mode`` can still recognise it and
        switch to ``fallback_stt``. 4xx never retries and the body usually
        carries the actual reason – include it in the message.
        """
        if response.status_code < 400:
            return
        # Provider-Bodies werden nie geloggt: sie können Request-Inhalte oder
        # Transkripte spiegeln. Nur Kontext und Status fliessen in die Exception.
        if response.status_code in (401, 403):
            # Abgelehnter Key → eigener 4xx (422), unterscheidbar von „kein Key".
            raise ProviderAuthError(
                f"{context} rejected the API key (HTTP {response.status_code})",
                provider=self._provider,
            )
        if response.status_code >= 500:
            raise ProviderUnavailable(
                f"{context} returned HTTP {response.status_code}",
                provider=self._provider,
            )
        raise ProviderInvalidResponse(
            f"{context} returned HTTP {response.status_code}",
            provider=self._provider,
        )

    def _health_url(self) -> str:
        if self._health_path is None:
            return f"{self._base_url}/models"
        return str(httpx.URL(f"{self._base_url}/").join(self._health_path))

    def _json_object(self, response: httpx.Response, *, context: str) -> dict[str, Any]:
        try:
            payload = response.json()
        except ValueError as exc:
            raise ProviderInvalidResponse(
                f"{context} returned invalid JSON",
                provider=self._provider,
            ) from exc
        if not isinstance(payload, dict):
            raise ProviderInvalidResponse(
                f"{context} returned a non-object JSON response",
                provider=self._provider,
            )
        return payload
