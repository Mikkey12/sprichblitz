"""usage_daily: atomarer Upsert (keine Lost Updates), Semantik, Aggregat."""

from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy.engine import Engine
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, select

from sprichblitz_backend.db.engine import create_db_engine
from sprichblitz_backend.db.models import UsageDaily, User
from sprichblitz_backend.services import usage

_DAY = date(2026, 6, 6)


@pytest.fixture
def engine() -> Engine:
    eng = create_db_engine("sqlite://", poolclass=StaticPool)
    SQLModel.metadata.create_all(eng)
    with Session(eng) as s:
        s.add(User(name="u1"))
        s.add(User(name="u2"))
        s.commit()
    return eng


def test_upsert_increments_one_row(engine: Engine) -> None:
    with Session(engine) as s:
        for _ in range(5):
            usage.record_success(s, 1, "mail", day=_DAY, audio_seconds=2.0)
        usage.record_error(s, 1, "mail", day=_DAY)
    with Session(engine) as s:
        rows = s.exec(select(UsageDaily)).all()
        assert len(rows) == 1  # Upsert, nicht Insert-pro-Call
        assert rows[0].count == 5
        assert rows[0].errors == 1
        assert rows[0].total_audio_seconds == pytest.approx(10.0)


def test_aggregate_user_scoped_vs_admin(engine: Engine) -> None:
    with Session(engine) as s:
        usage.record_success(s, 1, "mail", day=_DAY, audio_seconds=1.0)
        usage.record_success(s, 1, "mail", day=_DAY, audio_seconds=1.0)
        usage.record_error(s, 1, "rage", day=_DAY)
        usage.record_success(s, 2, "mail", day=_DAY, audio_seconds=5.0)

    with Session(engine) as s:
        u1 = usage.aggregate(s, 1)
        assert u1.per_mode["mail"].requests == 2
        assert u1.per_mode["mail"].total_audio_seconds == pytest.approx(2.0)
        assert u1.per_mode["rage"].errors == 1

        admin = usage.aggregate(s, None)  # alle Nutzer
        assert admin.per_mode["mail"].requests == 3
        assert admin.per_mode["mail"].total_audio_seconds == pytest.approx(7.0)
