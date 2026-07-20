"""Schützt gegen „grüne Tests, kaputte Migration": fährt alle Alembic-
Migrationen gegen eine Wegwerf-DB und prüft, dass das resultierende Schema
nicht von den SQLModel-Modellen abdriftet.
"""

from __future__ import annotations

from pathlib import Path

from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from sqlalchemy import create_engine, inspect
from sqlmodel import SQLModel

import sprichblitz_backend.db.models  # noqa: F401  – registriert Tabellen in der Metadata
from alembic import command

_BACKEND_DIR = Path(__file__).resolve().parents[2]
_ALEMBIC_INI = _BACKEND_DIR / "alembic.ini"
_ALEMBIC_DIR = _BACKEND_DIR / "alembic"


def _alembic_config(url: str) -> Config:
    cfg = Config(str(_ALEMBIC_INI))
    # CWD-unabhängig: Script-Location absolut verankern.
    cfg.set_main_option("script_location", str(_ALEMBIC_DIR))
    return cfg


def test_migrations_apply_cleanly_and_match_models(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "drift.db"
    url = f"sqlite:///{db_path}"
    # env.py liest die URL über default_database_url() → SPRICHBLITZ_DB_URL.
    monkeypatch.setenv("SPRICHBLITZ_DB_URL", url)

    # 1) Laufen alle Migrationen sauber durch?
    command.upgrade(_alembic_config(url), "head")

    engine = create_engine(url)
    try:
        # 2) Tabellen vorhanden?
        tables = set(inspect(engine).get_table_names())
        assert {"users", "api_tokens"} <= tables

        # 3) Kein Drift zwischen migriertem Schema und den Modellen.
        with engine.connect() as conn:
            ctx = MigrationContext.configure(conn)
            diffs = compare_metadata(ctx, SQLModel.metadata)
    finally:
        engine.dispose()

    # alembic_version ist Alembics eigene Tabelle (nicht in den Modellen) → ignorieren.
    meaningful = [d for d in diffs if "alembic_version" not in repr(d)]
    assert meaningful == [], f"Schema driftet von den Modellen: {meaningful}"
