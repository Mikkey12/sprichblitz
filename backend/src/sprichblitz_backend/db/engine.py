"""SQLite-Engine + Session-Dependency.

SQLite-spezifische Defaults (wichtig, weil ``verify_bearer`` als sync-Dependency
im FastAPI-Threadpool läuft):

- ``check_same_thread=False`` – der Connection-Pool darf eine Connection
  thread-übergreifend wiederverwenden, ohne SQLites Default-Thread-Check.
- Connect-Listener setzt ``journal_mode=WAL`` (Schreibzugriffe sperren nicht die
  ganze DB → Nebenläufigkeit ab Etappe 5), ``foreign_keys=ON`` (FK-Constraints
  greifen in SQLite nur explizit), ``busy_timeout`` und ``synchronous=NORMAL``.

Der Default-DB-Pfad wird **absolut** aus der Modulposition aufgelöst, nicht
CWD-relativ – sonst zeigen LaunchAgent-Start (CWD irgendwo) und manueller Start
``python -m`` (CWD = Projektordner) auf unterschiedliche DB-Dateien.
``SPRICHBLITZ_DB_URL`` bleibt der Override.
"""

from __future__ import annotations

import contextlib
import os
from collections.abc import Iterator
from pathlib import Path

from fastapi import Request
from sqlalchemy import event
from sqlalchemy.engine import Engine, make_url
from sqlmodel import Session, create_engine

# .../backend/src/sprichblitz_backend/db/engine.py → parents[3] == backend/
_BACKEND_DIR = Path(__file__).resolve().parents[3]
DEFAULT_DB_PATH = _BACKEND_DIR / "sprichblitz.db"


def default_database_url() -> str:
    """Absolut verankerte Default-URL; ``SPRICHBLITZ_DB_URL`` überschreibt."""
    override = os.getenv("SPRICHBLITZ_DB_URL", "").strip()
    if override:
        return override
    return f"sqlite:///{DEFAULT_DB_PATH}"


def _apply_sqlite_pragmas(dbapi_connection, _connection_record) -> None:  # noqa: ANN001
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA busy_timeout=5000")
    cursor.execute("PRAGMA synchronous=NORMAL")
    cursor.close()


def _sqlite_file_path(resolved: str) -> Path | None:
    """Dateipfad einer SQLite-URL, oder ``None`` für In-Memory/URL-less DBs."""
    db = make_url(resolved).database
    if not db or db == ":memory:":
        return None
    return Path(db)


def _restrict_db_perms(db_path: Path) -> None:
    """DB/WAL/SHM best effort auf 0600 einschränken.

    Das Elternverzeichnis wird absichtlich nicht verändert: Beim Standardpfad
    ist dies der geteilte ``backend/``-Projektordner. Ihn auf 0700 zu setzen
    würde Checkout, CI und andere lokale Benutzer unerwartet aussperren.
    """
    for name in (db_path.name, db_path.name + "-wal", db_path.name + "-shm"):
        f = db_path.with_name(name)
        if f.exists():
            with contextlib.suppress(OSError):
                f.chmod(0o600)


def create_db_engine(url: str | None = None, **kwargs) -> Engine:
    """Engine mit SQLite-sicheren Defaults.

    ``url`` fällt auf :func:`default_database_url` zurück. Zusätzliche ``kwargs``
    gehen an ``create_engine`` (Tests übergeben ``poolclass=StaticPool`` für eine
    geteilte In-Memory-DB).
    """
    resolved = url or default_database_url()
    is_sqlite = resolved.startswith("sqlite")
    connect_args = {"check_same_thread": False} if is_sqlite else {}
    engine = create_engine(resolved, connect_args=connect_args, **kwargs)
    if is_sqlite:
        event.listen(engine, "connect", _apply_sqlite_pragmas)
        db_path = _sqlite_file_path(resolved)
        if db_path is not None:
            _restrict_db_perms(db_path)  # bestehende DB (Live) sofort einschränken
            # Nach dem WAL-Pragma erneut anwenden. Bei einer frischen DB existiert
            # die Datei erst beim Connect; spätere Connections erfassen auch neu
            # angelegte WAL-/SHM-Dateien.
            event.listen(engine, "connect", lambda _c, _r: _restrict_db_perms(db_path))
    return engine


def get_session(request: Request) -> Iterator[Session]:
    """FastAPI-Dependency: Session aus der App-Engine (``app.state.db_engine``)."""
    engine: Engine = request.app.state.db_engine
    with Session(engine) as session:
        yield session
