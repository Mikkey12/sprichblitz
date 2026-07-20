"""Shared client-side models.

Die bekannten Modi bleiben als Konstanten erhalten, der Backend-Vertrag ist
aber config-getrieben: neue ``mode_key``-Werte müssen ohne Client-Release
verarbeitet werden können.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel


class Mode(StrEnum):
    exact_de = "exact_de"
    exact_swiss = "exact_swiss"
    mail = "mail"
    rage = "rage"
    emoji = "emoji"

    @classmethod
    def _missing_(cls, value: object) -> Mode | None:
        """Erzeuge für jeden nichtleeren String einen dynamischen Mode-Wert.

        Damit bleiben ``Mode.exact_de`` und die fünf bisherigen Defaults
        rückwärtskompatibel, während Pydantic, Config und Wire-Format nicht auf
        die lokal bekannten Enum-Mitglieder begrenzt sind.
        """
        if not isinstance(value, str) or not value:
            return None
        member = str.__new__(cls, value)
        member._name_ = None
        member._value_ = value
        cls._value2member_map_[value] = member
        return member


MODE_DISPLAY_NAMES: dict[Mode, str] = {
    Mode.exact_de: "Deutsch exakt",
    Mode.exact_swiss: "Schweizerdeutsch",
    Mode.mail: "E-Mail (höflich)",
    Mode.rage: "Höflich umformuliert",
    Mode.emoji: "Mit Emojis",
}


def display_name(mode: Mode) -> str:
    """Anzeigename für UI/Tooltip; Fallback auf Slug bei unbekanntem Mode."""
    return MODE_DISPLAY_NAMES.get(mode, mode.value)


class FullResult(BaseModel):
    """Client-Sicht auf die /full-Response des Backends."""

    mode: Mode
    raw_text: str
    final_text: str
    stt_provider: str
    stt_model: str
    llm_provider: str | None = None
    llm_model: str | None = None
    used_fallback: bool = False
    total_duration_ms: int


class ModeStatus(BaseModel):
    """Pro-Modus-Status aus ``/me/modes``: ist der Modus für diesen Nutzer aktiv,
    plus sein effektiver Anzeigename (für Toast/Tooltip)."""

    enabled: bool = True
    display_name: str


class MeInfo(BaseModel):
    """Client-Sicht auf ``GET /me``: Name + aktive processing_location (für Tooltip)."""

    name: str
    processing_location: str


class BackendError(Exception):
    """Strukturierter Backend-Fehler (gespiegelt von ErrorResponse)."""

    def __init__(
        self,
        *,
        error: str,
        code: str,
        provider: str | None = None,
        http_status: int | None = None,
    ) -> None:
        self.error = error
        self.code = code
        self.provider = provider
        self.http_status = http_status
        super().__init__(f"[{code}] {error}" + (f" (provider={provider})" if provider else ""))
