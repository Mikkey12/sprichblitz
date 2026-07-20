"""Transcription orchestration: pick the STT, run it, fall back on failure."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from loguru import logger

from ..models.config_models import ModeConfig
from ..models.domain import TranscriptionResult
from ..providers.base import STTProvider
from ..providers.registry import ProviderRegistry
from ..util.errors import ProviderEmptyResult, ProviderError, ProviderUnavailable
from .local_gate import LocalInferenceGate

# Auslöser für den STT-Fallback: transienter Ausfall (5xx/Connect/Timeout →
# ProviderUnavailable) ODER eine gültige Antwort ohne verwertbaren Text
# (ProviderEmptyResult). Ein 4xx-Status (Quota/Bad-Request) nutzt die Basisklasse
# ProviderInvalidResponse und ist hier BEWUSST NICHT enthalten – er wird 1:1 an
# den Client gereicht, damit die aufrufende Person ihn sieht.
_FALLBACK_TRIGGERS = (ProviderUnavailable, ProviderEmptyResult)


@dataclass
class TranscribeOutcome:
    result: TranscriptionResult
    used_fallback: bool


async def _transcribe(
    provider: STTProvider,
    audio_wav: bytes,
    mode: ModeConfig,
    api_key: str | None,
    gate: LocalInferenceGate | None,
) -> TranscriptionResult:
    """Ein STT-Call; durchs Gate nur, wenn der Provider lokal ist (key_provider None)."""
    if gate is not None and provider.key_provider is None:
        async with gate.slot():
            return await provider.transcribe(
                audio_wav, language=mode.language, prompt_hint=mode.prompt_hint, api_key=api_key
            )
    return await provider.transcribe(
        audio_wav, language=mode.language, prompt_hint=mode.prompt_hint, api_key=api_key
    )


async def transcribe_for_mode(
    *,
    audio_wav: bytes,
    mode: ModeConfig,
    registry: ProviderRegistry,
    api_key_for: Callable[[str], str | None] | None = None,
    gate: LocalInferenceGate | None = None,
) -> TranscribeOutcome:
    """Transcribe ``audio_wav`` (16 kHz mono PCM in WAV) using the mode's STT.

    Fällt auf ``mode.fallback_stt`` zurück, wenn der Primär-STT ausfällt
    (``ProviderUnavailable``) ODER eine gültige Antwort ohne verwertbaren Text
    liefert (``ProviderEmptyResult``, bzw. leeres Transkript). Genau der
    Resilienz-Pfad für ``exact_swiss``/``mundart``: dichte Mundart → lokales STT
    liefert nichts Brauchbares → Cloud-Fallback. Ein 4xx-Status (Quota/Bad-Request)
    triggert bewusst KEINEN Fallback (siehe ``_FALLBACK_TRIGGERS``). Lokale Calls
    (key_provider None) laufen einzeln durchs ``gate``; Cloud-Calls daran vorbei.
    Ein fehlender Pflicht-Key wirft **vor** dem Call (412).
    """
    primary = registry.get_stt(mode.stt)
    primary_key = api_key_for(primary.name) if api_key_for else None
    try:
        result = await _transcribe(primary, audio_wav, mode, primary_key, gate)
    except _FALLBACK_TRIGGERS as exc:
        if not mode.fallback_stt:
            raise
        logger.warning(
            "Primary STT failed, falling back",
            primary=primary.name,
            fallback=mode.fallback_stt,
            error=str(exc),
        )
        fb = await _transcribe_fallback(audio_wav, mode, registry, api_key_for, gate)
        return TranscribeOutcome(result=fb, used_fallback=True)

    # Primär hat geantwortet, aber ohne verwertbaren Text. Bei konfiguriertem
    # Fallback ist genau das der Mundart-Fall, für den er existiert – also
    # versuchen. OHNE Fallback bleibt "" ein gültiges Ergebnis (z. B. Stille) und
    # erzeugt KEINEN Fehler.
    if mode.fallback_stt and not result.text.strip():
        logger.warning(
            "Primary STT returned blank text, trying fallback",
            primary=primary.name,
            fallback=mode.fallback_stt,
        )
        try:
            fb = await _transcribe_fallback(audio_wav, mode, registry, api_key_for, gate)
        except ProviderError:
            # Fallback selbst gescheitert → das gültige (leere) Primär-Ergebnis
            # ist besser als ein harter Fehler.
            return TranscribeOutcome(result=result, used_fallback=False)
        return TranscribeOutcome(result=fb, used_fallback=True)

    return TranscribeOutcome(result=result, used_fallback=False)


async def _transcribe_fallback(
    audio_wav: bytes,
    mode: ModeConfig,
    registry: ProviderRegistry,
    api_key_for: Callable[[str], str | None] | None,
    gate: LocalInferenceGate | None,
) -> TranscriptionResult:
    fallback = registry.get_stt(mode.fallback_stt)
    fallback_key = api_key_for(fallback.name) if api_key_for else None
    return await _transcribe(fallback, audio_wav, mode, fallback_key, gate)
