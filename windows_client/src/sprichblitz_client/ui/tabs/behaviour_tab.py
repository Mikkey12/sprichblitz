"""Settings-Tab: Verhalten – Aktivierung, VAD, Sound, Auto-Start.

Jeder Punkt hat ein „ⓘ"-Icon mit Kurzbeschreibung (Hover). Der
Mindest-Sprachanteil wird als Prozent angezeigt; intern bleibt es ein
Verhältnis 0..1, damit VAD/Config unverändert funktionieren.
"""

from __future__ import annotations

from collections.abc import Callable

from ...config import ClientConfig
from .. import palette
from ..tooltip import attach_info_icon

# Kurztexte pro Einstellung (ehrlich inkl. bekannter Grenzen).
_HELP = {
    "activation": (
        "toggle: Hotkey drücken startet, nochmal drücken stoppt die Aufnahme.\n"
        "ptt (Push-to-Talk) ist derzeit NICHT implementiert – die Windows-"
        "Hotkey-API meldet kein Tasten-Loslassen; ptt verhält sich daher wie "
        "toggle."
    ),
    "hotkey_backend": (
        "win32: native Windows-Hotkey-API, unauffällig für Virenscanner, kann "
        "aber linkes Alt nicht von AltGr unterscheiden.\n"
        "keyboard_lib: hängt sich global an alle Tasten – robuster bei "
        "Konflikten, für Security-Tools aber sichtbarer. Standard: win32."
    ),
    "inserter": (
        "Wie der erkannte Text an der Cursorposition landet.\n"
        "keyboard_write: simuliertes Tippen (robust, Standard).\n"
        "clipboard_sendinput: über die Zwischenablage (bei Sonderzeichen-/"
        "Layout-Problemen).\npyautogui: Notnagel."
    ),
    "vad_backend": (
        "Stimm-Aktivitätserkennung vor dem Senden (spart leere Anfragen).\n"
        "rms: einfache Lautstärke-Schwelle, immer verfügbar.\n"
        "webrtc: präzisere Erkennung – wirkt nur, wenn das webrtcvad-Paket im "
        "Build enthalten ist, sonst automatischer RMS-Fallback."
    ),
    "vad_threshold": (
        "Ab welcher Lautstärke (dBFS) Ton als Sprache zählt – nur für rms.\n"
        "Tiefer (z. B. −45) = empfindlicher (auch leise Stimme, mehr Rauschen).\n"
        "Höher (−35) = nur lautes Sprechen zählt. Standard −40."
    ),
    "vad_ratio": (
        "Wie viel Prozent der Aufnahme als Sprache erkannt werden muss, damit "
        "überhaupt ans Backend gesendet wird.\nHöher = strenger gegen Stille/"
        "Rauschen, kann aber sehr kurze Äußerungen verwerfen. Standard 5 %."
    ),
    "sound": "Kurzer Ton beim Start und Stopp der Aufnahme.",
    "autostart": (
        "Legt einen Autostart-Eintrag an (HKCU-Run, kein Admin nötig), damit "
        "Sprichblitz nach dem Windows-Login automatisch läuft. Wirkt nur für die "
        "gebaute .exe, nicht beim Start aus dem Quellcode."
    ),
    "toast_recording": ("Zeigt beim Aufnahme-Start eine kleine Sprechblase am Tray-Icon."),
    "locale": (
        "Steuert die Schreibweise/Orthografie.\n"
        "auto = aktives Windows-Tastaturlayout erkennen und mitschicken "
        "(Tool wird damit länderunabhängig).\n"
        "off = nichts senden, das Backend macht keinen Eingriff.\n"
        "Explizit (z. B. de-CH) = fest fixieren.\n"
        "Heute aktive Regel: bei *-CH wird das Eszett deterministisch "
        "durch ss ersetzt (für ALLE Modi, auch ohne LLM)."
    ),
}

LOCALE_CHOICES = [
    "auto",
    "off",
    "de-CH",
    "de-DE",
    "de-AT",
    "fr-CH",
    "fr-FR",
    "it-CH",
    "it-IT",
    "en-US",
    "en-GB",
]


def format_speech_ratio_percent(ratio: float) -> str:
    """0.05 -> '5 %'. Pure Funktion (testbar)."""
    return f"{round(ratio * 100)} %"


