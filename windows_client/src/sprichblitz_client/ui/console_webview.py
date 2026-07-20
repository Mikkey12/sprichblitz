"""Konsolen-Webview als eigener, gehärteter WebView2-Prozess.

Der Elternprozess übergibt per stdin JSON mit Bootstrap-URL und gebundenem
Nonce. Der langlebige Backend-Bearer bleibt immer im Elternprozess. Vor der
ersten Navigation setzt dieser Child-Prozess den ``sb_boot``-Cookie über die
native WebView2-Cookie-API.
"""

from __future__ import annotations

import json
import sys
import time
from dataclasses import dataclass
from urllib.parse import urlsplit

from loguru import logger

_WINDOW_TITLE = "Sprichblitz Konsole"
_HANDLERS: list[object] = []  # .NET-Delegates müssen bis zum Window-Close leben.
_WEBVIEW_READY_TIMEOUT_S = 15.0
_WEBVIEW_READY_POLL_S = 0.05


@dataclass(frozen=True)
class ConsoleLaunch:
    url: str
    nonce: str

    @classmethod
    def parse(cls, raw: str) -> ConsoleLaunch:
        try:
            body = json.loads(raw)
        except (TypeError, json.JSONDecodeError) as exc:
            raise ValueError("ungültiges Console-JSON") from exc
        if not isinstance(body, dict):
            raise ValueError("Console-Payload muss ein Objekt sein")
        url = body.get("url")
        nonce = body.get("nonce")
        if not isinstance(url, str) or not isinstance(nonce, str) or not nonce:
            raise ValueError("Console-URL/Nonce fehlt")
        parsed = urlsplit(url)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path != "/console/bootstrap"
        ):
            raise ValueError("keine gültige https-Bootstrap-URL")

        return cls(url=url, nonce=nonce)


def _install_bootstrap(window, launch: ConsoleLaunch, core: object) -> None:
    """Setzt Cookie und Navigation; muss auf dem nativen UI-Thread laufen."""
    parsed = urlsplit(launch.url)
    hostname = parsed.hostname or ""
    cookie = core.CookieManager.CreateCookie(  # type: ignore[attr-defined]
        "sb_boot",
        launch.nonce,
        hostname,
        "/console",
    )
    cookie.IsSecure = True
    cookie.IsHttpOnly = False
    core.CookieManager.AddOrUpdateCookie(cookie)  # type: ignore[attr-defined]

    def clear_console_cookies() -> None:
        # Dieser Child hostet ausschliesslich die Sprichblitz-Konsole. Beim
        # Schliessen darf kein sb_console-Cookie im privaten Profil bleiben.
        core.CookieManager.DeleteAllCookies()  # type: ignore[attr-defined]

    window.events.closing += clear_console_cookies
    _HANDLERS.append(clear_console_cookies)

    # Direkte native Navigation: Wir befinden uns bereits auf dem WebView2-
    # UI-Thread; window.load_url() würde erneut über pywebview dispatchen.
    core.Navigate(launch.url)  # type: ignore[attr-defined]


def _prepare_window(window, launch: ConsoleLaunch) -> None:  # noqa: ANN001
    """Plant Cookie + Navigation auf dem nativen WebView2-UI-Thread ein."""
    try:
        control = window.native.webview

        def configure_native() -> None:
            core = control.CoreWebView2
            if core is not None:
                _install_bootstrap(window, launch, core)
                return

            def on_initialized(sender, args) -> None:  # noqa: ANN001
                try:
                    if not args.IsSuccess:
                        raise RuntimeError(
                            f"WebView2-Initialisierung fehlgeschlagen: "
                            f"{args.InitializationException}"
                        )
                    _install_bootstrap(window, launch, sender.CoreWebView2)
                except Exception:
                    logger.exception("Console-Webview konnte WebView2 nicht sicher initialisieren")
                    window.destroy()

            control.CoreWebView2InitializationCompleted += on_initialized
            _HANDLERS.append(on_initialized)

        if hasattr(control, "Invoke"):
            # Produktionspfad (WinForms): sämtliche WebView2-Objekte besitzen
            # Thread-Affinität und dürfen nur hier berührt werden.
            from System import Action  # type: ignore[import-not-found]

            control.Invoke(Action(configure_native))
        else:
            # Kleine Fake-Controls in Unit-Tests brauchen kein .NET-Dispatch.
            configure_native()
    except Exception:
        logger.exception("Console-Webview konnte WebView2 nicht sicher initialisieren")
        window.destroy()


def _prepare_window_when_ready(window, launch: ConsoleLaunch) -> None:  # noqa: ANN001
    """Wartet auf den nativen WebView2-Core, bevor dessen APIs laufen.

    ``webview.start(func=...)`` startet ``func`` absichtlich parallel zum
    Erzeugen des nativen Fensters. Ohne diese Schranke ist ``window.native``
    noch ``None`` und das Konsolenfenster schliesst sich direkt wieder. Das
    pywebview-``loaded``-Event ist für ``about:blank`` im gepackten Prozess
    nicht zuverlässig und darf deshalb nicht als Bereitschaftssignal dienen.
    """
    deadline = time.monotonic() + _WEBVIEW_READY_TIMEOUT_S
    while time.monotonic() < deadline:
        native = getattr(window, "native", None)
        control = getattr(native, "webview", None)
        if control is not None:
            _prepare_window(window, launch)
            return
        time.sleep(_WEBVIEW_READY_POLL_S)

    logger.error("Console-Webview wurde nicht rechtzeitig bereit")
    window.destroy()


def run_from_stdin() -> int:
    """Liest ein :class:`ConsoleLaunch`-JSON und öffnet es in Edge WebView2."""
    raw = sys.stdin.readline().strip()
    try:
        launch = ConsoleLaunch.parse(raw)
    except ValueError as exc:
        logger.error("Console-Webview: {}", exc)
        return 2

    # lazy: Tests + Nicht-Webview-Pfade brauchen pywebview nicht installiert.
    import webview

    window = webview.create_window(_WINDOW_TITLE, "about:blank")
    webview.start(
        _prepare_window_when_ready,
        args=(window, launch),
        gui="edgechromium",
    )
    return 0
