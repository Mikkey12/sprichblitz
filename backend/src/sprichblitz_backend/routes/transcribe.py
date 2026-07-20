from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from sqlmodel import Session

from ..auth import CurrentPrincipal
from ..db.engine import get_session
from ..models.api import Mode, TranscribeResponse
from ..services import mode_definitions, mode_overrides, usage
from ..services.full_pipeline import transcribe_only
from ..services.provider_keys import build_api_key_resolver
from ..util.errors import ModeNotConfigured, ProviderError

router = APIRouter()


@router.post("/transcribe", response_model=TranscribeResponse)
async def transcribe_endpoint(
    request: Request,
    principal: CurrentPrincipal,
    session: Annotated[Session, Depends(get_session)],
    file: Annotated[UploadFile, File()],
    mode: Annotated[Mode, Form()],
    stt: Annotated[str | None, Form()] = None,
    locale: Annotated[str | None, Form()] = None,
) -> TranscribeResponse:
    uid = int(principal.user_id)
    request.app.state.rate_limiter.check(uid)  # 429 VOR Gate/Pipeline

    audio_bytes = await file.read()
    audio_format = _format_hint(file)

    cfg = request.app.state.config
    registry = request.app.state.registry
    api_key_for = build_api_key_resolver(cfg, session, request.app.state.key_vault, uid)
    mode_override = mode_overrides.get_override(session, uid, mode)

    # Effektive Modi = config.yml + globale DB-Definitionen; global deaktivierte
    # existieren hier nicht mehr → 400 wie ein unbekannter Modus.
    base_mode = mode_definitions.resolve_mode(session, cfg, mode)
    if base_mode is None:
        raise ModeNotConfigured(mode)

    try:
        response = await transcribe_only(
            audio_bytes=audio_bytes,
            audio_format=audio_format,
            mode_name=mode,
            base_mode=base_mode,
            cfg=cfg,
            registry=registry,
            stt_override=stt,
            locale=locale,
            location=principal.processing_location,
            mode_override=mode_override,
            gate=request.app.state.local_gate,
            api_key_for=api_key_for,
        )
    except ProviderError:
        usage.record_error(session, uid, mode)
        raise
    usage.record_success(session, uid, mode, audio_seconds=response.audio_seconds)
    return response


def _format_hint(file: UploadFile) -> str | None:
    """Infer the audio format from the upload filename or content-type."""
    if file.filename:
        ext = file.filename.rsplit(".", 1)[-1].lower()
        if ext in {"wav", "mp3", "m4a", "mp4", "aac"}:
            return ext
    if file.content_type:
        ct = file.content_type.lower()
        if "wav" in ct:
            return "wav"
        if "mpeg" in ct or "mp3" in ct:
            return "mp3"
        if "mp4" in ct or "m4a" in ct or "aac" in ct:
            return "m4a"
    return None
