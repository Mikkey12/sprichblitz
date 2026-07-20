"""Blockierender First-Run-Modal: Backend-URL + Bearer-Token.

Wird vor dem Tray gezeigt, falls noch kein Token im System-Keystore liegt
(siehe ``app.py``). Das Token wird **nicht** in :class:`ClientConfig`
gespeichert, sondern direkt via :mod:`sprichblitz_client.secrets_store` ins
OS-Keystore geschrieben.

UX-Entscheidungen
-----------------
- Modal, nicht Tray-only: ohne gültiges Token startet der Client nicht.
- Show/Hide-Button für das Token-Feld – default ``*``-maskiert.
- Optionaler "Verbindung testen"-Button (synchron ``GET /health`` für
  Erreichbarkeit + authed ``GET /config`` für die Token-Gültigkeit,
  3 s Timeout). Verifiziert Token + URL bevor gespeichert wird.
- Abbrechen → Rückgabe ``None``; Aufrufer entscheidet, ob Client beendet
  oder weiterläuft (Default: beenden).

Lazy-Imports: ``customtkinter`` und ``httpx`` erst in :meth:`prompt`.
"""

from __future__ import annotations

from dataclasses import dataclass

from loguru import logger

from .. import secrets_store
from ..config import ClientConfig, save_config
from ..url_validation import validate_backend_url
from . import palette

DEFAULT_BACKEND_URL = "https://sprichblitz.example.com"
HEALTH_TIMEOUT_S = 3.0


@dataclass(frozen=True)
class TokenDialogResult:
    """Ergebnis des Modal-Dialogs."""

    backend_url: str
    token: str


