from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Annotated

from fastapi import Cookie, Depends, Header, HTTPException, Request, status
from sqlmodel import Session, select

from .db.engine import get_session
from .db.models import ApiToken, User, utcnow
from .services.cf_access import CfAccessError
from .services.console_session import SCOPE_ADMIN, ConsoleSessionError

# last_used_at wird höchstens 1×/Minute geschrieben (Schreib-Drossel).
_LAST_USED_THROTTLE = timedelta(seconds=60)


@dataclass(frozen=True)
class AuthPrincipal:
    """Wer hinter einem gültigen Bearer-Token steckt.

    Ab Etappe 1 echte Per-User-Identität aus SQLite: ``user_id`` ist die
    String-Form von ``users.id``; ``name``/``is_admin``/``processing_location``
    stammen aus dem Nutzerdatensatz. ``scopes`` bleibt als Vorwärts-Kompat-Feld
    (heute Wildcard). Routen, die nur ``Depends(verify_bearer)`` als Guard
    nutzen, ignorieren den Wert; ab Etappe 2 hängen Handler den Principal via
    :data:`CurrentPrincipal` in die Signatur. ``via_console_cookie`` markiert
    Cookie-Auth (Settings-Konsole) → erlaubt Routen, den Cookie-Zugriff enger als
    Bearer zu scopen (z. B. ``/stats`` eigen-scopen statt Admin-Aggregat).

    ``token_id`` ist das ``ApiToken``, das den Request legitimiert – beim Bearer
    direkt, auf dem Cookie-Pfad der Bootstrap-Bearer (``tid``-Bindung). Damit kann
    ``POST /console/session`` die Bindung bis in die Session durchreichen.
    ``console_scope`` trägt die Reichweite der Cookie-Session (``user``/``admin``)
    und ist auf dem Bearer-Pfad ``None``.
    """

    user_id: str = "default"
    name: str = "default"
    is_admin: bool = False
    processing_location: str = "local"
    via_console_cookie: bool = False
    token_id: int | None = None
    console_scope: str | None = None
    scopes: frozenset[str] = field(default_factory=lambda: frozenset({"*"}))


class AuthError(HTTPException):
    def __init__(self, detail: str = "Authentication failed") -> None:
        super().__init__(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=detail,
            headers={"WWW-Authenticate": 'Bearer realm="sprichblitz"'},
        )


class AdminRequired(HTTPException):
    """403, wenn ein gültig authentifizierter Principal keine Admin-Rechte hat.

    Bewusst 403 (nicht 401): „wer bist du" ist geklärt, es fehlt die Rolle.
    """

    def __init__(self, detail: str = "Admin privileges required") -> None:
        super().__init__(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"error": detail, "code": "admin_required"},
        )


class CfAccessDenied(HTTPException):
    """403, wenn auf dem Tunnel-Pfad das Cloudflare-Access-JWT fehlt/ungültig ist.

    Der Bearer ist gültig (Identität ok) – nur das Edge-Gate verweigert; bewusst
    403 (nicht 401), um „wer bist du" (Bearer) von „SSO-Gate" zu trennen.
    """

    def __init__(self, detail: str = "Cloudflare Access denied") -> None:
        super().__init__(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"error": detail, "code": "cf_access_denied"},
        )


