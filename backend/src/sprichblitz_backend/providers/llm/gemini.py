"""Gemini LLM provider via the ``google-genai`` SDK."""

from __future__ import annotations

from google import genai
from google.genai import types as genai_types

from ...models.domain import CompletionResult
from ...util.errors import (
    ProviderAuthError,
    ProviderInvalidResponse,
    ProviderUnavailable,
)
from ..base import LLMProvider
from ..retry import with_retry


class GeminiProvider(LLMProvider):
    def __init__(
        self,
        *,
        name: str,
        api_key_env: str,
        default_model: str,
    ) -> None:
        self.name = name
        self.default_model = default_model
        self._api_key_env = api_key_env

    def _client(self, api_key: str | None = None) -> genai.Client:
        # Key ausschliesslich per Request (Per-User-Vault); kein Env-Fallback.
        if not api_key:
            raise ProviderAuthError(
                f"Kein API-Key für {self.name} übergeben",
                provider=self.name,
            )
        return genai.Client(api_key=api_key)

    @with_retry
    async def complete(
        self,
        system: str,
        user: str,
        model: str | None = None,
        max_tokens: int = 1000,
        prefill: str | None = None,
        api_key: str | None = None,
    ) -> CompletionResult:
        # Gemini does not support assistant-prefill; ignore quietly.
        chosen = model or self.default_model
        client = self._client(api_key)
        try:
            response = await client.aio.models.generate_content(
                model=chosen,
                contents=user,
                config=genai_types.GenerateContentConfig(
                    system_instruction=system,
                    max_output_tokens=max_tokens,
                ),
            )
        except Exception as exc:  # google-genai raises various subclasses
            # SDK-Fehlertexte können Response-Bodies und damit Request-Inhalte
            # enthalten. Nur zur Klassifikation verwenden, niemals loggen oder
            # an den Client weiterreichen.
            msg = str(exc).lower()
            if "auth" in msg or "api key" in msg or "permission" in msg:
                raise ProviderAuthError(
                    f"Authentication failed ({exc.__class__.__name__})",
                    provider=self.name,
                ) from exc
            raise ProviderUnavailable(
                f"Gemini call failed ({exc.__class__.__name__})", provider=self.name
            ) from exc

        text = getattr(response, "text", None)
        if not isinstance(text, str):
            raise ProviderInvalidResponse("Gemini response has no text", provider=self.name)

        usage = getattr(response, "usage_metadata", None)
        return CompletionResult(
            text=text,
            provider=self.name,
            model=chosen,
            input_tokens=getattr(usage, "prompt_token_count", None) if usage else None,
            output_tokens=getattr(usage, "candidates_token_count", None) if usage else None,
        )

    async def list_models(self, api_key: str | None = None) -> list[str]:
        try:
            client = self._client(api_key)
        except ProviderAuthError:
            return []  # ohne Key keine Liste (statt Absturz)
        try:
            models = await client.aio.models.list()
            return [m.name for m in models if getattr(m, "name", None)]
        except Exception:
            return []

    async def health_check(self, api_key: str | None = None) -> bool:
        try:
            client = self._client(api_key)
        except ProviderAuthError:
            return False  # kein Key übergeben → „offline" = Key fehlt
        try:
            await client.aio.models.list()
            return True
        except Exception:
            return False
