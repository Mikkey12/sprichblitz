"""LLM post-processing for the mail/rage/emoji modes."""

from __future__ import annotations

from collections.abc import Callable

from ..models.config_models import ModeConfig
from ..models.domain import CompletionResult
from ..providers.registry import ProviderRegistry
from .local_gate import LocalInferenceGate
from .locale_orthography import llm_system_prompt_for_locale


async def post_process_for_mode(
    *,
    text: str,
    mode: ModeConfig,
    registry: ProviderRegistry,
    locale: str | None = None,
    api_key_for: Callable[[str], str | None] | None = None,
    gate: LocalInferenceGate | None = None,
) -> CompletionResult:
    if not mode.apply_llm or not mode.llm:
        # Caller should not invoke us in this case; defend defensively.
        raise ValueError(f"Mode does not apply LLM: {mode!r}")
    if not mode.system_prompt:
        raise ValueError("Mode has apply_llm=true but no system_prompt set")

    # Locale-Bonus: bei Schweizer Locale dem System-Prompt einen Hinweis
    # auf Schweizer Schreibweise mitgeben. Die *Garantie* (ß→ss) kommt
    # weiterhin aus der deterministischen Nachkorrektur im full_pipeline.
    system = llm_system_prompt_for_locale(mode.system_prompt, locale)

    provider = registry.get_llm(mode.llm)
    api_key = api_key_for(provider.name) if api_key_for else None

    # Lokaler LLM (key_provider None) → durchs Gate; Cloud-LLM daran vorbei.
    if gate is not None and provider.key_provider is None:
        async with gate.slot():
            return await provider.complete(
                system=system,
                user=text,
                model=mode.llm_model,
                prefill=mode.output_prefill or None,
                api_key=api_key,
            )
    return await provider.complete(
        system=system,
        user=text,
        model=mode.llm_model,  # None falls back to provider's default
        prefill=mode.output_prefill or None,
        api_key=api_key,
    )
