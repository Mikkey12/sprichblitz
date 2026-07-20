"""Nutzer-scoped Routen: Profil + Per-User-Provider-Keys.

Antworten echoen **nie** den Key – ``GET /me`` liefert pro Provider nur einen
Boolean. ``PUT`` speichert den Key verschlüsselt, **ohne** ihn gegen den Provider
zu testen; ein fehlender/abgelehnter/unentschlüsselbarer Key fällt erst bei
Nutzung auf (412/422).
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field
from sqlmodel import Session

from ..auth import SettingsPrincipal, has_admin_scope, require_tls
from ..db.engine import get_session
from ..db.models import ProcessingLocation, User, utcnow
from ..models.api import Mode
from ..models.domain import ByoProvider
from ..services import mode_definitions, mode_overrides, provider_keys

router = APIRouter()


class MeResponse(BaseModel):
    name: str
    processing_location: str
    keys: dict[str, bool]
    is_admin: bool = False
    # Ob DIESE Session die Verwaltung erreicht (Rolle + Session-Scope). Die Konsole
    # blendet den Admin-Tab danach ein – siehe auth.has_admin_scope.
    admin_scope: bool = False


class SetKeyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str = Field(min_length=1, max_length=16_384)


class KeyStatusResponse(BaseModel):
    provider: str
    configured: bool


@router.get("/me", response_model=MeResponse)
def get_me(
    principal: SettingsPrincipal,
    session: Annotated[Session, Depends(get_session)],
) -> MeResponse:
    return MeResponse(
        name=principal.name,
        processing_location=principal.processing_location,
        keys=provider_keys.key_presence(session, int(principal.user_id)),
        is_admin=principal.is_admin,
        admin_scope=has_admin_scope(principal),
    )


@router.put("/me/keys/{provider}", response_model=KeyStatusResponse)
def put_key(
    provider: ByoProvider,
    body: SetKeyRequest,
    principal: SettingsPrincipal,
    session: Annotated[Session, Depends(get_session)],
    request: Request,
) -> KeyStatusResponse:
    require_tls(request)  # Secret-tragender Endpunkt: nie über unverschlüsseltes http.
    key = body.key.strip()
    if not key:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"error": "Key darf nicht leer sein", "code": "empty_key"},
        )
    provider_keys.set_user_key(
        session, request.app.state.key_vault, int(principal.user_id), provider.value, key
    )
    return KeyStatusResponse(provider=provider.value, configured=True)


@router.delete("/me/keys/{provider}", response_model=KeyStatusResponse)
def delete_key(
    provider: ByoProvider,
    principal: SettingsPrincipal,
    session: Annotated[Session, Depends(get_session)],
) -> KeyStatusResponse:
    provider_keys.delete_user_key(session, int(principal.user_id), provider.value)
    return KeyStatusResponse(provider=provider.value, configured=False)


class SettingsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Pydantic validiert gegen das Enum → ungültiger Wert = 422.
    processing_location: ProcessingLocation


@router.patch("/me/settings", response_model=MeResponse)
def patch_settings(
    body: SettingsRequest,
    principal: SettingsPrincipal,
    session: Annotated[Session, Depends(get_session)],
) -> MeResponse:
    user = session.get(User, int(principal.user_id))
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "User not found", "code": "user_not_found"},
        )
    user.processing_location = body.processing_location.value
    user.updated_at = utcnow()
    session.add(user)
    session.commit()
    return MeResponse(
        name=user.name,
        processing_location=user.processing_location,
        keys=provider_keys.key_presence(session, user.id),
        is_admin=user.is_admin,
        admin_scope=has_admin_scope(principal),
    )


# --- Per-User-Modi-Overrides (Etappe 4 / voll editierbar) --------------------
_DISPLAY_NAME_MAX = 80
_SYSTEM_PROMPT_MAX = 4000  # falls später Few-shot-Prompts nötig: auf 8000 heben
_LLM_MODEL_MAX = 200


class ModeOverrideRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    display_name: str | None = Field(default=None, max_length=_DISPLAY_NAME_MAX)
    system_prompt: str | None = Field(default=None, max_length=_SYSTEM_PROMPT_MAX)
    stt_provider: str | None = Field(default=None, min_length=1, max_length=64)
    llm_provider: str | None = Field(default=None, min_length=1, max_length=64)
    llm_model: str | None = Field(default=None, max_length=_LLM_MODEL_MAX)
    apply_llm: bool | None = None  # Tri-State: None = Default, sonst erzwungen
    enabled: bool = True


class ModeOverrideRaw(BaseModel):
    """Die ROHEN gespeicherten Override-Werte (für den Konsolen-Editor: faithful
    round-trippen statt beim Speichern den effektiven Default einzufrieren)."""

    display_name: str | None
    system_prompt: str | None
    stt_provider: str | None
    llm_provider: str | None
    llm_model: str | None
    apply_llm: bool | None
    enabled: bool


class ModeOverrideInfo(BaseModel):
    mode_key: Mode
    # Effektive Werte (Override ← config-Default), für unmittelbare Anzeige:
    display_name: str
    system_prompt: str | None
    stt_provider: str
    llm_provider: str | None
    llm_model: str | None
    apply_llm: bool
    enabled: bool
    is_overridden: bool
    # config-Defaults für „(Default: …)"-Platzhalter im Editor ohne Zweit-Fetch:
    default_display_name: str
    default_stt: str
    default_llm: str | None
    default_llm_model: str | None
    default_apply_llm: bool
    default_system_prompt: str | None
    override: ModeOverrideRaw | None = None  # roher Override (None = kein Override)


def _mode_info(mode_key: Mode, mode, override, registry) -> ModeOverrideInfo:
    eff = mode_overrides.apply_user_override(mode, override, registry=registry)
    return ModeOverrideInfo(
        mode_key=mode_key,
        display_name=mode_overrides.effective_display_name(mode, override),
        system_prompt=eff.system_prompt,
        stt_provider=eff.stt,
        llm_provider=eff.llm,
        llm_model=eff.llm_model,
        apply_llm=eff.apply_llm,
        enabled=mode_overrides.is_enabled(override),
        is_overridden=override is not None,
        default_display_name=mode.description,
        default_stt=mode.stt,
        default_llm=mode.llm,
        default_llm_model=mode.llm_model,
        default_apply_llm=mode.apply_llm,
        default_system_prompt=mode.system_prompt,
        override=(
            ModeOverrideRaw(
                display_name=override.display_name,
                system_prompt=override.system_prompt,
                stt_provider=override.stt_provider,
                llm_provider=override.llm_provider,
                llm_model=override.llm_model,
                apply_llm=override.apply_llm,
                enabled=override.enabled,
            )
            if override is not None
            else None
        ),
    )


def _require_mode(request: Request, session: Session, mode_key: Mode):
    """Ein Modus aus der EFFEKTIVEN Menge (config.yml + globale DB-Modi).

    Global deaktivierte sind hier nicht mehr enthalten – ein persoenlicher
    Override auf einen abgeschalteten Modus waere sinnlos.
    """
    mode = mode_definitions.resolve_mode(session, request.app.state.config, mode_key)
    if mode is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": f"Mode not configured: {mode_key}", "code": "mode_not_configured"},
        )
    return mode


@router.get("/me/modes", response_model=list[ModeOverrideInfo])
def get_modes(
    request: Request,
    principal: SettingsPrincipal,
    session: Annotated[Session, Depends(get_session)],
) -> list[ModeOverrideInfo]:
    cfg = request.app.state.config
    registry = request.app.state.registry
    overrides = mode_overrides.list_overrides(session, int(principal.user_id))
    out: list[ModeOverrideInfo] = []
    for name, mode in mode_definitions.effective_modes(session, cfg).items():
        out.append(_mode_info(name, mode, overrides.get(name), registry))
    return out


@router.put("/me/modes/{mode_key}", response_model=ModeOverrideInfo)
def put_mode(
    mode_key: Mode,
    body: ModeOverrideRequest,
    request: Request,
    principal: SettingsPrincipal,
    session: Annotated[Session, Depends(get_session)],
) -> ModeOverrideInfo:
    mode = _require_mode(request, session, mode_key)
    registry = request.app.state.registry
    if body.stt_provider is not None and body.stt_provider not in registry.stt:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "error": f"Unbekannter STT-Provider: {body.stt_provider}",
                "code": "invalid_stt_provider",
            },
        )
    if body.llm_provider is not None and body.llm_provider not in registry.llm:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "error": f"Unbekannter LLM-Provider: {body.llm_provider}",
                "code": "invalid_llm_provider",
            },
        )
    # Guard: effektiv aktives LLM verlangt effektiv Provider UND Prompt (sonst 500
    # zur Laufzeit). „Effektiv" = Override-Wert, sonst config-Default.
    eff_apply_llm = body.apply_llm if body.apply_llm is not None else mode.apply_llm
    eff_llm = body.llm_provider or mode.llm
    eff_prompt = body.system_prompt or mode.system_prompt
    if eff_apply_llm and (not eff_llm or not eff_prompt):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "error": "LLM-Nachbearbeitung verlangt einen LLM-Provider und einen System-Prompt",
                "code": "llm_requires_prompt_and_provider",
            },
        )
    override = mode_overrides.upsert_override(
        session,
        int(principal.user_id),
        mode_key,
        display_name=body.display_name,
        system_prompt=body.system_prompt,
        stt_provider=body.stt_provider,
        llm_provider=body.llm_provider,
        llm_model=body.llm_model,
        apply_llm=body.apply_llm,
        enabled=body.enabled,
    )
    return _mode_info(mode_key, mode, override, registry)


@router.delete("/me/modes/{mode_key}", response_model=ModeOverrideInfo)
def delete_mode(
    mode_key: Mode,
    request: Request,
    principal: SettingsPrincipal,
    session: Annotated[Session, Depends(get_session)],
) -> ModeOverrideInfo:
    mode = _require_mode(request, session, mode_key)
    registry = request.app.state.registry
    mode_overrides.delete_override(session, int(principal.user_id), mode_key)
    return _mode_info(mode_key, mode, None, registry)