def hash_token(token: str) -> str:
    """SHA-256-Hex eines Bearer-Tokens.

    Tokens sind hochentropisch (``secrets.token_urlsafe(48)`` ≈ 384 Bit) →
    schnelles Hashing ohne Salt genügt (Brute-Force unmöglich, Rainbow-Tables
    sinnlos). Der Lookup läuft per indiziertem ``WHERE token_hash = ?``.
    """
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _extract_bearer(authorization: str | None) -> str:
    if not authorization:
        raise AuthError("Missing Authorization header")
    parts = authorization.split(None, 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise AuthError("Authorization header must be 'Bearer <token>'")
    presented = parts[1].strip()
    if not presented:
        raise AuthError("Empty bearer token")
    return presented


def _touch_last_used(session: Session, api_token: ApiToken) -> None:
    """Gedrosseltes (max. 1×/Min) Update von ``last_used_at`` – best effort.

    Ein fehlgeschlagenes Telemetrie-Update darf die Authentifizierung nicht
    scheitern lassen.
    """
    now = utcnow()
    if (
        api_token.last_used_at is not None
        and (now - api_token.last_used_at) < _LAST_USED_THROTTLE
    ):
        return
    try:
        api_token.last_used_at = now
        session.add(api_token)
        session.commit()
    except Exception:
        session.rollback()


def _principal_from_user(
    user: User | None,
    *,
    via_console_cookie: bool = False,
    token_id: int | None = None,
    console_scope: str | None = None,
) -> AuthPrincipal:
    """User-Datensatz → Principal; ``None``/``disabled`` → einheitliche 401
    (kein Leak, welche Bedingung verletzt ist)."""
    if user is None or user.disabled:
        raise AuthError("Invalid token")
    return AuthPrincipal(
        user_id=str(user.id),
        name=user.name,
        is_admin=user.is_admin,
        processing_location=user.processing_location,
        via_console_cookie=via_console_cookie,
        token_id=token_id,
        console_scope=console_scope,
    )


def resolve_principal(session: Session, presented_token: str) -> AuthPrincipal:
    """Token → :class:`AuthPrincipal` via indiziertem Hash-Lookup.

    Unbekannt, ``revoked`` und ``disabled`` liefern bewusst dieselbe 401-Meldung.
    """
    token_hash = hash_token(presented_token)
    api_token = session.exec(
        select(ApiToken).where(ApiToken.token_hash == token_hash)
    ).first()
    if api_token is None or api_token.revoked:
        raise AuthError("Invalid token")
    principal = _principal_from_user(
        session.get(User, api_token.user_id), token_id=api_token.id
    )
    _touch_last_used(session, api_token)
    return principal


def _resolve_console_cookie(request: Request, session: Session, cookie: str) -> AuthPrincipal:
    """Cookie-Pfad – nur additiv, wenn KEIN Bearer vorliegt.

    CSRF-Schutz: verlangt zusätzlich den Custom-Header ``X-Sb-Console`` (cross-site
    nicht setzbar), zusammen mit ``SameSite=Strict`` am Cookie.

    Pro Request werden BEIDE Widerrufswege frisch aus der DB geprüft: ``user.disabled``
    **und** – über die ``tid``-Bindung (2026-07-16) – ``api_token.revoked`` des
    Bootstrap-Bearers. Damit beendet auch das Widerrufen eines EINZELNEN Tokens die
    daraus abgeleiteten Sessions SOFORT (kein Lag bis TTL); das Cookie ist so stark
    wie der Bearer, aus dem es entstand. ``exp`` begrenzt nur die Sitzungsdauer.
    """
    if request.headers.get("x-sb-console") is None:
        raise AuthError("Missing X-Sb-Console header")
    signer = getattr(request.app.state, "console_signer", None)
    if signer is None:
        raise AuthError("Console session unavailable")
    try:
        claims = signer.verify(cookie)
    except ConsoleSessionError as exc:
        raise AuthError("Invalid session") from exc
    # tid-Bindung: das Bootstrap-Token muss noch existieren, gültig sein und
    # weiterhin demselben Nutzer gehören (Defense-in-Depth gegen Claim-Drift).
    api_token = session.get(ApiToken, claims.token_id)
    if api_token is None or api_token.revoked or api_token.user_id != claims.user_id:
        raise AuthError("Invalid session")
    return _principal_from_user(
        session.get(User, claims.user_id),
        via_console_cookie=True,
        token_id=claims.token_id,
        console_scope=claims.scope,
    )


def require_tls(request: Request) -> None:
    """403 ``tls_required``, wenn der (rekonstruierte) Scheme nicht https ist.

    Für Secret-tragende Endpunkte (Key-Upload, Session-Bootstrap). Auf dem Tunnel
    rekonstruiert die TrustedIngress-Middleware https aus ``X-Forwarded-Proto``;
    der LAN-/Loopback-Pfad bleibt http und wird hier abgewiesen.
    """
    if request.url.scheme != "https":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"error": "TLS required for this endpoint", "code": "tls_required"},
        )


def _enforce_cf_access(request: Request, cf_access_jwt: str | None) -> None:
    """``token_plus_cf_access``: auf dem vertrauenswürdigen Tunnel-Ingress
    zusätzlich das Cloudflare-Access-JWT verlangen.

    LAN-Pfad (untrusted Peer): CF-Header werden **ignoriert** → der Bearer genügt
    allein (kein Header-Trust-Bypass; ein geleakter JWT ist auf dem LAN wertlos).
    ``token_only``: No-op. Greift nur in dieser Dependency → ``/health`` u. Ä.
    (ohne Auth) bleiben ausgenommen.
    """
    if getattr(request.app.state, "auth_mode", "token_only") != "token_plus_cf_access":
        return
    if not getattr(request.state, "via_trusted_ingress", False):
        return
    if cf_access_jwt is None:
        raise CfAccessDenied("Missing Cf-Access-Jwt-Assertion")
    try:
        request.app.state.cf_verifier.verify(cf_access_jwt)
    except CfAccessError as exc:
        raise CfAccessDenied("Invalid Cf-Access-Jwt-Assertion") from exc


