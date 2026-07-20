"""Regression guard for the hard invariant „keine Transkripte/Secrets in Logs".

Two layers protect it, both tested here:

1. loguru defaults to ``diagnose=True``, which renders the local variables of a
   traceback frame into the log. On an insertion failure the dictated text is a
   live local (``inserter.insert(result.final_text)``), so without
   ``diagnose=False`` the transcript would land in ``client.log``.
2. The ``_redact`` patcher strips forbidden keys from ``extra`` before a record
   reaches any sink – a backstop against ``logger.info(..., final_text=…)`` or an
   extra-rendering sink.
"""

from __future__ import annotations

import io
import json
from pathlib import Path

from loguru import logger

from sprichblitz_client import logging_setup, paths
from sprichblitz_client.logging_setup import _FORBIDDEN_KEYS, _redact


def test_exception_log_does_not_leak_local_variables(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(paths, "log_dir", lambda: tmp_path)
    monkeypatch.setattr(paths, "log_file", lambda: tmp_path / "client.log")

    logging_setup.configure_logging()

    secret_transcript = "Bitte 5000 Franken an Konto CH99 ueberweisen"

    def insert(text: str) -> None:  # mirrors inserter.insert(result.final_text)
        raise RuntimeError("target window rejected input")

    try:
        final_text = secret_transcript
        insert(final_text)
    except RuntimeError as exc:
        logger.exception("Text-Insertion fehlgeschlagen: {}", exc)

    logger.remove()  # flush the enqueue=True file sink before reading

    log_text = (tmp_path / "client.log").read_text(encoding="utf-8")
    # The transcript (a local variable) must NOT appear …
    assert secret_transcript not in log_text
    # … while the failure itself is still recorded (debuggability preserved).
    assert "Text-Insertion fehlgeschlagen" in log_text
    assert "RuntimeError" in log_text


def test_configure_logging_creates_log_file(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(paths, "log_dir", lambda: tmp_path)
    monkeypatch.setattr(paths, "log_file", lambda: tmp_path / "client.log")

    logging_setup.configure_logging()
    logger.info("smoke")
    logger.remove()

    assert (tmp_path / "client.log").exists()


# --- Redaction-Patcher -------------------------------------------------------


def test_redact_replaces_forbidden_extra_keys() -> None:
    record = {"extra": {"final_text": "diktat", "token": "sk-x", "transcript": "d"}}
    _redact(record)
    assert all(record["extra"][k] == "<redacted>" for k in ("final_text", "token", "transcript"))


def test_redact_passes_metadata_through() -> None:
    record = {"extra": {"provider": "openai", "status": 400, "mode": "mail"}}
    _redact(record)
    assert record["extra"] == {"provider": "openai", "status": 400, "mode": "mail"}


def test_forbidden_keys_cover_transcript_and_secret_fields() -> None:
    assert {"text", "final_text", "raw_text", "transcript", "token", "api_key"} <= _FORBIDDEN_KEYS


def test_bound_secret_is_redacted_end_to_end(monkeypatch, tmp_path: Path) -> None:
    """Der global gesetzte Patcher greift für JEDEN Sink – hier ein serialize-Sink,
    der ``extra`` tatsächlich rendert (der Default-Sink tut es nicht)."""
    monkeypatch.setattr(paths, "log_dir", lambda: tmp_path)
    monkeypatch.setattr(paths, "log_file", lambda: tmp_path / "client.log")

    logging_setup.configure_logging()  # installiert _redact via logger.configure
    buf = io.StringIO()
    logger.add(buf, serialize=True, backtrace=False, diagnose=False)

    logger.bind(final_text="Bitte 5000 Franken ueberweisen", provider="openai").info("done")
    logger.remove()

    payload = json.loads(buf.getvalue().splitlines()[-1])
    extra = payload["record"]["extra"]
    assert extra["final_text"] == "<redacted>"
    assert extra["provider"] == "openai"  # Metadaten bleiben
    assert "Bitte 5000" not in buf.getvalue()
