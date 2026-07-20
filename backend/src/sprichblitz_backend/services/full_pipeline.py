"""End-to-end pipeline: audio → STT (+ fallback) → optional LLM."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass

from ..audio.normalizer import normalize_to_pcm16k_mono
from ..db.models import ModeOverride
from ..models.api import FullResponse, Mode, TranscribeResponse
from ..models.config_models import AppConfig, LocalProvidersConfig, ModeConfig
from ..providers.registry import ProviderRegistry
from .local_gate import LocalInferenceGate
from .locale_orthography import apply_locale_orthography
from .mode_overrides import apply_user_override
from .post_processing import post_process_for_mode
from .transcription import transcribe_for_mode


@dataclass
class TranscribeOnlyOutcome:
    response: TranscribeResponse


async def transcribe_only(
    *,
    audio_bytes: bytes,
    audio_format: str | None,
    mode_name: Mode,
    base_mode: ModeConfig,
    cfg: AppConfig,
    registry: ProviderRegistry,
    stt_override: str | None = None,
    locale: str | None = None,
    location: str = "online",
    mode_override: ModeOverride | None = None,
    gate: LocalInferenceGate | None = None,
    api_key_for: Callable[[str], str | None] | None = None,
) -> TranscribeResponse:
    base = base_mode
    _ensure_mode_enabled(mode_name, mode_override)
    located = resolve_mode_for_location(
        apply_user_override(base, mode_override, registry=registry),
        location,
        cfg.local_providers,
    )
    allowed_stt = {cfg.local_providers.stt} if location == "local" else None
    mode = build_effective_mode(located, registry, stt=stt_override, allowed_stt=allowed_stt)

    started = time.monotonic()
    normalized = await normalize_to_pcm16k_mono(audio_bytes, format_hint=audio_format)
    outcome = await transcribe_for_mode(
        audio_wav=normalized.pcm_wav_bytes,
        mode=mode,
        registry=registry,
        api_key_for=api_key_for,
        gate=gate,
    )
    duration_ms = int((time.monotonic() - started) * 1000)

    return TranscribeResponse(
        mode=mode_name,
        text=apply_locale_orthography(outcome.result.text, locale),
        stt_provider=outcome.result.provider,
        stt_model=outcome.result.model,
        used_fallback=outcome.used_fallback,
        duration_ms=duration_ms,
        audio_seconds=normalized.duration_seconds,
    )


async def full_pipeline(
    *,
    audio_bytes: bytes,
    audio_format: str | None,
    mode_name: Mode,
    base_mode: ModeConfig,
    cfg: AppConfig,
    registry: ProviderRegistry,
    stt_override: str | None = None,
    llm_override: str | None = None,
    llm_model_override: str | None = None,
    locale: str | None = None,
    location: str = "online",
    mode_override: ModeOverride | None = None,
    gate: LocalInferenceGate | None = None,
    api_key_for: Callable[[str], str | None] | None = None,
) -> FullResponse:
    base = base_mode
    _ensure_mode_enabled(mode_name, mode_override)
    located = resolve_mode_for_location(
        apply_user_override(base, mode_override, registry=registry),
        location,
        cfg.local_providers,
    )
    is_local = location == "local"
    mode = build_effective_mode(
        located,
        registry,
        stt=stt_override,
        llm=llm_override,
        llm_model=llm_model_override,
        allowed_stt={cfg.local_providers.stt} if is_local else None,
        allowed_llm={cfg.local_providers.llm} if is_local else None,
    )
    ensure_llm_wellformed(mode_name, mode)

    started = time.monotonic()
    normalized = await normalize_to_pcm16k_mono(audio_bytes, format_hint=audio_format)
    stt = await transcribe_for_mode(
        audio_wav=normalized.pcm_wav_bytes,
        mode=mode,
        registry=registry,
        api_key_for=api_key_for,
        gate=gate,
    )

    # Deterministische Locale-Orthografie auf STT-Output anwenden.
    raw_text = apply_locale_orthography(stt.result.text, locale)

    if not mode.apply_llm:
        total_ms = int((time.monotonic() - started) * 1000)
        return FullResponse(
            mode=mode_name,
            raw_text=raw_text,
            final_text=raw_text,
            stt_provider=stt.result.provider,
            stt_model=stt.result.model,
            llm_provider=None,
            llm_model=None,
            used_fallback=stt.used_fallback,
            audio_seconds=normalized.duration_seconds,
            total_duration_ms=total_ms,
        )

    llm = await post_process_for_mode(
        # LLM bekommt den bereits korrigierten Text; das LLM-Output wird
        # zusätzlich nochmal normalisiert, falls es ß wieder einbaut.
        text=raw_text,
        mode=mode,
        registry=registry,
        locale=locale,
        api_key_for=api_key_for,
        gate=gate,
    )
    total_ms = int((time.monotonic() - started) * 1000)

    return FullResponse(
        mode=mode_name,
        raw_text=raw_text,
        final_text=apply_locale_orthography(llm.text, locale),
        stt_provider=stt.result.provider,
        stt_model=stt.result.model,
        llm_provider=llm.provider,
        llm_model=llm.model,
        used_fallback=stt.used_fallback,
        audio_seconds=normalized.duration_seconds,
        total_duration_ms=total_ms,
    )


# Die Auflösung eines Modus lebt bewusst NICHT mehr hier: seit die Modi auch aus
# der DB kommen (ModeDefinition), bräuchte sie eine Session – und die Pipeline soll
# rechenbar bleiben, nicht datenbankabhängig. Die Routen lösen auf (wie process.py
# es schon immer tat) und reichen den fertigen ``base_mode`` herein.


def _ensure_mode_enabled(mode_name: Mode, override: ModeOverride | None) -> None:
    from ..util.errors import ModeDisabled

    if override is not None and not override.enabled:
        raise ModeDisabled(mode_name)


def ensure_llm_wellformed(mode_name: Mode, mode: ModeConfig) -> None:
    """Defensiv: ``apply_llm`` an, aber effektiv kein LLM/Prompt → 409 statt 500.

    Greift erst nach der vollen Merge-/Location-Auflösung. Im local-Modus ist
    ``mode.llm`` immer gesetzt (lokaler Provider), daher relevant v. a. online.
    Die PUT-Validierung in ``routes/me.py`` verhindert solche Overrides bereits.
    """
    from ..util.errors import ModeMisconfigured

    if mode.apply_llm and (not mode.llm or not mode.system_prompt):
        raise ModeMisconfigured(mode_name)


def resolve_mode_for_location(
    mode: ModeConfig, location: str, local_providers: LocalProvidersConfig
) -> ModeConfig:
    """§6: Provider-Auswahl je ``processing_location``.

    ``online`` → Mode-Config unverändert (STT/LLM/fallback_stt wie konfiguriert,
    inkl. exact_swiss-STT = WhisperKit, Cloud nur als Fallback). ``local`` →
    STT/LLM auf die lokalen Provider, STT-Cloud-Fallback hart ``None`` (§6 #5).
    """
    if location != "local":
        return mode
    # local erzwingt die lokalen Provider. ``llm_model`` MUSS mit zurückgesetzt
    # werden: ein online-spezifischer Modellname (z. B. aus einem User-Override
    # ``claude-haiku-4-5``) würde sonst an LM Studio gereicht → unbekanntes Modell.
    # None → der lokale Provider nutzt sein Default-Modell.
    updates: dict[str, object] = {
        "stt": local_providers.stt,
        "fallback_stt": None,
        "llm_model": None,
    }
    if mode.apply_llm:
        updates["llm"] = local_providers.llm
    return mode.model_copy(update=updates)


def build_effective_mode(
    mode: ModeConfig,
    registry: ProviderRegistry,
    *,
    stt: str | None = None,
    llm: str | None = None,
    llm_model: str | None = None,
    allowed_stt: set[str] | None = None,
    allowed_llm: set[str] | None = None,
) -> ModeConfig:
    """Apply per-request provider/model overrides onto a mode.

    Returns ``mode`` unchanged when no override is set. ``allowed_stt`` /
    ``allowed_llm`` bound which providers an override may select; default = the
    full registry (online). Im ``local``-Modus übergibt die Pipeline nur die
    lokalen Provider → ein Cloud-Override wird abgelehnt (harte Grenze, §6).
    ``llm_model`` is free-form – the provider decides whether it exists.
    """
    from ..util.errors import OverrideNotAllowed

    allowed_stt = allowed_stt if allowed_stt is not None else set(registry.stt)
    allowed_llm = allowed_llm if allowed_llm is not None else set(registry.llm)

    updates: dict[str, str] = {}
    if stt:
        if stt not in allowed_stt:
            raise OverrideNotAllowed("STT", stt)
        updates["stt"] = stt
    if llm:
        if llm not in allowed_llm:
            raise OverrideNotAllowed("LLM", llm)
        updates["llm"] = llm
    if llm_model:
        updates["llm_model"] = llm_model
    return mode.model_copy(update=updates) if updates else mode