class TokenDialog:
    """Blockierender First-Run-Modal.

    Verwendung::

        dlg = TokenDialog(initial_url=cfg.backend_url)
        result = dlg.prompt()
        if result is None:
            sys.exit(0)
        # Token + URL sind bereits persistiert (keyring + config.json).
    """

    def __init__(self, initial_url: str = DEFAULT_BACKEND_URL) -> None:
        self._initial_url = initial_url
        self._result: TokenDialogResult | None = None

    def prompt(self) -> TokenDialogResult | None:
        """Zeigt den Dialog und blockiert bis OK oder Abbrechen."""
        import customtkinter as ctk  # type: ignore[import-not-found]

        ctk.set_appearance_mode("system")
        ctk.set_default_color_theme("blue")

        win = ctk.CTk()
        win.title("Sprichblitz – Erstkonfiguration")
        win.geometry("560x430")
        win.resizable(False, False)
        win.configure(fg_color=palette.BG)
        try:
            win.attributes("-topmost", True)
        except Exception:  # pragma: no cover
            pass

        ctk.CTkLabel(
            win,
            text="Sprichblitz einrichten",
            anchor="w",
            text_color=palette.TEXT,
            font=ctk.CTkFont(size=palette.TEXT_XL, weight=palette.WEIGHT_BOLD),
        ).pack(fill="x", padx=palette.SPACE_5, pady=(palette.SPACE_5, palette.SPACE_1))
        ctk.CTkLabel(
            win,
            text="Mit deinem Backend verbinden und den Zugriff sicher hinterlegen.",
            anchor="w",
            text_color=palette.TEXT_MUTED,
            font=ctk.CTkFont(size=palette.TEXT_SM),
        ).pack(fill="x", padx=palette.SPACE_5, pady=(0, palette.SPACE_4))

        card = ctk.CTkFrame(win, **palette.card_style())
        card.pack(fill="x", padx=palette.SPACE_5)

        # ----- URL --------------------------------------------------------
        ctk.CTkLabel(
            card,
            text="Backend-URL",
            anchor="w",
            text_color=palette.TEXT,
            font=ctk.CTkFont(size=palette.TEXT_SM, weight=palette.WEIGHT_BOLD),
        ).pack(fill="x", padx=palette.SPACE_4, pady=(palette.SPACE_4, palette.SPACE_1))
        url_var = ctk.StringVar(value=self._initial_url)
        url_entry = ctk.CTkEntry(card, textvariable=url_var, **palette.entry_style())
        url_entry.pack(fill="x", padx=palette.SPACE_4, pady=(0, palette.SPACE_3))

        # ----- Token ------------------------------------------------------
        ctk.CTkLabel(
            card,
            text="Bearer-Token (BACKEND_AUTH_TOKEN aus dem Backend-Setup)",
            anchor="w",
            text_color=palette.TEXT,
            font=ctk.CTkFont(size=palette.TEXT_SM, weight=palette.WEIGHT_BOLD),
        ).pack(fill="x", padx=palette.SPACE_4, pady=(0, palette.SPACE_1))
        token_var = ctk.StringVar()
        token_entry = ctk.CTkEntry(
            card,
            textvariable=token_var,
            show="*",
            **palette.entry_style(),
        )
        token_entry.pack(fill="x", padx=palette.SPACE_4, pady=(0, palette.SPACE_1))

        show_var = ctk.BooleanVar(value=False)

        def toggle_show() -> None:
            token_entry.configure(show="" if show_var.get() else "*")

        ctk.CTkCheckBox(
            card,
            text="Token anzeigen",
            variable=show_var,
            command=toggle_show,
            **palette.checkbox_style(),
        ).pack(
            anchor="w",
            padx=palette.SPACE_4,
            pady=(0, palette.SPACE_3),
        )

        # ----- Status-Label ---------------------------------------------
        status_var = ctk.StringVar(value="")
        status_label = ctk.CTkLabel(
            win,
            textvariable=status_var,
            anchor="w",
            text_color=palette.TEXT_MUTED,
            font=ctk.CTkFont(size=palette.TEXT_SM),
        )
        status_label.pack(fill="x", padx=palette.SPACE_5, pady=(palette.SPACE_2, 0))

        # ----- Buttons ----------------------------------------------------
        button_row = ctk.CTkFrame(win, fg_color="transparent")
        button_row.pack(
            fill="x",
            padx=palette.SPACE_5,
            pady=(palette.SPACE_3, palette.SPACE_5),
        )

        def set_status(message: str, *, ok: bool | None = None) -> None:
            status_var.set(message)
            color = palette.TEXT_MUTED if ok is None else palette.SUCCESS if ok else palette.DANGER
            status_label.configure(text_color=color)

        def on_test() -> None:
            url = url_var.get().strip().rstrip("/")
            token = token_var.get().strip()
            if not url or not token:
                set_status("URL und Token erforderlich.", ok=False)
                return
            set_status("Teste Verbindung …")
            win.update_idletasks()
            ok, message = _test_connection(url, token)
            set_status(message, ok=ok)
            logger.info("TokenDialog Test-Verbindung: ok={} url={}", ok, url)

        def on_save() -> None:
            url = url_var.get().strip().rstrip("/")
            token = token_var.get().strip()
            if not url or not token:
                set_status("URL und Token erforderlich.", ok=False)
                return
            check = validate_backend_url(url)
            if not check.ok:
                set_status(check.message or "Ungültige Backend-URL.", ok=False)
                return
            try:
                secrets_store.set_token(token)
            except Exception as exc:
                set_status(f"Token speichern fehlgeschlagen: {exc}", ok=False)
                logger.exception("Keyring-Schreiben fehlgeschlagen")
                return
            cfg = ClientConfig(backend_url=url)
            save_config(cfg)
            self._result = TokenDialogResult(backend_url=url, token=token)
            win.destroy()

        def on_cancel() -> None:
            self._result = None
            win.destroy()

        ctk.CTkButton(
            button_row,
            text="Verbindung testen",
            command=on_test,
            width=168,
            **palette.secondary_button(),
        ).pack(side="left")
        ctk.CTkButton(
            button_row,
            text="Abbrechen",
            command=on_cancel,
            width=112,
            **palette.secondary_button(),
        ).pack(side="right", padx=(palette.SPACE_2, 0))
        ctk.CTkButton(
            button_row,
            text="Speichern",
            command=on_save,
            width=112,
            **palette.primary_button(),
        ).pack(side="right")

        win.protocol("WM_DELETE_WINDOW", on_cancel)
        token_entry.focus_set()
        win.mainloop()
        return self._result


def _test_connection(
    url: str,
    token: str,
) -> tuple[bool, str]:
    """Erreichbarkeit via ``/health`` + Token-Gültigkeit via ``/config``.

    ``/health`` ist absichtlich öffentlich – ein 200 dort sagt nichts über
    das Token. Erst der authed ``/config``-Aufruf prüft das Token wirklich
    (vorher meldete der Dialog mit falschem Token "Verbindung OK")."""
    try:
        import httpx
    except ImportError:  # pragma: no cover
        return False, "httpx nicht installiert."

    headers = {"Authorization": f"Bearer {token}"}
    timeout = httpx.Timeout(HEALTH_TIMEOUT_S, connect=HEALTH_TIMEOUT_S)
    try:
        with httpx.Client(timeout=timeout, headers=headers) as client:
            health = client.get(f"{url}/health")
            if health.status_code in (401, 403):
                return False, "Zugang abgelehnt – Bearer-Token prüfen."
            if health.status_code != 200:
                return False, f"Backend nicht ok (Health HTTP {health.status_code})."
            cfg = client.get(f"{url}/config")
    except httpx.ConnectError as exc:
        return False, f"Backend nicht erreichbar: {exc}"
    except httpx.TimeoutException:
        return False, "Timeout beim Verbindungstest."

    if cfg.status_code == 200:
        return True, "Verbindung OK – Token gültig."
    if cfg.status_code in (401, 403):
        return False, "Zugang abgelehnt – Bearer-Token prüfen."
    return False, f"Token-Check fehlgeschlagen (/config HTTP {cfg.status_code})."
