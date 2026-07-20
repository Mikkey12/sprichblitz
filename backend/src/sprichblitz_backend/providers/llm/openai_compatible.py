"""LLM provider for OpenAI-compatible endpoints.

A single class handles three real providers (OpenAI, OpenRouter, LM Studio),
each instantiated separately by the registry with its own ``base_url`` and
``api_key_env``. This avoids duplicating the same code three times.

Note on prefill: OpenAI's chat-completion API does not honour an assistant
message at the *end* of the messages list as a prefill the way Anthropic
does. We therefore ignore ``prefill`` here and rely on a strict system
prompt to keep the model from prepending boilerplate. Anthropic is the only
provider that needs the prefill mechanism.
"""

from __future__ import annotations

from loguru import logger

from ...models.domain import CompletionResult
from .._openai_compat import _OpenAICompatibleClient
from ..base import LLMProvider
from ..retry import with_retry


class OpenAICompatibleLLMProvider(LLMProvider):
    def __init__(
        self,
        *,
        name: str,
        base_url: str,
        api_key_env: str,
        default_model: str,
        health_path: str | None = None,
    ) -> None:
        self.name = name
        self.default_model = default_model
        self._client = _OpenAICompatibleClient(
            provider=name,
            base_url=base_url,
            api_key_env=api_key_env,
            health_path=health_path,
        )

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
        if prefill:
            # Document, rather than silently drop, that prefill is unsupported.
            logger.debug(
                "Provider does not support assistant prefill – ignoring",
                provider=self.name,
            )
        chosen = model or self.default_model
        text, in_tokens, out_tokens = await self._client.chat_completion(
            system=system,
            user=user,
            model=chosen,
            max_tokens=max_tokens,
            api_key=api_key,
        )
        return CompletionResult(
            text=text,
            provider=self.name,
            model=chosen,
            input_tokens=in_tokens,
            output_tokens=out_tokens,
        )

    async def list_models(self, api_key: str | None = None) -> list[str]:
        return await self._client.list_models(api_key)

    async def health_check(self, api_key: str | None = None) -> bool:
        return await self._client.health_check(api_key)
