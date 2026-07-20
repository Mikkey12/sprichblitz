"""HTTP-Client gegen das Sprichblitz-Backend.

In Phase 1 nutzt der Client nur ``POST /full`` (Audio → fertiger Text).
Bearer-Token kommt aus dem System-Keystore (siehe
:mod:`sprichblitz_client.secrets_store`); URL aus :class:`ClientConfig`.

Timeouts:
- Globaler Timeout 60 s (Whisper-Cloud-Limit + Buffer für Netz).
- Connect-Timeout 10 s, sonst Toast „Backend nicht erreichbar".
"""

from __future__ import annotations

import httpx

from ..models import BackendError, FullResult, MeInfo, Mode, ModeStatus

DEFAULT_TIMEOUT = httpx.Timeout(60.0, connect=10.0)


class BackendClient:
    def __init__(
        self,
        backend_url: str,
        token: str,
        *,
        timeout: httpx.Timeout = DEFAULT_TIMEOUT,
        client: httpx.Client | None = None,
    ) -> None:
        self._base = backend_url.rstrip("/")
        self._token = token
        headers = {"Authorization": f"Bearer {token}"}
        if client is not None:
            self._client = client
            self._owns_client = False
        else:
            self._client = httpx.Client(
                base_url=self._base,
                timeout=timeout,
                headers=headers,
            )
            self._owns_client = True

    def __enter__(self) -> BackendClient:
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    # ------------------------------------------------------------------
    def health(self) -> dict:
        resp = self._client.get("/health")
        resp.raise_for_status()
        return resp.json()

    def get_config(self) -> dict:
        """``GET /config`` – verfügbare Provider, Modi, Provider-Health.

        Wird vom Settings-Window verwendet, um Provider-Status anzuzeigen
        und Mode-Konfigurationen darzustellen.
        """
        resp = self._client.get("/config")
        if resp.status_code >= 400:
            raise _error_from_response(resp)
        return resp.json()

    def full(
        self,
        audio_wav: bytes,
        mode: Mode,
        *,
        locale: str | None = None,
    ) -> FullResult:
        # d4: keine per-Request-STT/LLM-Overrides mehr – der Modus (+ die per-User
        # /me/modes + processing_location) bestimmt im Backend Provider & Prompt.
        files = {"file": ("recording.wav", audio_wav, "audio/wav")}
        data = {"mode": mode.value}
        if locale:
            data["locale"] = locale
        try:
            resp = self._client.post("/full", files=files, data=data)
        except httpx.ConnectError as exc:
            raise BackendError(
                error=f"Backend nicht erreichbar: {exc}",
                code="connection_error",
            ) from exc
        except httpx.TimeoutException as exc:
            raise BackendError(
                error=f"Timeout beim Backend-Call: {exc}",
                code="timeout",
            ) from exc

        if resp.status_code >= 400:
            raise _error_from_response(resp)
        return FullResult.model_validate(resp.json())

    def create_console_session(self, *, boot_nonce: str | None = None) -> str:
        """``POST /console/session`` – tauscht den Bearer gegen einen kurzlebigen
        Single-Use-Bootstrap-Code für die Konsolen-Webview (setzt hier KEIN Cookie).

        Die Webview löst den Code via ``GET /console/bootstrap?code=…`` ein – so
        gelangt der Bearer nie in die Webview, nur der Code in die URL.
        """
        try:
            headers = {"X-Sb-Boot-Nonce": boot_nonce} if boot_nonce else None
            resp = self._client.post("/console/session", headers=headers)
        except httpx.ConnectError as exc:
            raise BackendError(
                error=f"Backend nicht erreichbar: {exc}", code="connection_error"
            ) from exc
        except httpx.TimeoutException as exc:
            raise BackendError(error=f"Timeout beim Backend-Call: {exc}", code="timeout") from exc
        if resp.status_code >= 400:
            raise _error_from_response(resp)
        return resp.json()["code"]

    def get_modes(self) -> dict[Mode, ModeStatus]:
        """``GET /me/modes`` → pro Modus ``enabled`` + effektiver ``display_name``.

        Für die location-bewusste Hotkey-Steuerung (deaktivierte Modi starten kein
        Diktat). ``mode_key`` ist config-getrieben und darf ein beliebiger
        nichtleerer String sein.
        """
        try:
            resp = self._client.get("/me/modes")
        except httpx.ConnectError as exc:
            raise BackendError(
                error=f"Backend nicht erreichbar: {exc}", code="connection_error"
            ) from exc
        except httpx.TimeoutException as exc:
            raise BackendError(error=f"Timeout beim Backend-Call: {exc}", code="timeout") from exc
        if resp.status_code >= 400:
            raise _error_from_response(resp)
        out: dict[Mode, ModeStatus] = {}
        for item in resp.json():
            try:
                mode = Mode(item["mode_key"])
            except (ValueError, KeyError, TypeError):
                continue
            out[mode] = ModeStatus(
                enabled=bool(item.get("enabled", True)),
                display_name=str(item.get("display_name") or mode.value),
            )
        return out

    def get_me(self) -> MeInfo:
        """``GET /me`` → Profil (Name + processing_location) für den Tray-Tooltip."""
        try:
            resp = self._client.get("/me")
        except httpx.ConnectError as exc:
            raise BackendError(
                error=f"Backend nicht erreichbar: {exc}", code="connection_error"
            ) from exc
        except httpx.TimeoutException as exc:
            raise BackendError(error=f"Timeout beim Backend-Call: {exc}", code="timeout") from exc
        if resp.status_code >= 400:
            raise _error_from_response(resp)
        data = resp.json()
        return MeInfo(
            name=str(data.get("name", "")),
            processing_location=str(data.get("processing_location", "")),
        )


def _error_from_response(resp: httpx.Response) -> BackendError:
    """Mapped Backend-``ErrorResponse`` (oder beliebige 4xx/5xx) auf BackendError."""
    code = "http_error"
    error = f"HTTP {resp.status_code}"
    provider: str | None = None
    try:
        body = resp.json()
        if isinstance(body, dict):
            error = str(body.get("error") or error)
            code = str(body.get("code") or code)
            provider = body.get("provider") or None
    except ValueError:
        # Body war kein JSON – wir behalten die generische Meldung.
        pass

    if resp.status_code in (401, 403) and code == "http_error":
        code = "auth_failed"
        error = "Authentifizierung fehlgeschlagen – Token in Settings prüfen."

    return BackendError(error=error, code=code, provider=provider, http_status=resp.status_code)
