"""SQLModel-Tabellen für Sprichblitz – Etappe 1: Identität & Tokens.

Zeitstempel werden als **naive UTC** gespeichert: SQLite hält keine Zeitzonen,
und :func:`utcnow` liefert konsequent naive UTC, damit Vergleiche (z. B. das
gedrosselte ``last_used_at``-Update in :mod:`..auth`) nie aware/naiv mischen.

``processing_location`` ist eine **String-Spalte** (Werte ``local``/``online``);
die :class:`ProcessingLocation`-Enum dient der Validierung an den Rändern
(Admin-CLI, Principal) – das vermeidet ``sa.Enum``/CHECK-Reflexions-Rauschen im
Migrations-Drift-Test.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from enum import StrEnum

from sqlalchemy import UniqueConstraint
from sqlmodel import Field, SQLModel


def utcnow() -> datetime:
    """Naive UTC (ohne ``tzinfo``) – konsistent über Modelle und Auth."""
    return datetime.now(UTC).replace(tzinfo=None)


class ProcessingLocation(StrEnum):
    """Globaler Verarbeitungsort pro Nutzer (Logik erst ab Etappe 3)."""

    local = "local"
    online = "online"


class User(SQLModel, table=True):
    __tablename__ = "users"

    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(index=True, unique=True)
    display_name: str | None = Field(default=None)
    # Public/fresh-host default: cloud-configured modes work without WhisperKit
    # or LM Studio. Privacy-first local processing remains an explicit user
    # choice and still acts as the global local-provider kill-switch.
    processing_location: str = Field(default=ProcessingLocation.online.value)
    is_admin: bool = Field(default=False)
    disabled: bool = Field(default=False)
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class ApiToken(SQLModel, table=True):
    __tablename__ = "api_tokens"

    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="users.id", index=True)
    token_hash: str = Field(index=True, unique=True)
    label: str | None = Field(default=None)
    last_used_at: datetime | None = Field(default=None)
    revoked: bool = Field(default=False)
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class ProviderKey(SQLModel, table=True):
    """Per-User-API-Key (Fernet-verschlüsselt) für einen BYO-Cloud-Provider.

    ``provider`` ist ein ``ByoProvider``-Wert (als String gespeichert);
    ``ciphertext`` enthält NUR den verschlüsselten Key – niemals Klartext.
    """

    __tablename__ = "provider_keys"
    __table_args__ = (
        UniqueConstraint("user_id", "provider", name="uq_provider_keys_user_provider"),
    )

    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="users.id", index=True)
    provider: str = Field(index=True)
    ciphertext: str
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class ModeDefinition(SQLModel, table=True):
    """Globaler Modus: Definition ODER Überschreibung – gilt für ALLE Nutzer.

    Welche der beiden Rollen, hängt allein davon ab, ob ``mode_key`` auch in
    ``config.yml`` steht:

    * **Überschreibung** eines Config-Modus: gesetzte Felder gewinnen über die
      YAML, ``None`` heisst „Config-Wert gilt". ``enabled=False`` blendet den
      Modus global aus. Die YAML-Zeilen kann eine API nicht entfernen – das
      Deaktivieren ist der ehrliche Ersatz fürs Löschen, und die Konsole nennt
      den Knopf entsprechend.
    * **Eigenständiger Modus**, den die YAML gar nicht kennt (in der Konsole
      angelegt). Dann sind ``description`` und ``stt`` Pflicht, sonst lässt sich
      keine ``ModeConfig`` bauen. Nur dieser lässt sich wirklich löschen.

    Abgrenzung zu :class:`ModeOverride`: das hier ist Admin-Sache und gilt für
    alle; ModeOverride ist die persönliche Anpassung eines Nutzers und gewinnt
    zuletzt. Auflösung: ``config.yml`` (Kanon) → ``ModeDefinition`` → ``ModeOverride``.

    Bewusst eine EIGENE Tabelle statt ``user_id=NULL`` in ``ModeOverride``: SQL
    behandelt NULLs in UNIQUE-Constraints als verschieden – „genau ein globaler
    Eintrag pro Modus" wäre damit gar nicht erzwingbar gewesen (verifiziert
    2026-07-16). Hier greift ``UNIQUE(mode_key)`` schlicht.
    """

    __tablename__ = "mode_definitions"

    id: int | None = Field(default=None, primary_key=True)
    mode_key: str = Field(index=True, unique=True)
    enabled: bool = Field(default=True)
    # Alle Modus-Felder nullable: None = „Config-Wert gilt" (Überschreibungs-Rolle).
    description: str | None = Field(default=None)
    stt: str | None = Field(default=None)
    language: str | None = Field(default=None)
    prompt_hint: str | None = Field(default=None)
    apply_llm: bool | None = Field(default=None)
    llm: str | None = Field(default=None)
    llm_model: str | None = Field(default=None)
    output_prefill: str | None = Field(default=None)
    system_prompt: str | None = Field(default=None)
    fallback_stt: str | None = Field(default=None)
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class ModeOverride(SQLModel, table=True):
    """Per-User-Override eines der 5 festen Modus-Slots (Etappe 4 / voll editierbar).

    Null-Felder = Backend-Default (config.yml) gilt. Alle Provider-Felder werden
    beim Setzen gegen die Registry validiert (nur konfigurierte Provider). Im
    local-Modus überstimmt ``resolve_mode_for_location`` STT/LLM anschliessend
    still mit den lokalen Providern (kein Fehler, Privacy-Hard-Gate). ``stt_provider``
    ersetzt zusätzlich den ``fallback_stt`` (kein stiller Cloud-Fallback, wenn der
    Nutzer die STT bewusst gewählt hat). ``apply_llm`` ist Tri-State:
    ``None`` = Default, sonst erzwungen an/aus.
    """

    __tablename__ = "mode_overrides"
    __table_args__ = (
        UniqueConstraint("user_id", "mode_key", name="uq_mode_overrides_user_mode"),
    )

    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="users.id", index=True)
    mode_key: str = Field(index=True)
    display_name: str | None = Field(default=None)
    system_prompt: str | None = Field(default=None)
    stt_provider: str | None = Field(default=None)
    llm_provider: str | None = Field(default=None)
    llm_model: str | None = Field(default=None)
    apply_llm: bool | None = Field(default=None)
    enabled: bool = Field(default=True)
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class UsageDaily(SQLModel, table=True):
    """Aggregierte Nutzung pro (user, mode, day) – NUR Metadaten, NIE Inhalte.

    ``count`` = erfolgreiche Durchläufe, ``errors`` = fehlgeschlagene Provider-Calls
    (429/503/412 werden NICHT verbucht). Inkrement erfolgt atomar per SQL-Upsert
    (siehe :mod:`..services.usage`), nicht per Read-modify-write.
    """

    __tablename__ = "usage_daily"
    __table_args__ = (
        UniqueConstraint("user_id", "mode_key", "day", name="uq_usage_daily_user_mode_day"),
    )

    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="users.id", index=True)
    mode_key: str = Field(index=True)
    day: date = Field(index=True)
    count: int = Field(default=0)
    total_audio_seconds: float = Field(default=0.0)
    errors: int = Field(default=0)
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
