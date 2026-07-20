"""Single-Use-Bootstrap-Codes für die Console-Session.

Der native Shell tauscht seinen Bearer (``POST /console/session``) gegen einen
kurzlebigen, EINMALIGEN Code; die Webview löst ihn per ``GET /console/bootstrap``
ein und bekommt dabei das Session-Cookie gesetzt. So gelangt der durable Bearer
NIE in die Webview – nur ein 256-bit-Code (CSPRNG), single-use, ~60s gültig.

In-memory + **prozesslokal** (wie ``rate_limiter``/``local_gate`` seit Etappe 5).
Bei einem Multi-Worker-Deploy (``--workers>1``) müsste der Store geteilt oder der
Code stateless-signiert werden – aktuell läuft das Backend Single-Prozess.
"""

from __future__ import annotations

import secrets
import time
from dataclasses import dataclass
from threading import Lock

from .console_session import SCOPE_USER

DEFAULT_TTL_S = 60
_CODE_NBYTES = 32  # 256 bit CSPRNG


@dataclass(frozen=True)
class BootstrapGrant:
    """Was ein eingelöster Code freigibt – wandert 1:1 in die Session-Claims.

    ``token_id`` trägt den Bootstrap-Bearer bis zum Mint durch (Token-Bindung),
    ``scope`` die Reichweite der entstehenden Session.
    """

    user_id: int
    token_id: int
    scope: str
    # Optionaler Client-Nonce gegen Session-Fixation: der Redeem verlangt das
    # Cookie ``sb_boot`` == diesen Wert. ``None`` = Alt-Verhalten (kein Nonce).
    nonce: str | None = None


class BootstrapCodeStore:
    def __init__(self, *, ttl_s: int = DEFAULT_TTL_S) -> None:
        self._ttl = ttl_s
        self._codes: dict[str, tuple[BootstrapGrant, float]] = {}  # code -> (grant, expiry)
        self._lock = Lock()

    @property
    def ttl_s(self) -> int:
        return self._ttl

    def issue(
        self,
        user_id: int,
        *,
        token_id: int,
        scope: str = SCOPE_USER,
        nonce: str | None = None,
        now: float | None = None,
    ) -> str:
        """Prägt einen neuen 256-bit-Single-Use-Code für ``user_id``.

        ``nonce`` (optional) bindet den Code an einen Client-Wert; der Redeem
        verlangt dann das passende ``sb_boot``-Cookie (Anti-Session-Fixation).
        """
        t = time.monotonic() if now is None else now
        with self._lock:
            self._purge(t)
            code = secrets.token_urlsafe(_CODE_NBYTES)
            grant = BootstrapGrant(user_id=user_id, token_id=token_id, scope=scope, nonce=nonce)
            self._codes[code] = (grant, t + self._ttl)
            return code

    def redeem(self, code: str, *, now: float | None = None) -> BootstrapGrant | None:
        """Löst einen Code EINMALIG ein → :class:`BootstrapGrant` oder ``None``
        (unbekannt/abgelaufen/bereits verbraucht)."""
        t = time.monotonic() if now is None else now
        with self._lock:
            entry = self._codes.pop(code, None)  # single-use: pop, nie zweimal einlösbar
        if entry is None:
            return None
        grant, expiry = entry
        if t > expiry:
            return None
        return grant

    def _purge(self, now: float) -> None:
        for code in [c for c, (_, exp) in self._codes.items() if now > exp]:
            del self._codes[code]
