"""usage_daily: atomare Aggregat-Buchung pro (user, mode, day) – NIE Inhalte.

Inkrement via SQLite-Upsert (``INSERT … ON CONFLICT DO UPDATE SET x = x +
excluded.x``), **nicht** Read-modify-write (sonst Lost Updates unter
Nebenläufigkeit). Semantik: ``count`` = erfolgreicher Durchlauf, ``errors`` =
fehlgeschlagener Provider-Call (429/503/412 werden vom Aufrufer NICHT gebucht).
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date

from sqlalchemy import func, text
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlmodel import Session, select

from ..db.models import UsageDaily, utcnow
from ..models.api import ModeStats, StatsResponse


def _book(
    session: Session,
    user_id: int,
    mode_key: str,
    day: date,
    *,
    count: int,
    errors: int,
    audio: float,
) -> None:
    now = utcnow()
    stmt = sqlite_insert(UsageDaily).values(
        user_id=user_id,
        mode_key=mode_key,
        day=day,
        count=count,
        errors=errors,
        total_audio_seconds=audio,
        created_at=now,
        updated_at=now,
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=["user_id", "mode_key", "day"],
        set_={
            "count": text("count + excluded.count"),
            "errors": text("errors + excluded.errors"),
            "total_audio_seconds": text("total_audio_seconds + excluded.total_audio_seconds"),
            "updated_at": now,
        },
    )
    session.execute(stmt)
    session.commit()


def record_success(
    session: Session,
    user_id: int,
    mode_key: str,
    *,
    day: date | None = None,
    audio_seconds: float = 0.0,
) -> None:
    _book(session, user_id, mode_key, day or utcnow().date(), count=1, errors=0, audio=audio_seconds)


def record_error(
    session: Session, user_id: int, mode_key: str, *, day: date | None = None
) -> None:
    _book(session, user_id, mode_key, day or utcnow().date(), count=0, errors=1, audio=0.0)


def aggregate(
    session: Session,
    user_id: int | None,
    mode_names: Iterable[str] = (),
) -> StatsResponse:
    """Per-Mode-Aggregat. ``user_id=None`` → Admin-Aggregat über alle Nutzer.

    ``mode_names`` = die aktuell KONFIGURIERTEN Modi (aus ``cfg.modes``): sie
    werden mit 0 vorbefüllt, damit neue/ungenutzte Modi in den Stats auftauchen.
    Kein festes Enum mehr. Zusätzlich erscheinen Modi mit historischer Nutzung,
    die nicht (mehr) in der Config stehen (Union), damit alte Daten nicht
    verschwinden.
    """
    query = select(
        UsageDaily.mode_key,
        func.sum(UsageDaily.count),
        func.sum(UsageDaily.errors),
        func.sum(UsageDaily.total_audio_seconds),
    )
    if user_id is not None:
        query = query.where(UsageDaily.user_id == user_id)
    query = query.group_by(UsageDaily.mode_key)

    by_mode = {
        row[0]: (row[1] or 0, row[2] or 0, row[3] or 0.0) for row in session.exec(query).all()
    }
    # Config-Modi zuerst (stabile Reihenfolge), dann etwaige Alt-Modi aus der DB.
    ordered = list(dict.fromkeys([*mode_names, *by_mode.keys()]))
    per_mode: dict[str, ModeStats] = {}
    for mode in ordered:
        count, errors, audio = by_mode.get(mode, (0, 0, 0.0))
        per_mode[mode] = ModeStats(
            requests=int(count), errors=int(errors), total_audio_seconds=float(audio)
        )
    return StatsResponse(per_mode=per_mode)
