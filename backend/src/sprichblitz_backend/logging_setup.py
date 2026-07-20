from __future__ import annotations

import inspect
import logging
import os
import sys
from typing import Any

from loguru import logger

# Felder, die sich aus Records auf jeden Fall heraushalten müssen.
# Dadurch verhindern wir, dass jemand versehentlich rohe Audio- oder
# Transkript-Daten in die Logs gibt.
_FORBIDDEN_KEYS: frozenset[str] = frozenset(
    {
        "audio",
        "audio_bytes",
        "raw_audio",
        "wav",
        "pcm",
        "transcript",
        "text",
        "raw_text",
        "final_text",
        "system_prompt",
        "user_prompt",
        "completion",
        # Upstream-Fehlerdetails (P1-2-DEBUG-Logs in providers/): 4xx-Bodies
        # können Request-Inhalte (Transkript-Text) echoen. Backstop, falls ein
        # Sink extras rendert (serialize=True / {extra} im Format).
        "body",
        "detail",
        # Key-/Secret-Material (Stage-1-Härtung): nie über extra in Logs.
        "key",
        "api_key",
        "provider_key",
        "token",
        "secret",
    }
)


def _redact(record: dict[str, Any]) -> None:
    """Loguru-Patcher: entfernt verbotene Keys aus ``extra``."""
    extra = record.get("extra")
    if not isinstance(extra, dict):
        return
    for key in list(extra.keys()):
        if key in _FORBIDDEN_KEYS:
            extra[key] = "<redacted>"


class _InterceptHandler(logging.Handler):
    """Leitet stdlib-``logging``-Records (v. a. ``uvicorn.error``) durch Loguru.

    Schließt die ``log_config=None``-Lücke: uvicorns Startup-Zeilen
    ("Started server process", "Application startup complete", "Uvicorn running
    on …") erscheinen so im selben Loguru-Format/Sink. ``uvicorn.access`` ist via
    ``access_log=False`` ohnehin aus (Client-Addr = PII).
    """

    def emit(self, record: logging.LogRecord) -> None:
        try:
            level: str | int = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno
        # Kanonische loguru-Recipe: vom emit-Frame nach oben laufen, bis wir das
        # logging-Modul verlassen → {function}:{line} zeigen auf den echten
        # Aufrufer (z. B. uvicorns serve), nicht auf logging-Interna.
        frame, depth = inspect.currentframe(), 0
        while frame is not None and (depth == 0 or frame.f_code.co_filename == logging.__file__):
            frame = frame.f_back
            depth += 1
        # {name} auf den stdlib-Logger-Namen setzen (z. B. "uvicorn.error"), sonst
        # zeigte loguru das Aufrufer-Modul statt des Loggers.
        logger.patch(lambda r: r.update(name=record.name)).opt(
            depth=depth, exception=record.exc_info
        ).log(level, record.getMessage())


def configure_logging(level: str | None = None) -> None:
    """Configure Loguru with stdout sink, INFO default, and a redaction filter.

    The level can be overridden via the ``SPRICHBLITZ_LOG_LEVEL`` env var.
    Calling this function multiple times is safe; previous sinks are removed.
    """
    effective_level = (level or os.getenv("SPRICHBLITZ_LOG_LEVEL") or "INFO").upper()

    logger.remove()
    logger.configure(patcher=_redact)
    logger.add(
        sys.stdout,
        level=effective_level,
        backtrace=False,
        diagnose=False,
        enqueue=False,
        format=(
            "<green>{time:YYYY-MM-DD HH:mm:ss}</green> "
            "<level>{level: <8}</level> "
            "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> "
            "- <level>{message}</level>"
        ),
    )

    # uvicorns stdlib-Logger durch Loguru leiten (root/pytest bleiben unangetastet).
    # Mit log_config=None setzt uvicorn weder Handler noch Level → ohne setLevel(INFO)
    # würden die INFO-Startup-Zeilen am geerbten WARNING-Level verworfen.
    intercept = _InterceptHandler()
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        std_logger = logging.getLogger(name)
        std_logger.handlers = [intercept]
        std_logger.propagate = False
        std_logger.setLevel(logging.INFO)
