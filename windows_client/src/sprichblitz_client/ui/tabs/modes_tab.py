"""Settings-Tab: Modi → Hotkey pro Modus.

Pro Modus nur noch die Hotkey-Zuweisung (tippen oder „Aufnehmen"). Provider-,
STT- und LLM-Wahl wird zentral im Backend pro Nutzer gepflegt (Konsole: Modi +
processing_location) – der Client schickt nur noch den Modus an ``/full`` (d4).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping

from loguru import logger

from ...config import ClientConfig, HotkeyBinding, _default_hotkeys
from ...hotkeys.base import InvalidHotkeyError, altgr_risk, parse_hotkey
from ...models import Mode, ModeStatus, display_name
from .. import palette

MODE_LABELS: dict[Mode, str] = {
    Mode.exact_de: "Exakt (Deutsch)",
    Mode.exact_swiss: "Exakt (Schweizerdeutsch)",
    Mode.mail: "E-Mail-Stil",
    Mode.rage: "Höflich-Übersetzer",
    Mode.emoji: "Emoji-Würze",
}

# Tasten, die sich beim "Hotkey aufnehmen" als reine Modifier qualifizieren
# (werden NICHT als Haupt-Taste übernommen).
_MODIFIER_KEYS = {
    "Control_L",
    "Control_R",
    "Alt_L",
    "Alt_R",
    "Shift_L",
    "Shift_R",
    "Super_L",
    "Super_R",
    "Meta_L",
    "Meta_R",
}


class ModesTab:
    def __init__(
        self,
        parent: object,
        cfg: ClientConfig,
        modes: Mapping[Mode, ModeStatus] | None = None,
        on_dirty: Callable[[], None] | None = None,
    ) -> None:
        import customtkinter as ctk  # type: ignore[import-not-found]

        self._cfg = cfg
        self._modes = dict(modes or {})
        self._on_dirty = on_dirty
        self._hotkey_vars: dict[Mode, object] = {}  # ctk.StringVar

        parent.configure(fg_color=palette.SURFACE)

        # Hotkey-Map aus Config in Lookup umwandeln.
        bindings = {b.mode: b.keys for b in cfg.hotkeys}

        ctk.CTkLabel(
            parent,
            text=(
                "Pro Modus ein Hotkey (tippen oder aufnehmen). Provider, STT und "
                "LLM werden zentral in der Konsole pro Nutzer gepflegt – der Client "
                "sendet nur den Modus."
            ),
            anchor="w",
            justify="left",
            text_color=palette.TEXT_MUTED,
            font=ctk.CTkFont(size=palette.TEXT_SM),
        ).pack(
            fill="x",
            padx=palette.SPACE_5,
            pady=(palette.SPACE_4, palette.SPACE_2),
        )

        ctk.CTkButton(
            parent,
            text="CH-Tastatur-Defaults (Ctrl+Shift+F1..F5)",
            command=self._apply_ch_defaults,
            width=280,
            **palette.secondary_button(),
        ).pack(
            anchor="w",
            padx=palette.SPACE_5,
            pady=(0, palette.SPACE_2),
        )

        scroll = ctk.CTkScrollableFrame(
            parent,
            label_text="",
            fg_color=palette.BG,
            border_color=palette.BORDER,
            border_width=1,
            corner_radius=palette.RADIUS_CARD,
        )
        scroll.pack(
            fill="both",
            expand=True,
            padx=palette.SPACE_5,
            pady=(0, palette.SPACE_4),
        )

        for mode in _ordered_modes(cfg, self._modes):
            block = ctk.CTkFrame(scroll, **palette.card_style())
            block.pack(
                fill="x",
                pady=palette.SPACE_1,
                padx=palette.SPACE_1,
            )

            ctk.CTkLabel(
                block,
                text=_mode_label(mode, self._modes),
                text_color=palette.TEXT,
                font=ctk.CTkFont(
                    size=palette.TEXT_SM,
                    weight=palette.WEIGHT_BOLD,
                ),
                anchor="w",
            ).grid(
                row=0,
                column=0,
                columnspan=3,
                sticky="w",
                padx=palette.SPACE_3,
                pady=(palette.SPACE_2, 0),
            )

            ctk.CTkLabel(
                block,
                text="Hotkey:",
                anchor="e",
                text_color=palette.TEXT_MUTED,
            ).grid(
                row=1,
                column=0,
                sticky="e",
                padx=(palette.SPACE_3, palette.SPACE_2),
                pady=(0, palette.SPACE_2),
            )
            hotkey_var = ctk.StringVar(value=bindings.get(mode, ""))
            hotkey_var.trace_add("write", lambda *_a: self._mark_dirty())
            self._hotkey_vars[mode] = hotkey_var

            entry = ctk.CTkEntry(block, textvariable=hotkey_var, width=220, **palette.entry_style())
            entry.grid(row=1, column=1, sticky="w", pady=(0, palette.SPACE_2))

            record_btn = ctk.CTkButton(
                block,
                text="Aufnehmen",
                **palette.secondary_button(),
                width=100,
                command=lambda e=entry, v=hotkey_var: self._record_hotkey(e, v),
            )
            record_btn.grid(
                row=1,
                column=2,
                sticky="w",
                padx=(palette.SPACE_2, palette.SPACE_3),
                pady=(0, palette.SPACE_2),
            )

            block.grid_columnconfigure(1, weight=1)

    # ------------------------------------------------------------------
    def apply(self) -> None:
        """Validiert Hotkeys und schreibt sie zurück in ClientConfig."""
        new_bindings: list[HotkeyBinding] = []
        seen: set[str] = set()
        for mode, var in self._hotkey_vars.items():
            raw = var.get().strip()  # type: ignore[attr-defined]
            if not raw:
                # Leere Hotkey-Slots werden ausgelassen – Mode dann nicht erreichbar.
                continue
            try:
                parse_hotkey(raw)  # validate
            except InvalidHotkeyError as exc:
                raise RuntimeError(f"{mode.value}: ungültiger Hotkey '{raw}' ({exc})") from exc
            if altgr_risk(raw):
                raise RuntimeError(
                    f"{mode.value}: '{raw}' nutzt Ctrl+Alt – das ist auf "
                    "CH/EU-Tastaturen AltGr und kapert Zeichen wie @ # € (AltGr+2 = @). "
                    "Bitte eine andere Combo wählen oder den CH-Defaults-Button nutzen."
                )
            normalized = raw.lower()
            if normalized in seen:
                raise RuntimeError(f"Hotkey '{raw}' ist mehrfach belegt.")
            seen.add(normalized)
            new_bindings.append(HotkeyBinding(mode=mode, keys=raw))
        self._cfg.hotkeys = new_bindings

    def _apply_ch_defaults(self) -> None:
        """Setzt alle Hotkey-Felder auf das AltGr-sichere F-Tasten-Set."""
        defaults = {b.mode: b.keys for b in _default_hotkeys()}
        for mode, var in self._hotkey_vars.items():
            keys = defaults.get(mode)
            if keys:
                var.set(keys)  # type: ignore[attr-defined]

    # ------------------------------------------------------------------
    def _mark_dirty(self) -> None:
        if self._on_dirty is not None:
            self._on_dirty()

    def _record_hotkey(self, entry: object, hotkey_var: object) -> None:
        """Live-Aufnahme: nimmt den nächsten Tastendruck als Hotkey."""
        original_text = hotkey_var.get()  # type: ignore[attr-defined]
        hotkey_var.set("Drücke Tasten …")  # type: ignore[attr-defined]

        def on_key(event):  # noqa: ANN001
            keysym = getattr(event, "keysym", "")
            if not keysym or keysym in _MODIFIER_KEYS:
                # Nur Modifier gedrückt → weiter warten.
                return "break"
            mods: list[str] = []
            state = int(getattr(event, "state", 0))
            # Tk Modifier-Bits (vom X11/Win32-Mapping):
            #   Shift=0x1, Control=0x4, Mod1/Alt=0x8 (oder 0x20000 auf manchen Win),
            #   Mod4/Win=0x40000.
            if state & 0x0004:
                mods.append("ctrl")
            if state & 0x0008 or state & 0x20000:
                mods.append("alt")
            if state & 0x0001:
                mods.append("shift")
            if state & 0x40000:
                mods.append("win")

            key = keysym.lower()
            # Tk gibt Buchstaben oft Gross-/Kleinschreibung-getreu zurück;
            # für die Hotkey-Schreibweise normalisieren wir auf lower-case.
            combo = "+".join(mods + [key])
            try:
                parse_hotkey(combo)
            except InvalidHotkeyError:
                # Konnte nicht geparst werden → Original wiederherstellen.
                hotkey_var.set(original_text)  # type: ignore[attr-defined]
                logger.warning("Hotkey-Aufnahme abgebrochen, '{}' nicht parsebar", combo)
                return "break"
            hotkey_var.set(combo)  # type: ignore[attr-defined]
            entry.unbind("<KeyPress>")  # type: ignore[attr-defined]
            entry.master.focus_set()  # type: ignore[attr-defined]
            return "break"

        entry.focus_set()  # type: ignore[attr-defined]
        entry.bind("<KeyPress>", on_key)  # type: ignore[attr-defined]


def _ordered_modes(
    cfg: ClientConfig,
    modes: Mapping[Mode, ModeStatus],
) -> list[Mode]:
    """Standard-, Config- und Backend-Modi stabil und ohne Duplikate ordnen."""
    ordered: list[Mode] = []
    seen: set[Mode] = set()
    for mode in [*Mode, *(binding.mode for binding in cfg.hotkeys), *modes]:
        if mode not in seen:
            seen.add(mode)
            ordered.append(mode)
    return ordered


def _mode_label(mode: Mode, modes: Mapping[Mode, ModeStatus]) -> str:
    status = modes.get(mode)
    if status is not None:
        return status.display_name
    return MODE_LABELS.get(mode, display_name(mode))
