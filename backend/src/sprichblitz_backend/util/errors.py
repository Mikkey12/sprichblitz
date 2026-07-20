from __future__ import annotations

from fastapi import HTTPException, Request, status
from fastapi.responses import JSONResponse


class ProviderError(Exception):
    """Base for all provider-side problems."""

    code: str = "provider_error"
    http_status: int = status.HTTP_502_BAD_GATEWAY

    def __init__(self, message: str, *, provider: str | None = None) -> None:
        super().__init__(message)
        self.provider = provider
        self.message = message


class ProviderUnavailable(ProviderError):
    code = "provider_unavailable"
    http_status = status.HTTP_503_SERVICE_UNAVAILABLE


class ProviderAuthError(ProviderError):
    # Key vom Provider abgelehnt (echtes 401 vom Upstream) → 422 mit eigenem
    # Code, klar unterscheidbar von "kein Key hinterlegt" (412) und "nicht
    # entschlüsselbar" (422/provider_key_undecryptable).
    code = "provider_key_rejected"
    http_status = status.HTTP_422_UNPROCESSABLE_ENTITY


class ProviderInvalidResponse(ProviderError):
    code = "provider_invalid_response"
    http_status = status.HTTP_502_BAD_GATEWAY


class ProviderEmptyResult(ProviderInvalidResponse):
    """Syntaktisch gültige Provider-Antwort OHNE brauchbaren Inhalt (fehlender
    bzw. kein-String ``text``) – ein Provider-Fehlverhalten, nicht ein
    Status-Fehler.

    Bewusst eigene Subklasse: Der STT-Fallback (``transcription.py``) soll HIERAUF
    zurückfallen (leeres/verhörtes lokales STT → Cloud-Fallback), aber NICHT auf
    einen 4xx-Status (Quota/Bad-Request), der dieselbe Basisklasse
    ``ProviderInvalidResponse`` nutzt und bewusst 1:1 an den Client durchgereicht
    wird (Nutzer sollen Quota-Fehler sehen). Als Subklasse bleiben ``code`` und
    ``http_status`` gleich – kein Änderung am Client-Kontrakt, nur ein internes
    Unterscheidungsmerkmal für die Fallback-Logik.
    """


class ModeNotConfigured(HTTPException):
    """Raised when a request references a mode that isn't in config.yml."""

    def __init__(self, mode: str) -> None:
        super().__init__(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": f"Mode not configured: {mode}", "code": "mode_not_configured"},
        )


class OverrideNotAllowed(HTTPException):
    """Raised when a request asks for a provider that isn't in the registry."""

    def __init__(self, kind: str, name: str) -> None:
        super().__init__(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": f"Unknown {kind} provider override: {name}",
                "code": "override_not_allowed",
            },
        )


class MissingProviderKey(HTTPException):
    """Kein Per-User-Key für den benötigten Provider hinterlegt."""

    def __init__(self, provider: str) -> None:
        super().__init__(
            status_code=status.HTTP_412_PRECONDITION_FAILED,
            detail={
                "error": f"Kein API-Key für {provider} hinterlegt",
                "code": "missing_provider_key",
            },
        )


class ProviderKeyUndecryptable(HTTPException):
    """Hinterlegter Key ist nicht entschlüsselbar (rotierter/entfernter/korrupter Key)."""

    def __init__(self, provider: str) -> None:
        super().__init__(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "error": f"Key für {provider} nicht entschlüsselbar – bitte neu hinterlegen",
                "code": "provider_key_undecryptable",
            },
        )


class ModeDisabled(HTTPException):
    """Der Nutzer hat diesen Modus via mode_overrides deaktiviert (enabled=false)."""

    def __init__(self, mode: str) -> None:
        super().__init__(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"error": f"Mode disabled: {mode}", "code": "mode_disabled"},
        )


class ModeMisconfigured(HTTPException):
    """LLM ist aktiv (apply_llm), aber es fehlt effektiv ein LLM-Provider oder
    System-Prompt – z. B. nach Config-Drift. Defensiv als 409 statt 500 (die
    PUT-Validierung verhindert das Speichern solcher Overrides schon vorher)."""

    def __init__(self, mode: str) -> None:
        super().__init__(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": f"Modus fehlerhaft konfiguriert (LLM aktiv, aber Provider/Prompt fehlt): {mode}",
                "code": "mode_misconfigured",
            },
        )


class LocalGateTimeout(HTTPException):
    """Lokale Inferenz ausgelastet – Gate-Acquire lief in den Timeout (Etappe 5)."""

    def __init__(self) -> None:
        super().__init__(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"error": "Backend ausgelastet, bitte erneut versuchen", "code": "backend_busy"},
        )


class RateLimited(HTTPException):
    """Per-User-Rate-Limit überschritten (Etappe 5)."""

    def __init__(self) -> None:
        super().__init__(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={"error": "Zu viele Anfragen, bitte kurz warten", "code": "rate_limited"},
        )


def provider_exception_handler(_: Request, exc: ProviderError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.http_status,
        content={
            "error": exc.message,
            "code": exc.code,
            "provider": exc.provider,
        },
    )
