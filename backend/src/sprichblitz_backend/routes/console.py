"""Console-Session-Bootstrap.

Der native Shell tauscht seinen Bearer gegen einen kurzlebigen Single-Use-Code
(``POST /console/session``); die Webview löst den Code ein (``GET /console/bootstrap``)
und bekommt dabei das HttpOnly-Session-Cookie + einen Redirect auf ``/app/``. So
gelangt der durable Bearer NIE in die Webview – nur der 256-bit-Code in der URL,
single-use und ~60s gültig.

Der Code trägt neben der ``user_id`` auch die ``token_id`` des Bootstrap-Bearers
(Token-Bindung) und den ``scope`` der entstehenden Session bis zum Mint durch.
"""

from __future__ import annotations

import hmac
from typing import Annotated

from fastapi import APIRouter, Cookie, Header, HTTPException, Request, Response, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, ConfigDict, Field

from ..auth import AdminRequired, AuthError, AuthPrincipal, CurrentPrincipal, require_tls
from ..services.console_session import SCOPE_ADMIN, SCOPE_USER, SCOPES

router = APIRouter()

_COOKIE_NAME = "sb_console"
# Anti-Session-Fixation: der native Client setzt diesen Nonce als Cookie in der
# WebView und schickt denselben Wert als X-Sb-Boot-Nonce beim Session-Erstellen.
# Der Redeem verlangt Cookie == an den Code gebundener Nonce.
_NONCE_COOKIE = "sb_boot"


class BootstrapCodeResponse(BaseModel):
    code: str
    expires_in: int
    scope: str


class SessionRequest(BaseModel):
    """Optionaler Body. ``scope=None`` → Default je Rolle (siehe :func:`_resolve_scope`)."""

    model_config = ConfigDict(extra="forbid")

    scope: str | None = Field(default=None, max_length=16)


def _resolve_scope(requested: str | None, principal: AuthPrincipal) -> str:
    """Gewünschten Scope validieren bzw. den Default je Rolle bestimmen.

    Ohne Angabe bekommt ein Admin eine Verwaltungs-Session, alle anderen eine
    Self-Service-Session. Der Default ist bewusst rollenabhängig statt fix
    ``user``: so erreicht der Admin-Tab den bestehenden nativen Client, der den
    Parameter nicht kennt – ohne Client-Änderung. Wer bewusst abrüsten will,
    schickt ``scope="user"`` (Opt-down); ``scope="admin"`` ohne Admin-Rolle ist 403.
    """
    if requested is None:
        return SCOPE_ADMIN if principal.is_admin else SCOPE_USER
    if requested not in SCOPES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"error": f"Unknown console scope: {requested}", "code": "unknown_scope"},
        )
    if requested == SCOPE_ADMIN and not principal.is_admin:
        raise AdminRequired("Admin scope requires an admin user")
    return requested


@router.post("/console/session", response_model=BootstrapCodeResponse)
def create_session(
    principal: CurrentPrincipal,
    request: Request,
    body: SessionRequest | None = None,
    x_sb_boot_nonce: Annotated[str | None, Header()] = None,
) -> BootstrapCodeResponse:
    """Bearer → kurzlebiger Single-Use-Bootstrap-Code (KEIN Set-Cookie hier).

    Bearer-only (ein Cookie kann sich nicht selbst hochstufen oder verlängern),
    TLS-Pflicht, leichter Rate-Schutz. Die Webview löst den Code per
    ``GET /console/bootstrap`` ein.

    ``X-Sb-Boot-Nonce`` (optional) bindet den Code an einen Client-Nonce gegen
    Session-Fixation: der Redeem verlangt dann das gleichnamige ``sb_boot``-Cookie
    (das der native Client in der WebView setzt). Alt-Clients ohne Nonce laufen
    unverändert (es sei denn ``auth.require_console_nonce`` erzwingt ihn).
    """
    require_tls(request)
    limiter = getattr(request.app.state, "rate_limiter", None)
    if limiter is not None:
        limiter.check(int(principal.user_id))
    if principal.token_id is None:  # pragma: no cover – verify_bearer setzt das immer
        raise AuthError("Bearer token not resolvable")
    scope = _resolve_scope(body.scope if body is not None else None, principal)
    store = request.app.state.console_bootstrap
    nonce = x_sb_boot_nonce.strip() if x_sb_boot_nonce else None
    return BootstrapCodeResponse(
        code=store.issue(
            int(principal.user_id), token_id=principal.token_id, scope=scope, nonce=nonce or None
        ),
        expires_in=store.ttl_s,
        scope=scope,
    )


def _bad_code() -> HTTPException:
    # Bewusst dieselbe Meldung wie „unbekannter/abgelaufener Code": ein
    # Nonce-Mismatch soll nicht verraten, dass der Code selbst gültig war.
    return HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail={"error": "Invalid or expired bootstrap code", "code": "invalid_bootstrap_code"},
    )


@router.get("/console/bootstrap")
def bootstrap(
    code: str,
    request: Request,
    sb_boot: Annotated[str | None, Cookie()] = None,
) -> RedirectResponse:
    """Löst den Single-Use-Code ein → setzt das Session-Cookie + 302 auf ``/app/``.

    KEINE Auth-Dependency: der Code IST die Authentifizierung (256-bit, single-use,
    ~60s). TLS-Pflicht (Secure-Cookie). ``Referrer-Policy: no-referrer``, damit der
    Code in der URL nicht via ``Referer`` an ``/app/`` + dessen Ressourcen leakt.

    Anti-Session-Fixation: Ist der Code an einen Nonce gebunden, muss das
    ``sb_boot``-Cookie diesen Nonce tragen (kann ein Angreifer im Browser des
    Opfers nicht setzen). Nonce-lose Codes werden bei
    ``auth.require_console_nonce`` abgelehnt, sonst wie bisher akzeptiert.
    """
    require_tls(request)
    grant = request.app.state.console_bootstrap.redeem(code)
    if grant is None:
        raise _bad_code()

    require_nonce = getattr(request.app.state, "require_console_nonce", False)
    if grant.nonce is not None:
        # Konstant-Zeit-Vergleich; fehlendes/falsches Cookie → 400 (Fixation-Schutz).
        if sb_boot is None or not hmac.compare_digest(sb_boot, grant.nonce):
            raise _bad_code()
    elif require_nonce:
        raise _bad_code()

    signer = request.app.state.console_signer
    response = RedirectResponse(url="/app/", status_code=status.HTTP_302_FOUND)
    response.set_cookie(
        _COOKIE_NAME,
        signer.mint(grant.user_id, token_id=grant.token_id, scope=grant.scope),
        max_age=signer.ttl_for(grant.scope),
        httponly=True,
        secure=True,
        samesite="strict",
        path="/",
    )
    # Den einmaligen Nonce nach Gebrauch aus der WebView entfernen.
    response.delete_cookie(_NONCE_COOKIE, path="/console", secure=True, samesite="strict")
    response.headers["Referrer-Policy"] = "no-referrer"
    return response


@router.delete("/console/session", status_code=204)
def delete_session() -> Response:
    """Idempotenter Logout: löscht das Cookie (kein Auth-Zwang)."""
    response = Response(status_code=204)
    response.delete_cookie(
        _COOKIE_NAME, path="/", httponly=True, secure=True, samesite="strict"
    )
    return response
