"""Windows-Tastaturlayout zu BCP47-Locale.

Der Client erkennt das aktive Tastaturlayout (bevorzugt das des
Vordergrund-Fensters, damit z. B. Excel-vs-Notepad sauber unterscheidbar
bleibt, falls je zwei Layouts gepflegt werden) und meldet die abgeleitete
Locale ans Backend. Dort entscheidet eine deterministische Regeltabelle,
ob/wie Orthografie nachkorrigiert wird (heute: ``*-CH`` -> ``ss``).

Pure Funktion :func:`klid_to_locale` ist cross-platform unit-testbar;
:func:`current_keyboard_locale` ist Windows-only und lazy-importiert
``ctypes`` erst zur Laufzeit (No-Op auf macOS/Linux).
"""

from __future__ import annotations

import sys

# LANGID (untere 16 Bit der HKL) -> BCP47-Locale.
# Fokus auf DACH + Schweiz (alle vier Landessprachen) plus ein paar
# gaengige Defaults. Unbekannte Werte -> None (Backend macht dann
# nichts, voll abwaertskompatibel).
_LANGID_TO_LOCALE: dict[str, str] = {
    "0407": "de-DE",
    "0807": "de-CH",
    "0c07": "de-AT",
    "1007": "de-LU",
    "1407": "de-LI",
    "040c": "fr-FR",
    "100c": "fr-CH",
    "0c0c": "fr-CA",
    "0410": "it-IT",
    "0810": "it-CH",
    "0417": "rm-CH",
    "0409": "en-US",
    "0809": "en-GB",
}


def klid_to_locale(klid_hex: str) -> str | None:
    """Mappt einen KLID/LANGID-Hex-String auf eine BCP47-Locale.

    Akzeptiert sowohl die volle 8-stellige KLID (z. B. ``00000807``) als
    auch nur die 4-stellige LANGID (``0807``). Gross-/Kleinschreibung egal.
    """
    if not klid_hex:
        return None
    h = klid_hex.strip().lower()
    if len(h) > 4:
        h = h[-4:]
    return _LANGID_TO_LOCALE.get(h)


def current_keyboard_locale() -> str | None:
    """Aktive Tastaturlayout-Locale des Vordergrund-Fensters.

    Auf Nicht-Windows oder bei Fehlern -> ``None`` (Aufrufer behandelt
    das als "kein Hint", Backend macht keinen Eingriff)."""
    if sys.platform != "win32":
        return None
    try:
        import ctypes

        user32 = ctypes.windll.user32  # type: ignore[attr-defined]
        hwnd = user32.GetForegroundWindow()
        tid = 0
        if hwnd:
            tid = user32.GetWindowThreadProcessId(hwnd, None)
        hkl = user32.GetKeyboardLayout(tid)
        langid = int(hkl) & 0xFFFF
        return klid_to_locale(f"{langid:04x}")
    except Exception:  # pragma: no cover - defensiv
        return None


def resolve_effective_locale(override: str) -> str | None:
    """Setzt die ``locale_override``-Einstellung in eine echte Locale um.

    - ``"auto"`` -> Tastaturlayout erkennen (oder None bei Fehler).
    - ``"off"`` / leer -> None (Backend macht keinen Eingriff).
    - sonst -> der String selbst (z. B. ``"de-CH"``).
    """
    if not override or override == "off":
        return None
    if override == "auto":
        return current_keyboard_locale()
    return override
