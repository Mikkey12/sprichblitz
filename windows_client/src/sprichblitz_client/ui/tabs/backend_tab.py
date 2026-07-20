"""Settings-Tab: Backend-URL, Token, Live-Health-Check.

Layout
------
- ``Backend-URL``: editierbar, persistiert in :class:`ClientConfig`.
- ``Bearer-Token``: editierbar (mit Show/Hide), persistiert direkt in
  :mod:`sprichblitz_client.secrets_store` (NICHT in der ClientConfig).
- ``Verbindung testen``: synchroner ``GET /health`` + ``GET /config`` mit
  3 s Timeout. Zeigt Provider-Status (name + healthy + default_model)
  als Liste an.
"""

from __future__ import annotations

import threading
from collections.abc import Callable

from loguru import logger

from ... import secrets_store
from ...config import ClientConfig
from ...url_validation import validate_backend_url
from .. import palette

HEALTH_TIMEOUT_S = 3.0


class BackendTab:
    def __init__(
        self,
        parent: object,  # ctk.CTkFrame – lazy
        cfg: ClientConfig,
        on_dirty: Callable[[], None] | None = None,
    ) -> None:
        import customtkinter as ctk  # type: ignore[import-not-found]

        self._cfg = cfg
        self._on_dirty = on_dirty

        self._url_var = ctk.StringVar(value=cfg.backend_url)
        self._token_var = ctk.StringVar(value=secrets_store.get_token() or "")
        self._show_var = ctk.BooleanVar(value=False)
        self._status_var = ctk.StringVar(value="")

        parent.configure(fg_color=palette.SURFACE)

        for var in (self._url_var, self._token_var):
            var.trace_add("write", lambda *_a: self._mark_dirty())

        ctk.CTkLabel(
            parent,
            text="Backend-URL",
            anchor="w",
            text_color=palette.TEXT,
            font=ctk.CTkFont(size=palette.TEXT_SM, weight=palette.WEIGHT_BOLD),
        ).pack(
            fill="x",
            padx=palette.SPACE_5,
            pady=(palette.SPACE_5, palette.SPACE_1),
        )
        ctk.CTkEntry(
            parent,
            textvariable=self._url_var,
            **palette.entry_style(),
        ).pack(
            fill="x",
            padx=palette.SPACE_5,
            pady=(0, palette.SPACE_3),
        )

        ctk.CTkLabel(
            parent,
            text="Bearer-Token",
            anchor="w",
            text_color=palette.TEXT,
            font=ctk.CTkFont(size=palette.TEXT_SM, weight=palette.WEIGHT_BOLD),
        ).pack(fill="x", padx=palette.SPACE_5)
        self._token_entry = ctk.CTkEntry(
            parent,
            textvariable=self._token_var,
            show="*",
            **palette.entry_style(),
        )
        self._token_entry.pack(
            fill="x",
            padx=palette.SPACE_5,
            pady=(palette.SPACE_1, 0),
        )
        ctk.CTkCheckBox(
            parent,
            text="Token anzeigen",
            variable=self._show_var,
            command=self._toggle_show,
            **palette.checkbox_style(),
        ).pack(
            anchor="w",
            padx=palette.SPACE_5,
            pady=(0, palette.SPACE_3),
        )

        button_row = ctk.CTkFrame(parent, fg_color="transparent")
        button_row.pack(
            fill="x",
            padx=palette.SPACE_5,
            pady=(0, palette.SPACE_3),
        )
        ctk.CTkButton(
            button_row,
            text="Verbindung testen",
            command=self._on_test,
            width=180,
            **palette.secondary_button(),
        ).pack(side="left")

        self._status_label = ctk.CTkLabel(
            parent,
            textvariable=self._status_var,
            anchor="w",
            justify="left",
            text_color=palette.TEXT_MUTED,
        )
        self._status_label.pack(
            fill="x",
            padx=palette.SPACE_5,
            pady=(0, palette.SPACE_2),
        )

        # Provider-Status-Box (wird beim Test befüllt).
        self._providers_box = ctk.CTkTextbox(
            parent,
            height=180,
            **palette.textbox_style(),
        )
        self._providers_box.pack(
            fill="both",
            expand=True,
            padx=palette.SPACE_5,
            pady=(palette.SPACE_1, palette.SPACE_4),
        )
        self._providers_box.configure(state="disabled")

    # ------------------------------------------------------------------
    def apply(self) -> None:
        """Persistiert URL in ClientConfig, Token in keyring.

        Validiert die URL vorher: öffentliche Ziele müssen HTTPS verwenden;
        HTTP ist nur für localhost, Loopback und RFC-1918-LAN zulässig."""
        url = self._url_var.get().strip().rstrip("/")
        check = validate_backend_url(url)
        if not check.ok:
            raise RuntimeError(check.message or "Ungültige Backend-URL.")
        self._cfg.backend_url = url
        token = self._token_var.get().strip()
        if token:
            try:
                secrets_store.set_token(token)
            except Exception as exc:
                logger.exception("Token-Speichern im Keyring fehlgeschlagen")
                raise RuntimeError(f"Token speichern fehlgeschlagen: {exc}") from exc

    # ------------------------------------------------------------------
    def _toggle_show(self) -> None:
        self._token_entry.configure(show="" if self._show_var.get() else "*")

    def _mark_dirty(self) -> None:
        if self._on_dirty is not None:
            self._on_dirty()

    def _on_test(self) -> None:
        url = self._url_var.get().strip().rstrip("/")
        token = self._token_var.get().strip()
        if not url or not token:
            self._set_status("URL und Token erforderlich.", ok=False)
            return
        self._set_status("Teste Verbindung …")
        # Provider-Box auf "lädt …" setzen, bis Worker zurückkommt.
        self._providers_box.configure(state="normal")
        self._providers_box.delete("1.0", "end")
        self._providers_box.insert("1.0", "wird geladen …")
        self._providers_box.configure(state="disabled")

        def worker() -> None:
            ok, status_line, providers_text = _test_backend(url, token)
            # Tk-Calls aus diesem Thread heraus sind nicht sicher → via
            # after(0, …) zurück in den Mainloop-Thread schedulen.
            try:
                self._providers_box.after(  # type: ignore[attr-defined]
                    0,
                    lambda: self._on_test_result(ok, status_line, providers_text, url),
                )
            except Exception:  # pragma: no cover - Window inzwischen zu
                pass

        threading.Thread(target=worker, name="sprichblitz-backend-test", daemon=True).start()

    def _on_test_result(self, ok: bool, status_line: str, providers_text: str, url: str) -> None:
        self._set_status(status_line, ok=ok)
        self._providers_box.configure(state="normal")
        self._providers_box.delete("1.0", "end")
        self._providers_box.insert("1.0", providers_text)
        self._providers_box.configure(state="disabled")
        logger.info("BackendTab Test: ok={} url={}", ok, url)

    def _set_status(self, message: str, *, ok: bool | None = None) -> None:
        self._status_var.set(message)
        color = palette.TEXT_MUTED if ok is None else palette.SUCCESS if ok else palette.DANGER
        self._status_label.configure(text_color=color)


