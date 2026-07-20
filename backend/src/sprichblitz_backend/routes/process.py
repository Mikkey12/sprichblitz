from __future__ import annotations

import time
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from sqlmodel import Session

from ..auth import CurrentPrincipal
from ..db.engine import get_session
from ..models.api import ProcessRequest, ProcessResponse
from ..services import mode_definitions, mode_overrides, usage
from ..services.full_pipeline import (
    build_effective_mode,
    ensure_llm_wellformed,
    resolve_mode_for_location,
)
from ..services.locale_orthography import apply_locale_orthography
from ..services.post_processing import post_process_for_mode
from ..services.provider_keys import build_api_key_resolver
from ..util.errors import ModeDisabled, ModeNotConfigured, ProviderError

router = APIRouter()


@router.post("/process", response_model=ProcessResponse)
async def process_endpoint(
    request: Request,
    principal: CurrentPrincipal,
    session: Annotated[Session, Depends(get_session)],
    body: ProcessRequest,
) -> ProcessResponse:
    uid = int(principal.user_id)
    request.app.state.rate_limiter.check(uid)  # 429 VOR Gate/Pipeline

    cfg = request.app.state.config
    registry = request.app.state.registry

    # Effektive Menge (config.yml + globale DB-Modi), nicht nur die Config:
    # global deaktivierte sind hier weg und damit von unbekannten ununterscheidbar.
    base_mode = mode_definitions.resolve_mode(session, cfg, body.mode)
    if base_mode is None:
        raise ModeNotConfigured(body.mode)

    # §6: lokaler Modus nutzt den lokalen LLM (Qwen) statt Cloud, mit harter
    # Override-Grenze auf den lokalen Provider.
    override = mode_overrides.get_override(session, uid, body.mode)
    if override is not None and not override.enabled:
        raise ModeDisabled(body.mode)
    location = principal.processing_location
    located = resolve_mode_for_location(
        mode_overrides.apply_user_override(base_mode, override, registry=registry),
        location,
        cfg.local_providers,
    )
    mode = build_effective_mode(
        located,
        registry,
        llm=body.llm,
        llm_model=body.llm_model,
        allowed_llm={cfg.local_providers.llm} if location == "local" else None,
    )
    # Erst der vollständig zusammengeführte Modus ist massgeblich: Nutzer können
    # LLM-Verarbeitung pro Modus an- oder ausschalten. /process bleibt eine reine
    # LLM-Route und lehnt den effektiv ausgeschalteten Modus sauber mit 400 ab.
    if not mode.apply_llm:
        raise ModeNotConfigured(body.mode)
    ensure_llm_wellformed(body.mode, mode)

    user_text = apply_locale_orthography(body.text, body.locale)
    api_key_for = build_api_key_resolver(cfg, session, request.app.state.key_vault, uid)

    started = time.monotonic()
    try:
        completion = await post_process_for_mode(
            text=user_text,
            mode=mode,
            registry=registry,
            locale=body.locale,
            api_key_for=api_key_for,
            gate=request.app.state.local_gate,
        )
    except ProviderError:
        usage.record_error(session, uid, body.mode)
        raise
    duration_ms = int((time.monotonic() - started) * 1000)
    usage.record_success(session, uid, body.mode)  # /process: kein Audio

    return ProcessResponse(
        mode=body.mode,
        text=apply_locale_orthography(completion.text, body.locale),
        llm_provider=completion.provider,
        llm_model=completion.model,
        duration_ms=duration_ms,
    )
