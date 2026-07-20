"""Globale Modi: Speicherung + Auflösung gegen die Config.

Auflösungskette (die vollständige steht in ``mode_overrides``):

    config.yml (Kanon)  <  ModeDefinition (global, DB)  <  ModeOverride (pro Nutzer)

``config.yml`` bleibt der git-getrackte Kanon und der Bootstrap für einen frischen
Host; diese Tabelle legt sich darüber und ist zur Laufzeit editierbar – ohne YAML
zu schreiben (Kommentare blieben dabei auf der Strecke) und ohne Neustart.

Zwei Klassen von Modi, und der Unterschied ist keine Willkür, sondern eine
Tatsache: Was in ``config.yml`` steht, kann eine API nicht aus der Datei
entfernen. Deshalb:

* **Config-Modus** → „Löschen" heisst ``enabled=False``: er verschwindet aus der
  effektiven Menge und damit überall (Diktat, ``/me/modes``, ``/config``). Die
  YAML bleibt unangetastet, ein Zurückschalten ist ein Klick.
* **DB-Modus** (nur hier, nicht in der YAML) → echtes DELETE.

``effective_modes`` ist die einzige Stelle, die beides zusammenführt. Alles, was
früher direkt ``cfg.modes`` las, geht jetzt hier durch – sonst kennt ein Endpunkt
Modi, die ein anderer nicht kennt.
"""

from __future__ import annotations

from loguru import logger
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from ..db.models import ModeDefinition, utcnow
from ..models.config_models import AppConfig, ModeConfig

# Felder, die eine ModeDefinition in eine ModeConfig überträgt. ``description``
# und ``stt`` stehen bewusst zuerst: sie sind die Pflichtfelder eines DB-Modus.
_MODE_FIELDS = (
    "description",
    "stt",
    "language",
    "prompt_hint",
    "apply_llm",
    "llm",
    "llm_model",
    "output_prefill",
    "system_prompt",
    "fallback_stt",
)


def get_definition(session: Session, mode_key: str) -> ModeDefinition | None:
    return session.exec(
        select(ModeDefinition).where(ModeDefinition.mode_key == mode_key)
    ).first()


def list_definitions(session: Session) -> dict[str, ModeDefinition]:
    rows = session.exec(select(ModeDefinition).order_by(ModeDefinition.mode_key)).all()
    return {row.mode_key: row for row in rows}


def upsert_definition(session: Session, mode_key: str, **fields: object) -> ModeDefinition:
    """Anlegen oder ändern. Nur übergebene Felder werden angefasst (echtes PATCH).

    Race-sicher: legen zwei parallele Requests denselben ``mode_key`` an, verletzt
    der zweite INSERT den Unique-Constraint. Statt eines 500 wird der Konflikt
    gefangen und als Update nachgezogen (ORM-Pfad, damit Spalten-Defaults wie
    ``enabled=True`` beim Anlegen erhalten bleiben)."""

    def _apply(row: ModeDefinition) -> None:
        for key, value in fields.items():
            setattr(row, key, value)
        row.updated_at = utcnow()
        session.add(row)

    row = get_definition(session, mode_key)
    _apply(row if row is not None else ModeDefinition(mode_key=mode_key))
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        _apply(get_definition(session, mode_key))
        session.commit()
    return get_definition(session, mode_key)


def delete_definition(session: Session, mode_key: str) -> bool:
    row = get_definition(session, mode_key)
    if row is None:
        return False
    session.delete(row)
    session.commit()
    return True


def _set_fields(definition: ModeDefinition) -> dict[str, object]:
    """Die gesetzten (nicht-None) Modus-Felder – None heisst „Config-Wert gilt"."""
    return {
        field: getattr(definition, field)
        for field in _MODE_FIELDS
        if getattr(definition, field) is not None
    }


def merge_into(base: ModeConfig, definition: ModeDefinition | None) -> ModeConfig:
    """Config-Modus + globale Überschreibung → effektiver Modus.

    Ohne ``enabled``-Filter: die Verwaltung muss auch deaktivierte Modi anzeigen
    können (sonst liesse sich keiner wieder einschalten), während
    :func:`effective_modes` sie für alle anderen rauswirft.
    """
    if definition is None:
        return base
    fields = _set_fields(definition)
    return base.model_copy(update=fields) if fields else base


def is_standalone(cfg: AppConfig, mode_key: str) -> bool:
    """True, wenn der Modus NUR in der DB lebt – nur der ist wirklich löschbar."""
    return mode_key not in cfg.modes


def build_standalone(definition: ModeDefinition) -> ModeConfig | None:
    """ModeConfig aus einer reinen DB-Definition. ``None``, wenn Pflichtfelder fehlen.

    ``description`` und ``stt`` sind Pflicht; die Routen erzwingen das beim
    Schreiben. Hier trotzdem defensiv: eine unvollständige Zeile (von Hand in der
    DB, aus einer alten Version) darf ``/me/modes`` nicht mit einem 500 zerlegen.
    """
    fields = _set_fields(definition)
    if not fields.get("description") or not fields.get("stt"):
        return None
    return ModeConfig(**fields)


def effective_modes(session: Session, cfg: AppConfig) -> dict[str, ModeConfig]:
    """Die tatsächlich gültigen Modi: config.yml, überlagert von den globalen.

    Deaktivierte fliegen ganz raus – „global deaktiviert" und „gibt es nicht" sind
    nach aussen dasselbe (400 ``mode_not_configured``), sonst müsste jeder
    Endpunkt einen zweiten Sonderfall kennen.
    """
    modes = dict(cfg.modes)
    for mode_key, definition in list_definitions(session).items():
        if not definition.enabled:
            modes.pop(mode_key, None)
            continue
        base = modes.get(mode_key)
        if base is not None:
            modes[mode_key] = merge_into(base, definition)
            continue
        standalone = build_standalone(definition)
        if standalone is None:
            logger.warning(
                "Skipping incomplete mode definition (needs description + stt)",
                mode=mode_key,
            )
            continue
        modes[mode_key] = standalone
    return modes


def resolve_mode(session: Session, cfg: AppConfig, mode_key: str) -> ModeConfig | None:
    """Ein einzelner Modus aus der effektiven Menge – ``None``, wenn es ihn nicht gibt."""
    return effective_modes(session, cfg).get(mode_key)