class BehaviourTab:
    def __init__(
        self,
        parent: object,
        cfg: ClientConfig,
        on_dirty: Callable[[], None] | None = None,
    ) -> None:
        import customtkinter as ctk  # type: ignore[import-not-found]

        self._ctk = ctk
        self._cfg = cfg
        self._on_dirty = on_dirty

        parent.configure(fg_color=palette.SURFACE)
        content = ctk.CTkScrollableFrame(
            parent,
            fg_color=palette.SURFACE,
            corner_radius=0,
        )
        content.pack(fill="both", expand=True)
        parent = content
        self._parent = content

        self._activation_var = ctk.StringVar(value=cfg.activation)
        self._vad_var = ctk.StringVar(value=cfg.vad_backend)
        self._vad_threshold_var = ctk.DoubleVar(value=float(cfg.vad_rms_threshold_dbfs))
        self._vad_min_ratio_var = ctk.DoubleVar(value=float(cfg.vad_min_speech_ratio))
        self._sound_var = ctk.BooleanVar(value=bool(cfg.sound_enabled))
        self._autostart_var = ctk.BooleanVar(value=bool(cfg.auto_start))
        self._toast_recording_var = ctk.BooleanVar(value=bool(cfg.toast_on_recording_start))
        self._inserter_var = ctk.StringVar(value=cfg.text_inserter)
        self._hotkey_backend_var = ctk.StringVar(value=cfg.hotkey_backend)
        self._locale_var = ctk.StringVar(
            value=cfg.locale_override if cfg.locale_override in LOCALE_CHOICES else "auto"
        )

        for var in (
            self._activation_var,
            self._vad_var,
            self._vad_threshold_var,
            self._vad_min_ratio_var,
            self._sound_var,
            self._autostart_var,
            self._toast_recording_var,
            self._inserter_var,
            self._hotkey_backend_var,
            self._locale_var,
        ):
            var.trace_add("write", lambda *_a: self._mark_dirty())

        # ----- Aktivierung ------------------------------------------------
        self._header("Aktivierung", _HELP["activation"])
        ctk.CTkSegmentedButton(
            parent,
            values=["toggle", "ptt"],
            variable=self._activation_var,
            **palette.segmented_style(),
        ).pack(anchor="w", padx=palette.SPACE_5, pady=(palette.SPACE_1, 0))

        # ----- Hotkey-Backend ---------------------------------------------
        self._header("Hotkey-Backend", _HELP["hotkey_backend"])
        ctk.CTkSegmentedButton(
            parent,
            values=["win32", "keyboard_lib"],
            variable=self._hotkey_backend_var,
            **palette.segmented_style(),
        ).pack(anchor="w", padx=palette.SPACE_5, pady=(palette.SPACE_1, 0))

        # ----- Text-Insertion ---------------------------------------------
        self._header("Text-Einfügen-Methode", _HELP["inserter"])
        ctk.CTkSegmentedButton(
            parent,
            values=["keyboard_write", "clipboard_sendinput", "pyautogui"],
            variable=self._inserter_var,
            **palette.segmented_style(),
        ).pack(anchor="w", padx=palette.SPACE_5, pady=(palette.SPACE_1, 0))

        # ----- VAD-Backend ------------------------------------------------
        self._header("VAD-Backend", _HELP["vad_backend"])
        ctk.CTkSegmentedButton(
            parent,
            values=["rms", "webrtc"],
            variable=self._vad_var,
            **palette.segmented_style(),
        ).pack(anchor="w", padx=palette.SPACE_5, pady=(palette.SPACE_1, 0))

        # ----- Slider: VAD-Schwelle --------------------------------------
        threshold_label_var = ctk.StringVar(
            value=f"VAD-Schwelle: {self._vad_threshold_var.get():.0f} dBFS"
        )

        def update_threshold_label(_value=None):  # noqa: ANN001
            threshold_label_var.set(f"VAD-Schwelle: {self._vad_threshold_var.get():.0f} dBFS")

        self._vad_threshold_var.trace_add("write", lambda *_a: update_threshold_label())
        self._header_var(threshold_label_var, _HELP["vad_threshold"])
        ctk.CTkSlider(
            parent,
            from_=-60,
            to=-20,
            number_of_steps=40,
            variable=self._vad_threshold_var,
            command=update_threshold_label,
            **palette.slider_style(),
        ).pack(fill="x", padx=palette.SPACE_5, pady=(palette.SPACE_1, 0))

        # ----- Slider: Mindest-Sprachanteil (in %) -----------------------
        ratio_label_var = ctk.StringVar(
            value=(
                "Mindest-Sprachanteil: "
                + format_speech_ratio_percent(self._vad_min_ratio_var.get())
            )
        )

        def update_ratio_label(_value=None):  # noqa: ANN001
            ratio_label_var.set(
                "Mindest-Sprachanteil: "
                + format_speech_ratio_percent(self._vad_min_ratio_var.get())
            )

        self._vad_min_ratio_var.trace_add("write", lambda *_a: update_ratio_label())
        self._header_var(ratio_label_var, _HELP["vad_ratio"])
        ctk.CTkSlider(
            parent,
            from_=0.0,
            to=0.30,
            number_of_steps=30,
            variable=self._vad_min_ratio_var,
            command=update_ratio_label,
            **palette.slider_style(),
        ).pack(fill="x", padx=palette.SPACE_5, pady=(palette.SPACE_1, 0))

        # ----- Locale / Schreibweise -------------------------------------
        self._header("Schreibweise / Locale", _HELP["locale"])
        ctk.CTkOptionMenu(
            parent,
            values=LOCALE_CHOICES,
            variable=self._locale_var,
            width=160,
            **palette.option_menu_style(),
        ).pack(anchor="w", padx=palette.SPACE_5, pady=(palette.SPACE_1, 0))

        # ----- Toggles ----------------------------------------------------
        self._checkbox("Sound-Effekte (Start/Stop)", self._sound_var, _HELP["sound"])
        self._checkbox(
            "Beim Login automatisch starten",
            self._autostart_var,
            _HELP["autostart"],
        )
        self._checkbox(
            "Hinweis am Tray-Icon zeigen",
            self._toast_recording_var,
            _HELP["toast_recording"],
        )

    # ------------------------------------------------------------------
    def _header(self, title: str, help_text: str) -> None:
        ctk = self._ctk
        row = ctk.CTkFrame(self._parent, fg_color="transparent")
        row.pack(fill="x", padx=palette.SPACE_5, pady=(palette.SPACE_3, 0))
        ctk.CTkLabel(
            row,
            text=title,
            text_color=palette.TEXT,
            font=ctk.CTkFont(
                size=palette.TEXT_SM,
                weight=palette.WEIGHT_BOLD,
            ),
            anchor="w",
        ).pack(side="left")
        attach_info_icon(row, help_text).pack(
            side="left",
            padx=(palette.SPACE_2, 0),
        )

    def _header_var(self, text_var: object, help_text: str) -> None:
        ctk = self._ctk
        row = ctk.CTkFrame(self._parent, fg_color="transparent")
        row.pack(fill="x", padx=palette.SPACE_5, pady=(palette.SPACE_3, 0))
        ctk.CTkLabel(
            row,
            textvariable=text_var,
            anchor="w",
            text_color=palette.TEXT,
        ).pack(side="left")
        attach_info_icon(row, help_text).pack(
            side="left",
            padx=(palette.SPACE_2, 0),
        )

    def _checkbox(self, text: str, var: object, help_text: str) -> None:
        ctk = self._ctk
        row = ctk.CTkFrame(self._parent, fg_color="transparent")
        row.pack(fill="x", padx=palette.SPACE_5, pady=(palette.SPACE_2, 0))
        ctk.CTkCheckBox(
            row,
            text=text,
            variable=var,
            **palette.checkbox_style(),
        ).pack(side="left")
        attach_info_icon(row, help_text).pack(
            side="left",
            padx=(palette.SPACE_2, 0),
        )

    # ------------------------------------------------------------------
    def apply(self) -> None:
        self._cfg.activation = self._activation_var.get()  # type: ignore[assignment]
        self._cfg.hotkey_backend = self._hotkey_backend_var.get()  # type: ignore[assignment]
        self._cfg.text_inserter = self._inserter_var.get()  # type: ignore[assignment]
        self._cfg.vad_backend = self._vad_var.get()  # type: ignore[assignment]
        self._cfg.vad_rms_threshold_dbfs = float(self._vad_threshold_var.get())
        self._cfg.vad_min_speech_ratio = float(self._vad_min_ratio_var.get())
        self._cfg.sound_enabled = bool(self._sound_var.get())
        self._cfg.auto_start = bool(self._autostart_var.get())
        self._cfg.toast_on_recording_start = bool(self._toast_recording_var.get())
        self._cfg.locale_override = self._locale_var.get()

    def _mark_dirty(self) -> None:
        if self._on_dirty is not None:
            self._on_dirty()
