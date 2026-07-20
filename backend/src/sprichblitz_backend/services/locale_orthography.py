"""Locale-gesteuerte deterministische Orthografie-Korrektur.

Whisper folgt Orthografie-Anweisungen via ``prompt`` nicht zuverlaessig
(es schreibt weiter ``ss``-statt-``ss``-frage einfach falsch). Deshalb
wenden wir nach dem STT-Schritt eine **deterministische** Regel an,
gesteuert von einer vom Client gemeldeten Locale (typischerweise
abgeleitet vom aktiven Tastaturlayout): das ist die Garantie, nicht
der Modell-Output.

Heute aktiv: alle ``*-CH``-Locales bekommen ``ss``-Erzwingung
angewandt (Schweizer Standarddeutsch nutzt ausnahmslos ``ss``). Die
Tabelle kann ohne Architektur-Arbeit wachsen.
"""

from __future__ import annotations

# Unicode-Codepoints statt Literal-Glyphen im Quelltext, damit der
# Parser kein Theater mit typografischen Anfuehrungszeichen macht.
_ESZETT_LOWER = "ß"  # ß
_ESZETT_UPPER = "ẞ"  # ẞ


def _is_swiss(locale: str | None) -> bool:
    if not locale:
        return False
    return locale.strip().lower().endswith("-ch")


def apply_locale_orthography(text: str, locale: str | None) -> str:
    """Wendet locale-spezifische Orthografie-Regeln auf ``text`` an.

    - Schweizer Locale (``*-CH``): ``ß`` -> ``ss``, ``ẞ`` -> ``SS``.
    - Andere/keine Locale: Text unveraendert.

    Pure Funktion (idempotent, ohne Seiteneffekt) - damit unit-testbar
    und ueberall im Pipeline-Pfad anwendbar (STT-Output und LLM-Output).
    """
    if not text:
        return text
    if _is_swiss(locale):
        return text.replace(_ESZETT_LOWER, "ss").replace(_ESZETT_UPPER, "SS")
    return text


def swiss_orthography_hint() -> str:
    """Zusatz fuer den LLM-System-Prompt bei Schweizer Locale (Bonus,
    nicht die Garantie - die kommt aus :func:`apply_locale_orthography`)."""
    return (
        "\n\nWichtig: Verwende Schweizer Standarddeutsch. "
        "Schreibe immer 'ss' statt 'ß' "
        "(z. B. 'weiss', 'gross', 'Strasse'); 'ß' kommt im "
        "Schweizer Hochdeutsch nicht vor."
    )


def llm_system_prompt_for_locale(base: str, locale: str | None) -> str:
    """Haengt den Schweizer Orthografie-Hinweis an, wenn Locale Swiss ist."""
    if _is_swiss(locale):
        return base + swiss_orthography_hint()
    return base