def verify_bearer(
    request: Request,
    session: Annotated[Session, Depends(get_session)],
    authorization: Annotated[str | None, Header()] = None,
    cf_access_jwt: Annotated[str | None, Header(alias="Cf-Access-Jwt-Assertion")] = None,
) -> AuthPrincipal:
    """FastAPI-Dependency: validiert ``Authorization: Bearer <token>`` gegen die DB;
    in ``token_plus_cf_access`` zusätzlich das Access-JWT auf dem Tunnel-Pfad.

    **Bearer-only** – der Default-Guard für alle Endpunkte außer den Self-Service-
    Settings. Das Console-Cookie greift hier bewusst NICHT (Least Privilege:
    Diktat/Stats/Config bleiben dem hochentropischen Bearer vorbehalten; das
    Browser-Credential erreicht nur ``/me/*`` via :data:`SettingsPrincipal`). Auch
    der Session-Bootstrap (``POST /console/session``) nutzt diesen Guard → ein
    Cookie kann sich nicht selbst verlängern.

    Synchron → FastAPI führt die Dependency im Threadpool aus; der SQLite-Lookup
    (und der sync JWKS-Fetch) blockiert den Event-Loop nicht.
    """
    principal = resolve_principal(session, _extract_bearer(authorization))
    _enforce_cf_access(request, cf_access_jwt)
    return principal


def verify_settings_principal(
    request: Request,
    session: Annotated[Session, Depends(get_session)],
    authorization: Annotated[str | None, Header()] = None,
    cf_access_jwt: Annotated[str | None, Header(alias="Cf-Access-Jwt-Assertion")] = None,
    sb_console: Annotated[str | None, Cookie()] = None,
) -> AuthPrincipal:
    """Wie :func:`verify_bearer`, aber zusätzlich über das Console-Session-Cookie.

    Basis für die cookie-fähigen Guards: die Self-Service-Settings (``/me/*``)
    hängen direkt hier, die Verwaltung (``/admin/*``) über :func:`verify_admin_principal`
    mit zusätzlicher Scope-Prüfung. Diktat/Stats/Config bleiben dem Bearer
    vorbehalten (:func:`verify_bearer`).

    Präzedenz: liegt ein ``Authorization``-Header vor, läuft exakt der Bearer-Pfad
    (RAISEt bei ungültig → kein Fallthrough); nur ohne Bearer greift additiv der
    Cookie-Pfad.
    """
    if authorization is not None:
        principal = resolve_principal(session, _extract_bearer(authorization))
    elif sb_console is not None:
        principal = _resolve_console_cookie(request, session, sb_console)
    else:
        raise AuthError("Missing Authorization header")
    _enforce_cf_access(request, cf_access_jwt)
    return principal


def has_admin_scope(principal: AuthPrincipal) -> bool:
    """Ob dieser Principal ``/admin/*`` erreicht – die Wahrheit für Guard UND UI.

    ``GET /me`` spiegelt das nach ``admin_scope``, damit die Konsole den Admin-Tab
    nur dann zeigt, wenn er auch funktioniert. Bewusst EINE Quelle: sonst driften
    Guard und Anzeige auseinander.
    """
    if not principal.is_admin:
        return False
    return not principal.via_console_cookie or principal.console_scope == SCOPE_ADMIN


def verify_admin_principal(
    principal: Annotated[AuthPrincipal, Depends(verify_settings_principal)],
) -> AuthPrincipal:
    """Guard für ``/admin/*`` – Nutzer-/Token-Verwaltung nur für Admins.

    Bearer-Pfad: ``is_admin`` genügt. Cookie-Pfad: zusätzlich ``scope=admin`` – eine
    Self-Service-Session erreicht die Verwaltung NIE, auch wenn der Nutzer Admin ist.
    Der Admin-Scope wird nur beim Bootstrap geprägt (``POST /console/session``, das
    selbst Bearer-only ist) → ein Cookie kann sich nicht selbst hochstufen. Zusammen
    mit der ``tid``-Bindung (Revoke wirkt sofort) und dem kürzeren Admin-TTL ist das
    Browser-Credential hier so stark wie der Bearer, aus dem es entstand.

    Bewusst 403 (nicht 404): der Bearer ist gültig, nur die Rolle fehlt.
    """
    if not principal.is_admin:
        raise AdminRequired()
    if not has_admin_scope(principal):
        raise AdminRequired("Console session lacks admin scope")
    return principal


CurrentPrincipal = Annotated[AuthPrincipal, Depends(verify_bearer)]
SettingsPrincipal = Annotated[AuthPrincipal, Depends(verify_settings_principal)]
AdminPrincipal = Annotated[AuthPrincipal, Depends(verify_admin_principal)]
