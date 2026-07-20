from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from sqlmodel import Session

from ..auth import CurrentPrincipal
from ..db.engine import get_session
from ..models.api import FullResponse, Mode
from ..services import mode_definitions, mode_overrides, usage
from ..services.full_pipeline import full_pipeline
from ..services.provider_keys import build_api_key_resolver
from ..util.errors import ModeNotConfigured, ProviderError
from .transcribe import _format_hint

router = APIRouter()


@router.post("/full", response_model=FullResponse)
async def full_endpoint(
    request: Request,
    principal: CurrentPrincipal,
    session: Annotated[Session, Depends(get_session)],
    file: Annotated[UploadFile, File()],
    mode: Annotated[Mode, Form()],
    stt: Annotated[str | None, Form()] = None,
    llm: Annotated[str | None, Form()] = None,
    llm_model: Annotated[str | None, Form()] = None,
    locale: Annotated[str | None, Form()] = None,
) -> FullResponse:
    uid = int(principal.user_id)
    request.app.state.rate_limiter.check(uid)  # 429 VOR Gate/Pipeline

    audio_bytes = await file.read()
    audio_format = _format_hint(file)

    cfg = request.app.state.config
    registry = request.app.state.registry
    api_key_for = build_api_key_resolver(cfg, session, request.app.state.key_vault, uid)
    mode_override = mode_overrides.get_override(session, uid, mode)

    # Modi kommen aus config.yml UND der DB (global) – die effektive Menge kennt
    # nur der Resolver. Global deaktivierte sind hier schlicht weg → 400.
    base_mode = mode_definitions.resolve_mode(session, cfg, mode)
    if base_mode is None:
        raise ModeNotConfigured(mode)

    try:
        response = await full_pipeline(
            audio_bytes=audio_bytes,
            audio_format=audio_format,
            mode_name=mode,
            base_mode=base_mode,
            cfg=cfg,
            registry=registry,
            stt_override=stt,
            llm_override=llm,
            llm_model_override=llm_model,
            locale=locale,
            location=principal.processing_location,
            mode_override=mode_override,
            gate=request.app.state.local_gate,
            api_key_for=api_key_for,
        )
    except ProviderError:
        # Nur echte Provider-Fehler zählen als errors; 412/429/503 NICHT.
        usage.record_error(session, uid, mode)
        raise
    usage.record_success(session, uid, mode, audio_seconds=response.audio_seconds)
    return response
