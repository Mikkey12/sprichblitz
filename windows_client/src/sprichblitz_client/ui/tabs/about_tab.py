"""Settings-Tab: Über – Version, GitHub-Link, Quick-Health-Check."""

from __future__ import annotations

import webbrowser
from collections.abc import Callable

from loguru import logger

from ... import __version__
from ...config import ClientConfig
from .. import palette

GITHUB_URL = "https://github.com/Mikkey12/sprichblitz"

HEALTH_TIMEOUT_S = 3.0


class AboutTab:
    def __init__(
        self,
        parent: object,
        cfg: ClientConfig,
        on_dirty: Callable[[], None] | None = None,
    ) -> None:
        import customtkinter as ctk  # type: ignore[import-not-found]

        self._cfg = cfg
        self._status_var = ctk.StringVar(value="")

        parent.configure(fg_color=palette.SURFACE)

        ctk.CTkLabel(
            parent,
            text="Sprichblitz",
            text_color=palette.TEXT,
            font=ctk.CTkFont(
                size=palette.TEXT_XL,
                weight=palette.WEIGHT_BOLD,
            ),
            anchor="w",
        ).pack(
            fill="x",
            padx=palette.SPACE_5,
            pady=(palette.SPACE_5, palette.SPACE_1),
        )
        ctk.CTkLabel(
            parent,
            text=f"Version {__version__}",
            anchor="w",
            text_color=palette.TEXT_MUTED,
        ).pack(fill="x", padx=palette.SPACE_5)

        ctk.CTkLabel(
            parent,
            text=(
                "System-weites Diktat-Tool. Audio läuft direkt zum eigenen\n"
                "FastAPI-Backend, kein Cloud-Vendor sieht das Audio –\n"
                "ausser den explizit konfigurierten STT/LLM-Providern."
            ),
            anchor="w",
            justify="left",
            text_color=palette.TEXT,
            font=ctk.CTkFont(size=palette.TEXT_SM),
        ).pack(
            fill="x",
            padx=palette.SPACE_5,
            pady=(palette.SPACE_4, palette.SPACE_2),
        )

        ctk.CTkLabel(
            parent,
            text=(
                "Sprichblitz ist eine eigenständige Reinterpretation der\n"
                '„Blitztext"-Idee von Christoph Magnussen (YouTube, April\n'
                "2026). Dank an Christoph für die ursprüngliche Idee und\n"
                "dafür, dass er seine eigene Implementierung offen\n"
                "freigegeben hat:\n"
                "https://github.com/cmagnussen/blitztext-app"
            ),
            anchor="w",
            justify="left",
            text_color=palette.TEXT_MUTED,
        ).pack(
            fill="x",
            padx=palette.SPACE_5,
            pady=(0, palette.SPACE_3),
        )

        link_button = ctk.CTkButton(
            parent,
            text="GitHub öffnen",
            width=180,
            command=self._open_github,
            **palette.secondary_button(),
        )
        link_button.pack(
            anchor="w",
            padx=palette.SPACE_5,
            pady=(palette.SPACE_2, palette.SPACE_4),
        )

        health_button = ctk.CTkButton(
            parent,
            text="Quick-Health-Check",
            width=180,
            command=self._on_health,
            **palette.secondary_button(),
        )
        health_button.pack(
            anchor="w",
            padx=palette.SPACE_5,
            pady=(0, palette.SPACE_2),
        )

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
            pady=(palette.SPACE_1, palette.SPACE_4),
        )

    # ------------------------------------------------------------------
    def apply(self) -> None:
        # Reiner Read-only-Tab.
        return

    def _open_github(self) -> None:
        try:
            webbrowser.open(GITHUB_URL)
        except Exception as exc:
            logger.warning("Browser-Open fehlgeschlagen: {}", exc)

    def _on_health(self) -> None:
        from ... import secrets_store

        url = self._cfg.backend_url.rstrip("/")
        token = secrets_store.get_token() or ""
        if not url or not token:
            self._set_status(
                "Backend-URL oder Token fehlt – siehe Backend-Tab.",
                ok=False,
            )
            return

        import httpx

        headers = {"Authorization": f"Bearer {token}"}
        try:
            resp = httpx.get(
                f"{url}/health",
                headers=headers,
                timeout=httpx.Timeout(HEALTH_TIMEOUT_S, connect=HEALTH_TIMEOUT_S),
            )
        except httpx.ConnectError as exc:
            self._set_status(f"Backend nicht erreichbar: {exc}", ok=False)
            return
        except httpx.TimeoutException:
            self._set_status("Health-Check Timeout.", ok=False)
            return

        if resp.status_code == 200:
            data = resp.json()
            self._set_status(
                f"OK – Backend {data.get('version', '?')}, "
                f"Uptime {data.get('uptime_seconds', 0)} s.",
                ok=True,
            )
        elif resp.status_code in (401, 403):
            self._set_status("Zugang abgelehnt – Bearer-Token prüfen.", ok=False)
        else:
            self._set_status(f"Health-Check HTTP {resp.status_code}.", ok=False)

    def _set_status(self, message: str, *, ok: bool) -> None:
        self._status_var.set(message)
        self._status_label.configure(
            text_color=palette.SUCCESS if ok else palette.DANGER,
        )
