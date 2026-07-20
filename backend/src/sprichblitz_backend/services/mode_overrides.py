"""Per-User-Modi-Overrides: Speicherung, Merge in die Mode-Config, Anzeige.

Merge-Präzedenz (Etappe 4 / voll editierbar):
    Backend-Default  <  gespeicherter User-Override  <  Per-Request-Override
alles innerhalb der Location-/Allowlist-Grenze. ``apply_user_override`` mergt
``stt_provider``/``llm_provider``/``llm_model``/``apply_llm``/``system_prompt``
in die Mode-Config (Provider nur, wenn in der Registry – defensiv gegen
Config-Drift). Im local-Modus überschreibt ``resolve_mode_for_location`` STT/LLM
anschliessend **still** mit den lokalen Providern (kein Fehler). Der
Per-Request-Override läuft danach durch ``build_effective_mode`` (in local hart
auf die lokalen Provider begrenzt).
"""

from __future__ import annotations

from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlmodel import Session, select

from ..db.models import ModeOverride, utcnow
from ..models.config_models import ModeConfig
from ..providers.registry import ProviderRegistry


def get_override(session: Session, user_id: int, mode_key: str) -> ModeOverride | None:
    return session.exec(
        select(ModeOverride).where(
            ModeOverride.user_id == user_id, ModeOverride.mode_key == mode_key
        )
    ).first()


def list_overrides(session: Session, user_id: int) -> dict[str, ModeOverride]:
    rows = session.exec(select(ModeOverride).where(ModeOverride.user_id == user_id)).all()
    return {row.mode_key: row for row in rows}


def upsert_override(
    session: Session,
    user_id: int,
    mode_key: str,
    *,
    display_name: str | None = None,
    system_prompt: str | None = None,
    stt_provider: str | None = None,
    llm_provider: str | None = None,
    llm_model: str | None = None,
    apply_llm: bool | None = None,
    enabled: bool = True,
) -> ModeOverride:
    # Atomarer Upsert (ON CONFLICT) statt Read-modify-write: zwei parallele PUTs
    # desselben (user_id, mode_key) verletzten sonst beide den Unique-Constraint
    # → 500. Alle Felder werden gesetzt (Full-Replace, wie die Route sie schickt).
    now = utcnow()
    cols = dict(
        display_name=display_name,
        system_prompt=system_prompt,
        stt_provider=stt_provider,
        llm_provider=llm_provider,
        llm_model=llm_model,
        apply_llm=apply_llm,
        enabled=enabled,
    )
    stmt = sqlite_insert(ModeOverride).values(
        user_id=user_id, mode_key=mode_key, created_at=now, updated_at=now, **cols
    ).on_conflict_do_update(
        index_elements=["user_id", "mode_key"],
        set_={**cols, "updated_at": now},
    )
    session.execute(stmt)
    session.commit()
    return get_override(session, user_id, mode_key)


def delete_override(session: Session, user_id: int, mode_key: str) -> bool:
    row = get_override(session, user_id, mode_key)
    if row is None:
        return False
    session.delete(row)
    session.commit()
    return True


def delete_all_for_mode(session: Session, mode_key: str) -> int:
    """Alle per-User-Overrides eines Modus löschen. Aufgerufen beim Löschen eines
    DB-Modus, damit keine verwaisten Zeilen zurückbleiben (die bei einem später
    gleichnamig neu angelegten Modus still „wieder auftauchen" würden)."""
    rows = session.exec(select(ModeOverride).where(ModeOverride.mode_key == mode_key)).all()
    for row in rows:
        session.delete(row)
    session.commit()
    return len(rows)


def apply_user_override(
    mode: ModeConfig, override: ModeOverride | None, *, registry: ProviderRegistry
) -> ModeConfig:
    """Merge des gespeicherten Overrides in die Mode-Config (provider-relevant).

    Übernimmt ``system_prompt``, ``stt_provider``→``stt``, ``llm_provider``→``llm``,
    ``llm_model`` und das Tri-State ``apply_llm``. Provider-Felder greifen nur,
    wenn sie in der Registry stehen (defensiv gegen Config-Drift – nie ein 500
    wegen einer veralteten Präferenz). Wählt der Nutzer eine STT bewusst, wird der
    ``fallback_stt`` geleert (kein stiller Cloud-Fallback). ``display_name``/
    ``enabled`` sind Anzeige-/Steuerungs-Concerns und gehören nicht in die
    Provider-Auflösung.
    """
    if override is None:
        return mode
    updates: dict[str, object] = {}
    if override.system_prompt:
        updates["system_prompt"] = override.system_prompt
    if override.stt_provider and override.stt_provider in registry.stt:
        updates["stt"] = override.stt_provider
        updates["fallback_stt"] = None
    if override.llm_provider and override.llm_provider in registry.llm:
        updates["llm"] = override.llm_provider
    if override.llm_model:
        updates["llm_model"] = override.llm_model
    if override.apply_llm is not None:
        updates["apply_llm"] = override.apply_llm
    return mode.model_copy(update=updates) if updates else mode


def effective_display_name(mode: ModeConfig, override: ModeOverride | None) -> str:
    if override is not None and override.display_name:
        return override.display_name
    return mode.description


def is_enabled(override: ModeOverride | None) -> bool:
    return override.enabled if override is not None else True
