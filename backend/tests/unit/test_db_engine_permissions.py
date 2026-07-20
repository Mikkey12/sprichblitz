"""Dateirechte der SQLite-Datenbank und ihrer WAL-Nebenfiles."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import text

from sprichblitz_backend.db.engine import create_db_engine


def _mode(path: Path) -> int:
    return path.stat().st_mode & 0o777


def test_existing_sqlite_files_are_restricted_without_changing_parent(tmp_path: Path) -> None:
    tmp_path.chmod(0o755)
    db = tmp_path / "existing.db"
    sidecars = [db.with_name(f"{db.name}-wal"), db.with_name(f"{db.name}-shm")]
    for path in [db, *sidecars]:
        path.write_bytes(b"")
        path.chmod(0o644)

    engine = create_db_engine(f"sqlite:///{db}")
    try:
        assert _mode(tmp_path) == 0o755
        assert all(_mode(path) == 0o600 for path in [db, *sidecars])
    finally:
        engine.dispose()


def test_fresh_sqlite_db_and_wal_files_are_0600(tmp_path: Path) -> None:
    tmp_path.chmod(0o755)
    db = tmp_path / "fresh.db"
    engine = create_db_engine(f"sqlite:///{db}")

    try:
        with engine.connect() as connection:
            connection.execute(text("CREATE TABLE permission_probe (id INTEGER)"))
            connection.commit()

            assert _mode(tmp_path) == 0o755
            assert _mode(db) == 0o600
            for suffix in ("-wal", "-shm"):
                sidecar = db.with_name(f"{db.name}{suffix}")
                assert sidecar.exists()
                assert _mode(sidecar) == 0o600
    finally:
        engine.dispose()
