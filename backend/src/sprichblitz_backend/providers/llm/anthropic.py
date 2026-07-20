"""Anthropic LLM provider with assistant-prefill support.

Prefill works by appending an ``assistant`` message at the end of the
``messages`` list. Anthropic continues from that prefix – so the returned
text is just the *continuation*. We prepend the prefill to reconstruct the
full response a downstream client expects.
"""

from __future__ import annotations

import anthropic

from ...models.domain import CompletionResult
from ...util.errors import (
    ProviderAuthError,
    ProviderInvalidResponse,
    ProviderUnavailable,
)
from ..base import LLMProvider
from ..retry import with_retry


class AnthropicProvider(LLMProvider):
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

    def _client(self, api_key: str | None = None) -> anthropic.AsyncAnthropic:
        # Key ausschliesslich per Request (Per-User-Vault); kein Env-Fallback.
        if not api_key:
            raise ProviderAuthError(
                f"Kein API-Key für {self.name} übergeben",
                provider=self.name,
            )
        return anthropic.AsyncAnthropic(api_key=api_key)

    @staticmethod
    def build_messages(user: str, prefill: str | None) -> list[dict[str, str]]:
        """Construct the messages list used in the API call.

        Pure helper so tests can verify the structure without monkey-patching
        the Anthropic SDK.
        """
        messages: list[dict[str, str]] = [{"role": "user", "content": user}]
        if prefill:
            messages.append({"role": "assistant", "content": prefill})
        return messages

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
        chosen = model or self.default_model
        messages = self.build_messages(user, prefill)
        client = self._client(api_key)

        try:
            response = await client.messages.create(
                model=chosen,
                max_tokens=max_tokens,
                system=system,
                messages=messages,
            )
        except anthropic.APIConnectionError as exc:
            raise ProviderUnavailable(
                f"Connection error: {exc.__class__.__name__}", provider=self.name
            ) from exc
        except anthropic.AuthenticationError as exc:
            raise ProviderAuthError(
                f"Authentication failed (HTTP {exc.status_code})", provider=self.name
            ) from exc
        except anthropic.APIStatusError as exc:
            # SDK-Fehlertexte und Response-Bodies können Request-Inhalte
            # echoen. Deshalb weder weiterreichen noch auf DEBUG loggen.
            raise ProviderInvalidResponse(
                f"Anthropic API error (HTTP {exc.status_code})", provider=self.name
            ) from exc

        # Anthropic returns content as a list of blocks; we use only the
        # first text block – tools/images are not in scope here.
        try:
            continuation = response.content[0].text
        except (AttributeError, IndexError) as exc:
            raise ProviderInvalidResponse(
                "Anthropic response missing text content",
                provider=self.name,
            ) from exc

        text = (prefill + continuation) if prefill else continuation
        usage = getattr(response, "usage", None)

        return CompletionResult(
            text=text,
            provider=self.name,
            model=chosen,
            input_tokens=getattr(usage, "input_tokens", None),
            output_tokens=getattr(usage, "output_tokens", None),
        )

    async def list_models(self, api_key: str | None = None) -> list[str]:
        # Anthropic exposes a `client.models.list()` paginator, but the
        # network call is unhelpful for our startup health check (it can be
        # rate-limited). Hard-code the slugs we plan to expose; users can
        # still set any model in config.local.yml. ``api_key`` wird nicht
        # gebraucht (statische Liste), aber signaturkompatibel akzeptiert.
        return [
            "claude-haiku-4-5-20251001",
            "claude-sonnet-4-6",
            "claude-opus-4-7",
        ]

    async def health_check(self, api_key: str | None = None) -> bool:
        try:
            client = self._client(api_key)
        except ProviderAuthError:
            return False  # kein Key übergeben → „offline" = Key fehlt
        try:
            # Cheapest reliable health probe: list models (testet den Key).
            await client.models.list(limit=1)
            return True
        except Exception:
            return False
