"""Provider registry: builds STT and LLM provider instances from config.

Validation policy: when the configured ``default_model`` is not in the
provider's reported ``list_models()``, log a WARNING but keep the provider
active – the user can still select a different model from the client. This
keeps optional providers from preventing backend startup.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from loguru import logger

from ..models.config_models import (
    AppConfig,
    LLMProviderConfig,
    STTProviderConfig,
)
from .base import LLMProvider, STTProvider
from .llm.anthropic import AnthropicProvider
from .llm.gemini import GeminiProvider
from .llm.openai_compatible import OpenAICompatibleLLMProvider
from .stt.openai_whisper import OpenAIWhisperProvider
from .stt.speechmatics import SpeechmaticsProvider


@dataclass
class ProviderRegistry:
    stt: dict[str, STTProvider]
    llm: dict[str, LLMProvider]

    def get_stt(self, name: str) -> STTProvider:
        try:
            return self.stt[name]
        except KeyError as exc:
            raise KeyError(f"STT provider not configured: {name}") from exc

    def get_llm(self, name: str) -> LLMProvider:
        try:
            return self.llm[name]
        except KeyError as exc:
            raise KeyError(f"LLM provider not configured: {name}") from exc


def _build_stt(name: str, cfg: STTProviderConfig) -> STTProvider:
    """Map a config entry to an STT provider instance – dispatch by ``type``.

    Analog zu ``_build_llm``: die Auswahl geschieht über ``cfg.type``, nicht
    über den Namen. Damit ist ein neuer STT-Provider (z. B. ``gpt-4o-transcribe``
    als Cloud-Option) **reine Config** – kein Code. Alle OpenAI-kompatiblen
    Endpunkte (Cloud-Whisper, gpt-4o-transcribe, lokales WhisperKit/LM Studio)
    teilen sich denselben Client; ``speechmatics`` ist ein eigener Typ.
    """
    if cfg.type == "openai_compatible":
        return OpenAIWhisperProvider(
            name=name,
            base_url=cfg.base_url,
            api_key_env=cfg.api_key_env,
            model=cfg.model,
            health_path=cfg.health_path,
        )
    if cfg.type == "speechmatics":
        return SpeechmaticsProvider(
            name=name,
            base_url=cfg.base_url,
            api_key_env=cfg.api_key_env,
            model=cfg.model,
        )
    raise ValueError(f"Unknown STT provider type: {cfg.type}")


def _build_llm(name: str, cfg: LLMProviderConfig) -> LLMProvider:
    if cfg.type == "anthropic":
        return AnthropicProvider(
            name=name,
            api_key_env=cfg.api_key_env,
            default_model=cfg.default_model,
        )
    if cfg.type == "gemini":
        return GeminiProvider(
            name=name,
            api_key_env=cfg.api_key_env,
            default_model=cfg.default_model,
        )
    if cfg.type == "openai_compatible":
        if not cfg.base_url:
            raise ValueError(f"LLM provider {name} of type 'openai_compatible' needs base_url")
        return OpenAICompatibleLLMProvider(
            name=name,
            base_url=cfg.base_url,
            api_key_env=cfg.api_key_env,
            default_model=cfg.default_model,
            health_path=cfg.health_path,
        )
    raise ValueError(f"Unknown LLM provider type: {cfg.type}")


def build_registry(cfg: AppConfig) -> ProviderRegistry:
    stt = {name: _build_stt(name, c) for name, c in cfg.stt_providers.items()}
    llm = {name: _build_llm(name, c) for name, c in cfg.llm_providers.items()}
    # key_provider an die Instanzen hängen (Etappe-5-Gate erkennt „lokal" daran).
    for name, c in cfg.stt_providers.items():
        stt[name].key_provider = c.key_provider
    for name, c in cfg.llm_providers.items():
        llm[name].key_provider = c.key_provider
    return ProviderRegistry(stt=stt, llm=llm)


def validate_local_providers(cfg: AppConfig, registry: ProviderRegistry) -> None:
    """Fail fast, wenn die local_providers (§6) nicht in der Registry stehen."""
    if cfg.local_providers.stt not in registry.stt:
        raise ValueError(
            f"local_providers.stt '{cfg.local_providers.stt}' ist kein konfigurierter STT-Provider"
        )
    if cfg.local_providers.llm not in registry.llm:
        raise ValueError(
            f"local_providers.llm '{cfg.local_providers.llm}' ist kein konfigurierter LLM-Provider"
        )


async def validate_models_at_startup(registry: ProviderRegistry) -> None:
    """Probe each LLM provider's model list and warn on default-mismatches.

    Runs all probes in parallel because each call has a short timeout and
    multiple providers should not stall startup. Any failure is logged as
    INFO – an offline provider is normal during local development.
    """

    async def _check(provider: LLMProvider) -> None:
        try:
            available = await provider.list_models()
        except Exception as exc:  # pragma: no cover - defensive only
            logger.info(
                "Could not list models at startup",
                provider=provider.name,
                error=str(exc),
            )
            return

        if not available:
            logger.info(
                "Provider returned no models at startup; skipping default-model check",
                provider=provider.name,
            )
            return

        if provider.default_model not in available:
            logger.warning(
                "Default model not in provider's model list",
                provider=provider.name,
                default_model=provider.default_model,
                available=available[:10],
            )

    await asyncio.gather(*[_check(p) for p in registry.llm.values()])
