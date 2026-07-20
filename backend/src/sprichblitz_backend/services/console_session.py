"""Kurzlebige, signierte Console-Session (als Cookie genutzt).

Stateless: ein HS256-JWT, signiert mit einem aus ``SPRICHBLITZ_SECRET_KEY``
**abgeleiteten** Sub-Key (via :meth:`KeyVault.derive_subkey`, HKDF-SHA256). Der
Fernet-Vault-Key wird NIE direkt zum Signieren benutzt → Schlüssel-Trennung
Vault≠Session (kein neuer Secret; ``SPRICHBLITZ_SECRET_KEY`` bleibt das einzige
Backup).

Das Token trägt ``sub`` (user_id), ``tid`` (ApiToken-ID des Bootstrap-Bearers),
``scope`` und ``exp``. Die ``tid``-Bindung (2026-07-16) hebt die zuvor geparkte
Token-Bindung auf: der Cookie-Pfad prüft pro Request BEIDES frisch aus der DB –
``user.disabled`` **und** ``api_token.revoked``. Ein einzelner Token-Revoke killt
damit sofort auch alle daraus abgeleiteten Sessions (vorher: Lag bis TTL, nur
„Nutzer deaktivieren" wirkte sofort).

``scope`` trennt Self-Service von Verwaltung:

* ``user``  – Reichweite ``/me/*`` (unverändert, Least Privilege).
* ``admin`` – zusätzlich ``/admin/*``. Wird beim Bootstrap nur für ``is_admin``-
  Nutzer geprägt und bekommt ein **kürzeres TTL** (:data:`ADMIN_TTL_S`), weil ein
  Browser-Credential mit Verwaltungsreichweite kürzer leben soll.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

import jwt

# Domänen-Trennung der HKDF-Ableitung; auch von app.py für derive_subkey genutzt.
CONSOLE_SESSION_INFO = b"sprichblitz-console-session"
_ALG = "HS256"
DEFAULT_TTL_S = 1800  # 30 min – Self-Service-Session (/me/*)
ADMIN_TTL_S = 900  # 15 min – Verwaltungs-Session (/admin/*)

SCOPE_USER = "user"
SCOPE_ADMIN = "admin"
SCOPES = frozenset({SCOPE_USER, SCOPE_ADMIN})


class ConsoleSessionError(Exception):
    """Session-Cookie fehlt, ist abgelaufen oder manipuliert."""


@dataclass(frozen=True)
class ConsoleSessionClaims:
    """Verifizierter Cookie-Inhalt. ``token_id`` ist der Bootstrap-Bearer."""

    user_id: int
    token_id: int
    scope: str


class ConsoleSessionSigner:
    """Signiert/prüft das Session-Cookie mit einem vorab abgeleiteten Sub-Key.

    Den Sub-Key liefert ``KeyVault.derive_subkey(CONSOLE_SESSION_INFO)`` – der
    Signer selbst kennt das ``SECRET_KEY``-Rohmaterial nicht.
    """

    def __init__(
        self,
        signing_key: bytes,
        *,
        ttl_s: int = DEFAULT_TTL_S,
        admin_ttl_s: int = ADMIN_TTL_S,
    ) -> None:
        if not signing_key:
            raise ValueError("ConsoleSessionSigner braucht einen Signing-Key")
        self._key = signing_key
        self._ttl = ttl_s
        self._admin_ttl = admin_ttl_s

    @property
    def ttl_s(self) -> int:
        """TTL der Self-Service-Session in Sekunden."""
        return self._ttl

    def ttl_for(self, scope: str) -> int:
        """TTL je Scope – auch das Cookie-``Max-Age`` (kein Drift)."""
        return self._admin_ttl if scope == SCOPE_ADMIN else self._ttl

    def mint(
        self,
        user_id: int,
        *,
        token_id: int,
        scope: str = SCOPE_USER,
        now: float | None = None,
    ) -> str:
        """Signiertes Session-Token; an ``token_id`` gebunden, TTL je ``scope``."""
        if scope not in SCOPES:
            raise ValueError(f"Unbekannter Console-Scope: {scope}")
        iat = int(now if now is not None else time.time())
        return jwt.encode(
            {
                "sub": str(user_id),
                "tid": str(token_id),
                "scope": scope,
                "iat": iat,
                "exp": iat + self.ttl_for(scope),
            },
            self._key,
            algorithm=_ALG,
        )

    def verify(self, token: str) -> ConsoleSessionClaims:
        """Gibt die Claims zurück oder wirft ``ConsoleSessionError``.

        Prüft NUR Signatur, ``exp`` und die Claim-Struktur; ``disabled``/``revoked``
        sind Sache des DB-Lookups im Auth-Pfad. Ein Cookie ohne ``tid``/``scope``
        (vor der Token-Bindung geprägt) ist ungültig – bewusst kein Lenient-Pfad:
        bei 30-min-TTL kostet das höchstens ein erneutes Öffnen der Konsole.
        """
        try:
            claims = jwt.decode(
                token,
                self._key,
                algorithms=[_ALG],
                options={"require": ["exp", "sub", "tid", "scope"]},
            )
        except jwt.PyJWTError as exc:
            raise ConsoleSessionError(str(exc)) from exc
        scope = claims["scope"]
        if scope not in SCOPES:
            raise ConsoleSessionError(f"Unbekannter Console-Scope: {scope}")
        try:
            return ConsoleSessionClaims(
                user_id=int(claims["sub"]), token_id=int(claims["tid"]), scope=scope
            )
        except (TypeError, ValueError) as exc:
            raise ConsoleSessionError(f"Ungültige Claims: {exc}") from exc
