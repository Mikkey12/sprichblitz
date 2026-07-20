"""Pystray-basiertes Tray-Icon mit States und Menü.

States
------
``idle``        – Default. Bereit für Hotkey-Eingabe.
``recording``   – Aktive Aufnahme.
``processing``  – Aufnahme fertig, wartet auf Backend-Antwort.
``error``       – Letzter Call ist fehlgeschlagen, Tooltip enthält Detail.
                  Wenn ``blink=True`` an :meth:`set_state` mitgegeben wird,
                  alterniert das Icon zwischen ``error`` und ``idle`` bis
                  zum nächsten ``set_state``-Aufruf.

Menü-Einträge: Settings öffnen, Konto & Keys, Backend-Health prüfen,
Sprichblitz entfernen, Beenden.

Lazy-Imports
------------
``pystray`` und ``PIL`` werden erst in :meth:`TrayIcon.start` geladen,
damit dieses Modul auch auf macOS-Dev importierbar bleibt (kein Tk, kein
Quartz nötig). Auf Windows zieht der eigentliche ``Icon.run()``-Aufruf
beide Libraries nach.
"""

from __future__ import annotations

import io
import threading
import time
from collections.abc import Callable
from typing import Literal

from loguru import logger

from .icons_data import ICONS

State = Literal["idle", "recording", "processing", "error"]

BLINK_INTERVAL_S = 0.5


class TrayIcon:
    """Wrapper um ``pystray.Icon``.

    Der pystray-Loop läuft im Hauptthread (Windows-Anforderung), Setup +
    Start blockieren also – :meth:`run_detached` startet alternativ einen
    eigenen Thread für Smoke-Tests / Settings-driven UIs.
    """

    def __init__(
        self,
        *,
        title: str = "Sprichblitz",
        on_open_settings: Callable[[], None] | None = None,
        on_open_console: Callable[[], None] | None = None,
        on_health_check: Callable[[], None] | None = None,
        on_uninstall: Callable[[], None] | None = None,
        on_quit: Callable[[], None] | None = None,
    ) -> None:
        self._title = title
        self._on_open_settings = on_open_settings
        self._on_open_console = on_open_console
        self._on_health_check = on_health_check
        self._on_uninstall = on_uninstall
        self._on_quit = on_quit

        self._icon: object | None = None  # pystray.Icon, lazy
        self._images: dict[State, object] = {}  # PIL.Image, lazy
        self._state: State = "idle"
        self._blinking = False
        self._blink_thread: threading.Thread | None = None
        self._blink_stop = threading.Event()
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    def _build(self) -> None:
        import pystray  # type: ignore[import-not-found]
        from PIL import Image  # type: ignore[import-not-found]

        self._images = {
            name: Image.open(io.BytesIO(data)).convert("RGBA")
            for name, data in ICONS.items()
        }
        menu = pystray.Menu(
            pystray.MenuItem(
                "Settings öffnen",
                lambda _icon, _item: self._safe_call(self._on_open_settings),
                default=True,
            ),
            pystray.MenuItem(
                "Konto & Keys",
                lambda _icon, _item: self._safe_call(self._on_open_console),
            ),
            pystray.MenuItem(
                "Backend-Health prüfen",
                lambda _icon, _item: self._safe_call(self._on_health_check),
            ),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(
                "Sprichblitz entfernen …",
                lambda _icon, _item: self._safe_call(self._on_uninstall),
            ),
            pystray.MenuItem(
                "Beenden",
                lambda _icon, _item: self._handle_quit(),
            ),
        )
        self._icon = pystray.Icon(
            "sprichblitz",
            icon=self._images["idle"],
            title=self._title,
            menu=menu,
        )

    def run(self) -> None:
        """Blockiert: pystray-Mainloop. Auf Windows aus dem Hauptthread aufrufen."""
        self._build()
        assert self._icon is not None
        self._icon.run()  # type: ignore[attr-defined]

    def run_detached(self) -> None:
        """Startet pystray in eigenem Thread (für Tests / Sub-Loops)."""
        self._build()
        assert self._icon is not None
        thread = threading.Thread(
            target=self._icon.run,  # type: ignore[attr-defined]
            name="sprichblitz-tray",
            daemon=True,
        )
        thread.start()

    def stop(self) -> None:
        self._stop_blink()
        with self._lock:
            if self._icon is not None:
                try:
                    self._icon.stop()  # type: ignore[attr-defined]
                except Exception as exc:  # pragma: no cover - defensive
                    logger.warning("Tray-Stop fehlgeschlagen: {}", exc)

    # ------------------------------------------------------------------
    # State + Tooltip
    # ------------------------------------------------------------------
    def set_state(
        self,
        state: State,
        *,
        tooltip: str | None = None,
        blink: bool = False,
    ) -> None:
        with self._lock:
            self._state = state
            if self._icon is not None and state in self._images:
                self._icon.icon = self._images[state]  # type: ignore[attr-defined]
            if tooltip and self._icon is not None:
                self._icon.title = tooltip  # type: ignore[attr-defined]

        if blink and state == "error":
            self._start_blink()
        else:
            self._stop_blink()

    def set_tooltip(self, tooltip: str) -> None:
        with self._lock:
            if self._icon is not None:
                self._icon.title = tooltip  # type: ignore[attr-defined]

    def notify_balloon(self, title: str, message: str) -> None:
        """Balloon-Tip am Tray-Icon (Shell_NotifyIcon mit NIIF_INFO).

        Im Gegensatz zu WinRT-Toasts ist die Anzeige transient und
        landet typischerweise nicht in der Action-Center-Historie –
        passend für nicht-kritische Hinweise wie Recording-Start.
        Dauer wird vom System bestimmt (~3–5 s).
        """
        if self._icon is None:
            return
        try:
            # pystray ruft intern Shell_NotifyIcon mit NIM_MODIFY/NIF_INFO
            # auf dem bereits registrierten Tray-Icon auf.
            self._icon.notify(message, title=title)  # type: ignore[attr-defined]
        except Exception as exc:  # pragma: no cover - defensiv
            logger.warning("Balloon-Tip fehlgeschlagen: {}", exc)

    @property
    def state(self) -> State:
        return self._state

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    def _start_blink(self) -> None:
        if self._blinking:
            return
        self._blinking = True
        self._blink_stop.clear()
        self._blink_thread = threading.Thread(
            target=self._blink_loop, name="sprichblitz-tray-blink", daemon=True
        )
        self._blink_thread.start()

    def _stop_blink(self) -> None:
        if not self._blinking:
            return
        self._blink_stop.set()
        self._blinking = False
        if self._blink_thread is not None:
            self._blink_thread.join(timeout=1.0)
            self._blink_thread = None

    def _blink_loop(self) -> None:
        toggle = False
        while not self._blink_stop.is_set():
            toggle = not toggle
            with self._lock:
                if self._icon is None:
                    return
                key: State = "error" if toggle else "idle"
                self._icon.icon = self._images[key]  # type: ignore[attr-defined]
            time.sleep(BLINK_INTERVAL_S)
        # Final-State zurücksetzen.
        with self._lock:
            if self._icon is not None and self._state in self._images:
                self._icon.icon = self._images[self._state]  # type: ignore[attr-defined]

    def _handle_quit(self) -> None:
        self._stop_blink()
        if self._on_quit is not None:
            self._safe_call(self._on_quit)
        self.stop()

    @staticmethod
    def _safe_call(callback: Callable[[], None] | None) -> None:
        if callback is None:
            return
        try:
            callback()
        except Exception as exc:
            logger.exception("Tray-Callback-Fehler: {}", exc)
