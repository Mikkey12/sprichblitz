"""Admin-Routen: Nutzer- und Token-Verwaltung über HTTP.

Dünner Wrapper um die erprobte CLI-Logik in :mod:`sprichblitz_backend.admin` –
die Geschäftsregeln (Duplikat-Check, Hash-only-Speicherung, Idempotenz) leben
dort und bleiben für CLI und API identisch.

Guard ist durchgehend :data:`AdminPrincipal` (Bearer mit ``is_admin`` oder eine
Console-Session mit ``scope=admin``). Token-Klartext verlässt den Server **genau
einmal** – bei ``POST /admin/users/{id}/tokens`` – und nur über TLS; danach liegt
nur noch der SHA-256-Hash in der DB und ist nicht rekonstruierbar.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func
from sqlmodel import Session, select

from ..admin import create_user as create_user_record
from ..admin import delete_user as delete_user_record
from ..admin import issue_token as issue_token_record
from ..admin import list_users as list_user_records
from ..admin import revoke_token as revoke_token_record
from ..auth import AdminPrincipal, hash_token, require_tls
from ..db.engine import get_session
from ..db.models import ApiToken, ModeDefinition, ProcessingLocation, UsageDaily, User, utcnow
from ..models.config_models import ModeConfig
from ..services import mode_definitions, mode_overrides

router = APIRouter()


class AdminUserInfo(BaseModel):
    id: int
    name: str
    display_name: str | None
    processing_location: str
    is_admin: bool
    disabled: bool
    created_at: datetime
    # Was an diesem Nutzer hängt – die Konsole benennt es in der Lösch-Bestätigung,
    # damit „Statistik weg" nicht stillschweigend passiert.
    token_count: int = 0
    usage_days: int = 0


class CreateUserRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=64)
    display_name: str | None = Field(default=None, max_length=80)
    is_admin: bool = False
    processing_location: ProcessingLocation = ProcessingLocation.online


class PatchUserRequest(BaseModel):
    """Alle Felder optional – nur Gesetztes wird angefasst (echtes PATCH)."""

    model_config = ConfigDict(extra="forbid")

    display_name: str | None = Field(default=None, max_length=80)
    processing_location: ProcessingLocation | None = None
    is_admin: bool | None = None
    disabled: bool | None = None


class TokenInfo(BaseModel):
    """Token-Metadaten – **nie** der Klartext."""

    id: int
    label: str | None
    revoked: bool
    last_used_at: datetime | None
    created_at: datetime


class IssueTokenRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str | None = Field(default=None, max_length=64)


class IssuedTokenResponse(BaseModel):
    """Antwort auf die Token-Ausgabe – ``token`` ist hier zum einzigen Mal sichtbar."""

    id: int
    label: str | None
    token: str


def _count_by_user(session: Session, model: type) -> dict[int, int]:
    """``user_id -> Anzahl`` in EINER gruppierten Abfrage (statt N+1 pro Nutzer)."""
    rows = session.exec(select(model.user_id, func.count()).group_by(model.user_id)).all()
    return dict(rows)


def _to_info(user: User, *, tokens: int = 0, usage_days: int = 0) -> AdminUserInfo:
    return AdminUserInfo(
        id=user.id,
        name=user.name,
        display_name=user.display_name,
        processing_location=user.processing_location,
        is_admin=user.is_admin,
        disabled=user.disabled,
        created_at=user.created_at,
        token_count=tokens,
        usage_days=usage_days,
    )


def _info_with_counts(session: Session, user: User) -> AdminUserInfo:
    return _to_info(
        user,
        tokens=_count_by_user(session, ApiToken).get(user.id, 0),
        usage_days=_count_by_user(session, UsageDaily).get(user.id, 0),
    )


def _require_user(session: Session, user_id: int) -> User:
    user = session.get(User, user_id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": f"User not found: {user_id}", "code": "user_not_found"},
        )
    return user


@router.get("/admin/users", response_model=list[AdminUserInfo])
def list_users(
    principal: AdminPrincipal,
    session: Annotated[Session, Depends(get_session)],
) -> list[AdminUserInfo]:
    """Alle Nutzer inkl. deaktivierter (Verwaltung muss sie reaktivieren können)."""
    tokens = _count_by_user(session, ApiToken)
    usage = _count_by_user(session, UsageDaily)
    return [
        _to_info(u, tokens=tokens.get(u.id, 0), usage_days=usage.get(u.id, 0))
        for u in list_user_records(session)
    ]


@router.post("/admin/users", response_model=AdminUserInfo, status_code=status.HTTP_201_CREATED)
def create_user(
    body: CreateUserRequest,
    principal: AdminPrincipal,
    session: Annotated[Session, Depends(get_session)],
) -> AdminUserInfo:
    """Neuen Nutzer anlegen. Der Name ist unique → Duplikat = 409."""
    try:
        user = create_user_record(
            session,
            body.name,
            is_admin=body.is_admin,
            location=body.processing_location.value,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error": str(exc), "code": "user_exists"},
        ) from exc
    if body.display_name is not None:
        user.display_name = body.display_name
        session.add(user)
        session.commit()
        session.refresh(user)
    return _to_info(user)


@router.patch("/admin/users/{user_id}", response_model=AdminUserInfo)
def patch_user(
    user_id: int,
    body: PatchUserRequest,
    principal: AdminPrincipal,
    session: Annotated[Session, Depends(get_session)],
) -> AdminUserInfo:
    """Nutzer ändern.

    Aussperr-Schutz: Ein Admin kann sich **selbst** weder deaktivieren noch die
    eigene Admin-Rolle entziehen. Sonst könnte der einzige Admin die Verwaltung
    unerreichbar machen und käme nur noch über die CLI zurück.
    """
    user = _require_user(session, user_id)
    is_self = user.id == int(principal.user_id)
    if is_self and body.disabled is True:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error": "Cannot disable yourself", "code": "self_lockout"},
        )
    if is_self and body.is_admin is False:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error": "Cannot drop your own admin role", "code": "self_lockout"},
        )
    if body.display_name is not None:
        user.display_name = body.display_name
    if body.processing_location is not None:
        user.processing_location = body.processing_location.value
    if body.is_admin is not None:
        user.is_admin = body.is_admin
    if body.disabled is not None:
        user.disabled = body.disabled
    user.updated_at = utcnow()
    session.add(user)
    session.commit()
    session.refresh(user)
    return _info_with_counts(session, user)


@router.delete("/admin/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_user(
    user_id: int,
    principal: AdminPrincipal,
    session: Annotated[Session, Depends(get_session)],
) -> Response:
    """Nutzer HART löschen – inkl. Tokens, Keys, Mode-Overrides und Statistik.

    Unwiderruflich und **inklusive `usage_daily`** (Entscheid 2026-07-16): Das
    Admin-Aggregat verliert die Historie dieses Nutzers rückwirkend. Wer den Zugang
    nur sperren will, setzt ``disabled`` – dabei bleiben alle Daten erhalten.

    Aussperr-Schutz wie bei :func:`patch_user`: das eigene Konto ist tabu.
    """
    user = _require_user(session, user_id)
    if user.id == int(principal.user_id):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error": "Cannot delete yourself", "code": "self_lockout"},
        )
    delete_user_record(session, user_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/admin/users/{user_id}/tokens", response_model=list[TokenInfo])
def list_tokens(
    user_id: int,
    principal: AdminPrincipal,
    session: Annotated[Session, Depends(get_session)],
) -> list[TokenInfo]:
    """Token-Metadaten eines Nutzers – ohne Klartext (den gibt es nur bei Ausgabe)."""
    _require_user(session, user_id)
    tokens = session.exec(
        select(ApiToken).where(ApiToken.user_id == user_id).order_by(ApiToken.id)
    ).all()
    return [
        TokenInfo(
            id=t.id,
            label=t.label,
            revoked=t.revoked,
            last_used_at=t.last_used_at,
            created_at=t.created_at,
        )
        for t in tokens
    ]


@router.post(
    "/admin/users/{user_id}/tokens",
    response_model=IssuedTokenResponse,
    status_code=status.HTTP_201_CREATED,
)
def issue_token(
    user_id: int,
    body: IssueTokenRequest,
    principal: AdminPrincipal,
    request: Request,
    session: Annotated[Session, Depends(get_session)],
) -> IssuedTokenResponse:
    """Token ausstellen – Klartext **einmalig** in der Antwort, TLS-Pflicht.

    Wie beim Key-Upload trägt die Antwort ein Secret → derselbe TLS-Guard. Danach
    liegt nur der SHA-256-Hash in der DB; ein verlorenes Token wird ersetzt, nicht
    wiederhergestellt.
    """
    require_tls(request)
    user = _require_user(session, user_id)
    plaintext = issue_token_record(session, user.name, label=body.label)
    # Über den Hash zurücklesen statt „neuestes Token" zu raten – eindeutig und
    # rennfrei, da ``token_hash`` unique ist.
    token = session.exec(
        select(ApiToken).where(ApiToken.token_hash == hash_token(plaintext))
    ).one()
    return IssuedTokenResponse(id=token.id, label=token.label, token=plaintext)


class AdminModeInfo(BaseModel):
    """Ein Modus, wie die Verwaltung ihn sieht – inkl. Herkunft."""

    mode_key: str
    description: str
    enabled: bool
    # Steht der Modus in config.yml? Bestimmt, ob „Löschen" oder „Deaktivieren"
    # möglich ist – die YAML kann eine API nicht anfassen.
    from_config: bool
    # Gibt es eine globale DB-Zeile? (Config-Modus ohne Zeile = unveränderter Kanon)
    has_global_override: bool
    stt: str
    llm: str | None
    llm_model: str | None
    apply_llm: bool
    language: str
    prompt_hint: str | None
    system_prompt: str | None
    fallback_stt: str | None


class ModeWriteRequest(BaseModel):
    """Felder eines globalen Modus. ``None`` = Config-Wert gilt (bei Config-Modi).

    Für einen eigenständigen DB-Modus sind ``description`` und ``stt`` Pflicht –
    ohne sie lässt sich keine ModeConfig bauen. Das prüft die Route.
    """

    model_config = ConfigDict(extra="forbid")

    description: str | None = Field(default=None, max_length=500)
    stt: str | None = Field(default=None, min_length=1, max_length=64)
    language: str | None = Field(default=None, min_length=2, max_length=35)
    prompt_hint: str | None = Field(default=None, max_length=1000)
    apply_llm: bool | None = None
    llm: str | None = Field(default=None, min_length=1, max_length=64)
    llm_model: str | None = Field(default=None, min_length=1, max_length=200)
    output_prefill: str | None = Field(default=None, max_length=1000)
    system_prompt: str | None = Field(default=None, max_length=4000)
    fallback_stt: str | None = Field(default=None, min_length=1, max_length=64)
    enabled: bool = True


_MODE_KEY_RE = re.compile(r"^[a-z][a-z0-9_]{1,31}$")


def _validate_providers(request: Request, body: ModeWriteRequest) -> None:
    registry = request.app.state.registry
    for field, pool in (("stt", registry.stt), ("fallback_stt", registry.stt), ("llm", registry.llm)):
        value = getattr(body, field)
        if value is not None and value not in pool:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={
                    "error": f"Unknown provider for {field}: {value}",
                    "code": "unknown_provider",
                },
            )


def _mode_info(
    mode_key: str, mode: ModeConfig, *, from_config: bool, definition: ModeDefinition | None
) -> AdminModeInfo:
    return AdminModeInfo(
        mode_key=mode_key,
        description=mode.description,
        enabled=definition.enabled if definition is not None else True,
        from_config=from_config,
        has_global_override=definition is not None,
        stt=mode.stt,
        llm=mode.llm,
        llm_model=mode.llm_model,
        apply_llm=mode.apply_llm,
        language=mode.language,
        prompt_hint=mode.prompt_hint,
        system_prompt=mode.system_prompt,
        fallback_stt=mode.fallback_stt,
    )


@router.get("/admin/modes", response_model=list[AdminModeInfo])
def list_modes(
    request: Request,
    principal: AdminPrincipal,
    session: Annotated[Session, Depends(get_session)],
) -> list[AdminModeInfo]:
    """Alle Modi – auch die global deaktivierten.

    ``effective_modes`` wirft deaktivierte bewusst raus (nach aussen existieren sie
    nicht). Die Verwaltung muss sie trotzdem sehen, sonst könnte man sie nie wieder
    einschalten – deshalb hier die Config plus ALLE Definitionen, nicht die
    effektive Menge.
    """
    cfg = request.app.state.config
    definitions = mode_definitions.list_definitions(session)
    out: list[AdminModeInfo] = []
    for mode_key in sorted(set(cfg.modes) | set(definitions)):
        definition = definitions.get(mode_key)
        base = cfg.modes.get(mode_key)
        if base is not None:
            mode = mode_definitions.merge_into(base, definition)
        else:
            mode = mode_definitions.build_standalone(definition)
            if mode is None:
                continue  # unvollständige Zeile – build_standalone hat geloggt
        out.append(
            _mode_info(mode_key, mode, from_config=base is not None, definition=definition)
        )
    return out


@router.put("/admin/modes/{mode_key}", response_model=AdminModeInfo)
def put_mode(
    mode_key: str,
    body: ModeWriteRequest,
    request: Request,
    principal: AdminPrincipal,
    session: Annotated[Session, Depends(get_session)],
) -> AdminModeInfo:
    """Globalen Modus anlegen oder ändern – gilt für ALLE Nutzer.

    Bei einem Modus aus ``config.yml`` überschreiben gesetzte Felder die YAML;
    ``None`` heisst „Config-Wert gilt". Bei einem neuen Modus (nicht in der YAML)
    sind ``description`` und ``stt`` Pflicht.
    """
    cfg = request.app.state.config
    from_config = mode_key in cfg.modes
    if not from_config and not _MODE_KEY_RE.match(mode_key):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "error": "Mode key must be lowercase a-z, digits and _ (2–32 chars)",
                "code": "invalid_mode_key",
            },
        )
    if not from_config and (not body.description or not body.stt):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "error": "A new mode needs description and stt",
                "code": "incomplete_mode",
            },
        )
    _validate_providers(request, body)
    definition = mode_definitions.upsert_definition(
        session, mode_key, **body.model_dump()
    )
    mode = mode_definitions.resolve_mode(session, cfg, mode_key)
    if mode is None:  # global deaktiviert → aus der effektiven Menge raus
        base = cfg.modes.get(mode_key)
        mode = (
            mode_definitions.merge_into(base, definition)
            if base is not None
            else mode_definitions.build_standalone(definition)
        )
    return _mode_info(mode_key, mode, from_config=from_config, definition=definition)


@router.delete("/admin/modes/{mode_key}", status_code=status.HTTP_204_NO_CONTENT)
def delete_mode(
    mode_key: str,
    request: Request,
    principal: AdminPrincipal,
    session: Annotated[Session, Depends(get_session)],
) -> Response:
    """Einen NUR in der DB angelegten Modus löschen.

    Für Modi aus ``config.yml`` ist das 409: Die YAML-Zeilen kann eine API nicht
    entfernen, ein „Löschen" wäre also gelogen. Der ehrliche Weg dort ist
    ``enabled=false`` (PUT) – der Modus verschwindet überall, die Datei bleibt.
    """
    cfg = request.app.state.config
    if mode_key in cfg.modes:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": (
                    f"Mode '{mode_key}' comes from config.yml and cannot be deleted via API. "
                    "Disable it instead (enabled=false)."
                ),
                "code": "mode_from_config",
            },
        )
    if not mode_definitions.delete_definition(session, mode_key):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": f"Mode not found: {mode_key}", "code": "mode_not_found"},
        )
    # Verwaiste per-User-Overrides desselben mode_key mitlöschen (sonst „erben"
    # alte Nutzer sie, falls der Key später neu vergeben wird).
    mode_overrides.delete_all_for_mode(session, mode_key)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete("/admin/tokens/{token_id}", status_code=status.HTTP_204_NO_CONTENT)
def revoke_token(
    token_id: int,
    principal: AdminPrincipal,
    session: Annotated[Session, Depends(get_session)],
) -> Response:
    """Token widerrufen. Wirkt sofort – auch auf daraus abgeleitete Console-Sessions
    (``tid``-Bindung, siehe :func:`sprichblitz_backend.auth._resolve_console_cookie`)."""
    if not revoke_token_record(session, token_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": f"Token not found: {token_id}", "code": "token_not_found"},
        )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
