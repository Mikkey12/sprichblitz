"""Settings-Hauptfenster (customtkinter, Tabs).

Tabs (siehe ``ui/tabs/``):
    - Backend
    - Modi
    - Verhalten
    - Über

Lifecycle (Singleton)
---------------------
Die :class:`SettingsWindow`-Instanz wird einmal pro App-Lebenszeit
erstellt. ``run()`` baut Window + Tk-Mainloop auf und blockiert. Beim
"Schliessen"-Klick (oder X) wird das Window per :meth:`_on_close` nur
``withdraw``'t – Mainloop läuft weiter. Re-Open via
:meth:`request_show` (thread-safe; verwendet ``after(0, …)``).

Damit entfällt die 10 s-Latenz beim Wieder-Öffnen, die durch das
wiederholte Aufbauen einer ``ctk.CTk()``-Instanz im selben Prozess
entstand.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping

from loguru import logger

from ..config import ClientConfig, save_config
from ..models import Mode, ModeStatus
from . import palette
from .tabs.about_tab import AboutTab
from .tabs.backend_tab import BackendTab
from .tabs.behaviour_tab import BehaviourTab
from .tabs.modes_tab import ModesTab


class SettingsWindow:
    def __init__(
        self,
        cfg: ClientConfig,
        *,
        modes: Mapping[Mode, ModeStatus] | None = None,
        on_saved: Callable[[ClientConfig], None] | None = None,
    ) -> None:
        self._cfg = cfg
        self._modes = dict(modes or {})
        self._on_saved = on_saved
        self._win: object | None = None
        self._dirty = False
        self._tabs: list[object] = []

    def run(self) -> None:
        """Blockt: baut Tk auf und startet Mainloop. Mainloop endet erst bei
        :meth:`request_quit` oder Hauptprozess-Exit (daemon-Thread)."""
        import customtkinter as ctk  # type: ignore[import-not-found]

        # Hell/dunkel folgt dem System – bewusst ohne Umschalter (Design-System).
        # Das Default-Theme „blue" bleibt als Basis für Widget-Geometrie, aber
        # jede sichtbare Fläche bekommt unten die Tokens aus palette.py – sonst
        # würde CustomTkinters Blau die Markenfarbe überschreiben.
        ctk.set_appearance_mode("System")
        ctk.set_default_color_theme("blue")

        win = ctk.CTk()
        self._win = win
        win.title("Sprichblitz – Einstellungen")
        win.geometry("760x680")
        win.minsize(680, 560)
        win.configure(fg_color=palette.BG)

        tabview = ctk.CTkTabview(
            win,
            fg_color=palette.SURFACE,
            segmented_button_selected_color=palette.ACCENT,
            segmented_button_selected_hover_color=palette.ACCENT,
            segmented_button_unselected_color=palette.SURFACE,
            segmented_button_unselected_hover_color=palette.ACCENT_SUBTLE,
            text_color=palette.TEXT,
            corner_radius=palette.RADIUS_CARD,
        )
        tabview.pack(fill="both", expand=True, padx=palette.SPACE_3, pady=(palette.SPACE_3, 0))

        backend_frame = tabview.add("Backend")
        modes_frame = tabview.add("Modi")
        behaviour_frame = tabview.add("Verhalten")
        about_frame = tabview.add("Über")

        backend_tab = BackendTab(backend_frame, self._cfg, on_dirty=self._mark_dirty)
        modes_tab = ModesTab(
            modes_frame,
            self._cfg,
            modes=self._modes,
            on_dirty=self._mark_dirty,
        )
        behaviour_tab = BehaviourTab(behaviour_frame, self._cfg, on_dirty=self._mark_dirty)
        about_tab = AboutTab(about_frame, self._cfg)
        self._tabs = [backend_tab, modes_tab, behaviour_tab, about_tab]

        # ---- Bottom-Bar ----------------------------------------------------
        bottom = ctk.CTkFrame(win, fg_color="transparent")
        bottom.pack(fill="x", padx=palette.SPACE_3, pady=palette.SPACE_3)

        self._status_var = ctk.StringVar(value="")
        self._status_label = ctk.CTkLabel(
            bottom,
            textvariable=self._status_var,
            anchor="w",
            text_color=palette.TEXT_MUTED,
        )
        self._status_label.pack(side="left", fill="x", expand=True)

        # „Ein Akzent pro Ansicht": Die Fussleiste ist auf JEDEM Tab sichtbar,
        # also ist „Speichern" die eine primäre Aktion des ganzen Fensters –
        # deshalb sind sämtliche Tab-Buttons sekundär.
        ctk.CTkButton(
            bottom,
            text="Schliessen",
            width=120,
            command=self._on_close,
            **palette.secondary_button(),
        ).pack(side="right", padx=(palette.SPACE_2, 0))
        ctk.CTkButton(
            bottom,
            text="Speichern",
            width=120,
            command=self._on_save,
            **palette.primary_button(),
        ).pack(side="right")

        win.protocol("WM_DELETE_WINDOW", self._on_close)
        tabview.set("Backend")

        win.mainloop()

    # ------------------------------------------------------------------
    def request_show(self) -> None:
        """Thread-safe: bringt das versteckte Window zurück in den Vordergrund.

        Aus einem anderen Thread (Tray-Callback) aufgerufen, deshalb über
        ``after(0, …)`` an den Mainloop-Thread delegiert."""
        if self._win is None:
            return
        try:
            self._win.after(0, self._do_show)  # type: ignore[attr-defined]
        except Exception as exc:  # pragma: no cover - mainloop dead
            logger.warning("Settings request_show fehlgeschlagen: {}", exc)

    def _do_show(self) -> None:
        if self._win is None:
            return
        try:
            self._win.deiconify()  # type: ignore[attr-defined]
            self._win.lift()  # type: ignore[attr-defined]
            self._win.focus_force()  # type: ignore[attr-defined]
        except Exception as exc:  # pragma: no cover
            logger.warning("Settings _do_show fehlgeschlagen: {}", exc)

    # ------------------------------------------------------------------
    def _mark_dirty(self) -> None:
        self._dirty = True
        try:
            self._status_var.set("Ungespeicherte Änderungen.")
            self._status_label.configure(text_color=palette.TEXT_MUTED)
        except Exception:  # pragma: no cover - vor mainloop
            pass

    def _on_save(self) -> None:
        try:
            for tab in self._tabs:
                tab.apply()  # type: ignore[attr-defined]
        except RuntimeError as exc:
            self._status_var.set(str(exc))
            self._status_label.configure(text_color=palette.DANGER)
            logger.warning("Settings-Apply fehlgeschlagen: {}", exc)
            return
        try:
            save_config(self._cfg)
        except Exception as exc:
            self._status_var.set(f"Config-Datei schreiben fehlgeschlagen: {exc}")
            self._status_label.configure(text_color=palette.DANGER)
            logger.exception("Config-Speichern fehlgeschlagen")
            return

        self._dirty = False
        self._status_var.set("Gespeichert.")
        self._status_label.configure(text_color=palette.SUCCESS)
        if self._on_saved is not None:
            try:
                self._on_saved(self._cfg)
            except Exception as exc:  # pragma: no cover
                logger.exception("on_saved-Callback fehlgeschlagen: {}", exc)

    def _on_close(self) -> None:
        """Hide statt destroy – Mainloop bleibt aktiv für Re-Open."""
        if self._win is None:
            return
        try:
            self._win.withdraw()  # type: ignore[attr-defined]
        except Exception:  # pragma: no cover
            pass
        self._dirty = False
        try:
            self._status_var.set("")
        except Exception:  # pragma: no cover
            pass
