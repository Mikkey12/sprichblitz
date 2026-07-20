"""Cloudflare-Access-JWT-Validierung (auth.mode=token_plus_cf_access).

Validiert den ``Cf-Access-Jwt-Assertion``-Header: Signatur gegen die JWKS der
Team-Domain, plus aud/iss/exp. ``alg`` ist auf RS256 festgenagelt (Cloudflare
Access signiert RS256) → ``none`` und HS*-Alg-Confusion (öffentlicher Key als
HMAC-Secret) sind ausgeschlossen. JWKS wird **lazy** geholt (kein Netz beim
Start – Kaltstart-Lektion), gecacht (TTL) und bei unbekanntem ``kid`` nur
**gedrosselt** nachgeladen (Negativ-Cache gegen unknown-kid-Fluten). Jeder
Fehlerpfad ist **fail-closed**: ohne passenden, geprüften Schlüssel wird nie
akzeptiert.

Der JWT ist ein reines **Edge-Gate** (SSO/Service-Token bestanden?) – KEINE
Identität. Die Identität kommt weiter aus dem Bearer-Token. Claims werden nicht
geloggt (PII).
"""

from __future__ import annotations

import json
import threading
import time
from collections.abc import Callable
from typing import Any

import httpx
import jwt
from jwt.algorithms import RSAAlgorithm
from loguru import logger

# Cloudflare Access signiert Access-JWTs mit RS256 (die Schlüssel unter
# /cdn-cgi/access/certs sind RSA). Bewusst NICHT konfigurierbar – die Allowlist
# verhindert alg:none und HS*-Alg-Confusion.
_ALLOWED_ALGS = ["RS256"]

# fetcher(url, timeout) -> JWKS-dict; injizierbar für Tests (kein Netz).
JwksFetcher = Callable[[str, float], dict[str, Any]]


class CfAccessError(Exception):
    """Interner Validierungsfehler; wird in auth.py auf 403 gemappt."""


class CfAccessVerifier:
    def __init__(
        self,
        *,
        team_domain: str,
        application_aud: str,
        cache_ttl_s: float = 3600.0,
        min_refetch_interval_s: float = 60.0,
        http_timeout_s: float = 5.0,
        jwks_fetcher: JwksFetcher | None = None,
    ) -> None:
        if not team_domain or not application_aud:
            raise ValueError("CfAccessVerifier braucht team_domain und application_aud")
        self._iss = f"https://{team_domain}.cloudflareaccess.com"
        self._certs_url = f"{self._iss}/cdn-cgi/access/certs"
        self._aud = application_aud
        self._ttl = cache_ttl_s
        self._min_refetch = min_refetch_interval_s
        self._timeout = http_timeout_s
        self._fetch_jwks = jwks_fetcher or self._http_fetch
        self._keys: dict[str, Any] = {}  # kid -> RSA public key
        self._fetched_at = 0.0
        self._last_attempt = float("-inf")
        self._lock = threading.Lock()

    def verify(self, token: str) -> dict[str, Any]:
        """Validiert den Token vollständig oder wirft ``CfAccessError`` (fail-closed)."""
        try:
            header = jwt.get_unverified_header(token)
        except jwt.PyJWTError as exc:
            raise CfAccessError(f"bad token header: {exc}") from exc

        alg = header.get("alg")
        if alg not in _ALLOWED_ALGS:  # blockt none + HS*-Confusion
            raise CfAccessError(f"disallowed alg: {alg!r}")
        kid = header.get("kid")
        if not kid:
            raise CfAccessError("missing kid")

        key = self._key_for_kid(kid)
        try:
            claims: dict[str, Any] = jwt.decode(
                token,
                key=key,
                algorithms=_ALLOWED_ALGS,
                audience=self._aud,
                issuer=self._iss,
                options={"require": ["exp", "iss", "aud"]},
            )
        except jwt.PyJWTError as exc:
            raise CfAccessError(f"invalid token: {exc}") from exc
        return claims

    def _key_for_kid(self, kid: str) -> Any:
        with self._lock:
            now = time.monotonic()
            if kid in self._keys and (now - self._fetched_at) < self._ttl:
                return self._keys[kid]
            # (Re)fetch nötig (kid unbekannt oder Cache abgelaufen) – aber gedrosselt,
            # damit eine Flut unbekannter kids nicht den certs-Endpoint hämmert.
            if (now - self._last_attempt) >= self._min_refetch:
                self._last_attempt = now
                try:
                    self._refresh(now)
                except Exception as exc:  # fail-closed: kid wird unten geprüft
                    logger.warning("CF Access JWKS refresh failed", error=str(exc))
            if kid in self._keys:
                return self._keys[kid]
            raise CfAccessError("no JWKS key for kid (fail-closed)")

    def _refresh(self, now: float) -> None:
        jwks = self._fetch_jwks(self._certs_url, self._timeout)
        keys: dict[str, Any] = {}
        for jwk in jwks.get("keys", []):
            if jwk.get("kty") != "RSA" or not jwk.get("kid"):
                continue
            keys[jwk["kid"]] = RSAAlgorithm.from_jwk(json.dumps(jwk))
        # Cache nur bei erfolgreichem Fetch ersetzen.
        self._keys = keys
        self._fetched_at = now

    @staticmethod
    def _http_fetch(url: str, timeout: float) -> dict[str, Any]:
        resp = httpx.get(url, timeout=timeout)
        resp.raise_for_status()
        return resp.json()
