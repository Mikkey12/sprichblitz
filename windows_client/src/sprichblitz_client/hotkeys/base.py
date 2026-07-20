"""Hotkey-Backend-Basis + plattform-unabhängiger Parser."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass

# Modifier-Bits für Win32 ``RegisterHotKey`` (winuser.h).
MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
MOD_NOREPEAT = 0x4000

_MODIFIER_NAMES = {
    "ctrl": MOD_CONTROL,
    "control": MOD_CONTROL,
    "alt": MOD_ALT,
    "shift": MOD_SHIFT,
    "win": MOD_WIN,
    "super": MOD_WIN,
    "cmd": MOD_WIN,
}

# Virtual-Key-Codes für Nicht-ASCII-Tasten (winuser.h).
_NAMED_VKS = {
    "space": 0x20,
    "tab": 0x09,
    "enter": 0x0D,
    "return": 0x0D,
    "esc": 0x1B,
    "escape": 0x1B,
    "backspace": 0x08,
    "delete": 0x2E,
    "del": 0x2E,
    "home": 0x24,
    "end": 0x23,
    "pageup": 0x21,
    "pagedown": 0x22,
    "left": 0x25,
    "up": 0x26,
    "right": 0x27,
    "down": 0x28,
}
_NAMED_VKS.update({f"f{i}": 0x6F + i for i in range(1, 13)})  # F1..F12 = 0x70..0x7B


@dataclass(frozen=True)
class HotkeyCombo:
    """Geparster Hotkey: Win32-Modifier-Bits + Virtual-Key-Code + Roh-String."""

    modifiers: int
    vk: int
    raw: str


class InvalidHotkeyError(ValueError):
    """Hotkey-String konnte nicht geparst werden."""


def parse_hotkey(value: str) -> HotkeyCombo:
    """Parst Strings wie ``"ctrl+alt+1"`` in einen :class:`HotkeyCombo`."""
    if not value or not value.strip():
        raise InvalidHotkeyError("Leerer Hotkey-String")
    parts = [p.strip().lower() for p in value.split("+") if p.strip()]
    if not parts:
        raise InvalidHotkeyError(f"Ungültiger Hotkey: {value!r}")

    modifiers = 0
    key: str | None = None
    for part in parts:
        if part in _MODIFIER_NAMES:
            modifiers |= _MODIFIER_NAMES[part]
        else:
            if key is not None:
                raise InvalidHotkeyError(
                    f"Mehr als eine Nicht-Modifier-Taste in {value!r}"
                )
            key = part
    if key is None:
        raise InvalidHotkeyError(f"Keine Haupt-Taste in {value!r}")

    if key in _NAMED_VKS:
        vk = _NAMED_VKS[key]
    elif len(key) == 1 and key.isalnum():
        vk = ord(key.upper())
    else:
        raise InvalidHotkeyError(f"Unbekannte Taste {key!r} in {value!r}")
    return HotkeyCombo(modifiers=modifiers, vk=vk, raw=value)


def altgr_risk(value: str) -> bool:
    """True wenn ``value`` eine Ctrl+Alt-Combo über einer druckbaren Taste ist.

    Windows liefert AltGr als Ctrl+Alt, und ``RegisterHotKey`` kann AltGr
    nicht von echtem Ctrl+Alt trennen. ``ctrl+alt+2`` feuert deshalb auf einer
    Schweizer Tastatur bei AltGr+2 (= ``@``) und schluckt das Zeichen. Benannte
    Tasten (f1, space, pfeile) haben kein AltGr-Mapping und sind unkritisch.
    """
    try:
        combo = parse_hotkey(value)
    except InvalidHotkeyError:
        return False
    if not (combo.modifiers & MOD_CONTROL and combo.modifiers & MOD_ALT):
        return False
    parts = [p.strip().lower() for p in value.split("+") if p.strip()]
    key = next((p for p in parts if p not in _MODIFIER_NAMES), None)
    return bool(key and len(key) == 1 and key.isalnum())


class HotkeyBackend(ABC):
    """Backend-Interface; Implementierungen registrieren globale Hotkeys."""

    @abstractmethod
    def register(self, combo: HotkeyCombo, callback: Callable[[], None]) -> None:
        """Registriert einen Hotkey. Mehrfach-Registrierung pro Combo undefined."""

    @abstractmethod
    def start(self) -> None:
        """Startet den Backend-Loop (z.B. Win32-Message-Pump in eigenem Thread)."""

    @abstractmethod
    def stop(self) -> None:
        """Beendet den Loop und gibt Handles frei."""
