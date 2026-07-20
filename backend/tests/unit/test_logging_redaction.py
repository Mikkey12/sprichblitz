"""Redaction-Filter: verbotene extra-Keys werden ersetzt, nie durchgereicht.

Review-Finding zum Security-Review 2026-07: die P1-2-DEBUG-Logs binden
Upstream-Fehlerdetails als ``body``/``detail`` – beide müssen im
Redaction-Backstop stehen, sonst hebelt SPRICHBLITZ_LOG_LEVEL=DEBUG plus ein
extras-rendernder Sink die „keine Transkripte in Logs"-Invariante aus.
"""

from __future__ import annotations

from sprichblitz_backend.logging_setup import _FORBIDDEN_KEYS, _redact


def _record_with_extra(**extra) -> dict:
    return {"extra": dict(extra)}


def test_redacts_provider_error_detail_keys() -> None:
    # Die von den P1-2-DEBUG-Logs verwendeten Feldnamen.
    rec = _record_with_extra(body="echoed transcript", detail="echoed transcript")
    _redact(rec)
    assert rec["extra"]["body"] == "<redacted>"
    assert rec["extra"]["detail"] == "<redacted>"


def test_redacts_classic_content_and_secret_keys() -> None:
    rec = _record_with_extra(text="diktat", transcript="diktat", api_key="sk-x")
    _redact(rec)
    assert all(rec["extra"][k] == "<redacted>" for k in ("text", "transcript", "api_key"))


def test_metadata_keys_pass_through() -> None:
    rec = _record_with_extra(provider="openai", status=400, context="chat_completion")
    _redact(rec)
    assert rec["extra"] == {"provider": "openai", "status": 400, "context": "chat_completion"}


def test_debug_log_field_names_are_covered() -> None:
    # Guard: die in providers/ verwendeten DEBUG-Feldnamen bleiben in der Liste.
    assert {"body", "detail"} <= _FORBIDDEN_KEYS
