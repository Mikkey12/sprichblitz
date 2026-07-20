"""Unit-Tests: uvicorn-stdlib-Logs laufen durch den Loguru-Intercept
(schließt die log_config=None-Observability-Lücke)."""

from __future__ import annotations

import logging

from loguru import logger

from sprichblitz_backend.logging_setup import _InterceptHandler, configure_logging


def test_uvicorn_error_logger_wired_to_intercept() -> None:
    configure_logging()
    lg = logging.getLogger("uvicorn.error")
    assert any(isinstance(h, _InterceptHandler) for h in lg.handlers)
    assert lg.propagate is False
    assert lg.level == logging.INFO  # sonst würden INFO-Startup-Zeilen verworfen


def test_uvicorn_info_record_reaches_loguru() -> None:
    configure_logging()
    captured: list[str] = []
    sink_id = logger.add(lambda m: captured.append(m.record["message"]), level="INFO")
    try:
        logging.getLogger("uvicorn.error").info("uvicorn-running-marker")
    finally:
        logger.remove(sink_id)
    assert any("uvicorn-running-marker" in m for m in captured)


def test_intercept_attribution_uses_stdlib_logger_name() -> None:
    # Nach dem Depth-Walk-Fix + record.name-Übernahme zeigt die Quelle den echten
    # Logger (uvicorn.error), nicht das logging-Interne (logging:callHandlers).
    configure_logging()
    captured: list[tuple[str, str]] = []
    sink_id = logger.add(
        lambda m: captured.append((m.record["name"], m.record["message"])), level="INFO"
    )
    try:
        logging.getLogger("uvicorn.error").info("attribution-check")
    finally:
        logger.remove(sink_id)
    names = [name for name, msg in captured if msg == "attribution-check"]
    assert names == ["uvicorn.error"]
