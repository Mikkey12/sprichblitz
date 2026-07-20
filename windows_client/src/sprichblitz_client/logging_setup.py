"""Loguru-basierter File-Logger mit Rotation.

Default-Level: ``INFO``. Override via Env ``SPRICHBLITZ_LOG_LEVEL``.
Log-Datei: siehe :func:`sprichblitz_client.paths.log_file`.
Logs enthalten KEINE Audio-Bytes und KEINE Transkripte.

Zwei einander ergänzende Absicherungen halten die harte Invariante „keine
Transkripte/Secrets in Logs":

1. ``backtrace=False, diagnose=False`` auf allen Sinks: loguru rendert sonst
   (Default ``diagnose=True``) bei ``logger.exception`` die lokalen Variablen der
   Traceback-Frames – bei einem Insertion-Fehler läge damit der ``final_text`` im
   Klartext in der Log-Datei.
2. Der ``_redact``-Patcher streicht verbotene Keys (Text/Audio/Secrets) aus
   ``extra``, bevor ein Record in die Sinks geht – Backstop, falls je ein Sink
   ``extra`` rendert (``serialize=True``/``{extra}`` im Format) oder ein späterer
   Log-Aufruf versehentlich ``logger.info(..., final_text=…)`` schreibt.

Beides spiegelt das Backend-``logging_setup`` bewusst 1:1 (die Keys sind bewusst
dupliziert, nicht importiert – Client und Backend sind für den Public-Split
getrennte Pakete, wie schon bei den Design-Tokens).
"""

from __future__ import annotations

import os
import sys
from typing import Any

from loguru import logger

from .paths import log_dir, log_file

# Feldnamen, die nie in einem Log-Record landen dürfen – deckungsgleich mit dem
# Backend (``sprichblitz_backend.logging_setup._FORBIDDEN_KEYS``). Deckt Audio-,
# Transkript- und Secret-Material ab.
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
        "body",
        "detail",
        "key",
        "api_key",
        "provider_key",
        "token",
        "secret",
    }
)


def _redact(record: dict[str, Any]) -> None:
    """Loguru-Patcher: ersetzt verbotene Keys in ``extra`` durch ``<redacted>``."""
    extra = record.get("extra")
    if not isinstance(extra, dict):
        return
    for key in list(extra.keys()):
        if key in _FORBIDDEN_KEYS:
            extra[key] = "<redacted>"


def configure_logging(level: str = "INFO") -> None:
    effective_level = os.environ.get("SPRICHBLITZ_LOG_LEVEL", level).upper()
    logger.remove()
    logger.configure(patcher=_redact)
    # Unter PyInstallers runw.exe (windowed, ohne Konsole) sind sys.stderr und
    # sys.stdout None. File-Handler unten ist der wichtige Pfad in Production.
    if sys.stderr is not None:
        logger.add(
            sys.stderr,
            level=effective_level,
            backtrace=False,
            diagnose=False,
        )

    target_dir = log_dir()
    target_dir.mkdir(parents=True, exist_ok=True)
    logger.add(
        log_file(),
        level=effective_level,
        rotation="5 MB",
        retention=5,
        encoding="utf-8",
        enqueue=True,
        backtrace=False,
        diagnose=False,
    )