def _test_backend(
    url: str,
    token: str,
) -> tuple[bool, str, str]:
    """Health + Config in einem Rutsch; gibt zusätzlich Provider-Liste zurück."""
    import httpx

    headers = {"Authorization": f"Bearer {token}"}
    timeout = httpx.Timeout(HEALTH_TIMEOUT_S, connect=HEALTH_TIMEOUT_S)
    try:
        with httpx.Client(timeout=timeout, headers=headers) as client:
            health = client.get(f"{url}/health")
            if health.status_code in (401, 403):
                return False, "Zugang abgelehnt – Bearer-Token prüfen.", ""
            if health.status_code != 200:
                return (
                    False,
                    f"Health-Check HTTP {health.status_code}.",
                    "",
                )
            cfg = client.get(f"{url}/config")
            if cfg.status_code in (401, 403):
                return False, "Zugang abgelehnt – Bearer-Token prüfen.", ""
            if cfg.status_code != 200:
                return (
                    False,
                    f"Token-Check fehlgeschlagen (/config HTTP {cfg.status_code}).",
                    "",
                )
    except httpx.ConnectError as exc:
        return False, f"Backend nicht erreichbar: {exc}", ""
    except httpx.TimeoutException:
        return False, "Timeout beim Verbindungstest.", ""

    body = cfg.json()
    lines: list[str] = []

    stt = body.get("stt_providers", [])
    if stt:
        lines.append("STT-Provider:")
        for prov in stt:
            mark = "✓" if prov.get("healthy") else "✗"
            lines.append(
                f"  {mark} {prov.get('name')} ({prov.get('type')}) "
                f"– default {prov.get('default_model')}"
            )
        lines.append("")

    llm = body.get("llm_providers", [])
    if llm:
        lines.append("LLM-Provider:")
        for prov in llm:
            mark = "✓" if prov.get("healthy") else "✗"
            lines.append(
                f"  {mark} {prov.get('name')} ({prov.get('type')}) "
                f"– default {prov.get('default_model')}"
            )
        lines.append("")

    modes = body.get("modes", [])
    if modes:
        lines.append("Modi:")
        for mode in modes:
            llm_part = f" → {mode.get('llm_provider')}" if mode.get("apply_llm") else ""
            lines.append(f"  {mode.get('name')}: STT={mode.get('stt_provider')}{llm_part}")

    return True, f"Verbindung OK (Backend {body.get('version', '?')}).", "\n".join(lines)
