"""Entry-Point-spezifische Sicherheitsregressionen."""

from __future__ import annotations

import sys

from sprichblitz_client import __main__ as entrypoint
from sprichblitz_client import logging_setup
from sprichblitz_client.ui import console_webview


def test_console_child_configures_hardened_logging(monkeypatch) -> None:  # noqa: ANN001
    calls: list[str] = []
    monkeypatch.setattr(sys, "argv", ["Sprichblitz.exe", "--console-webview"])
    monkeypatch.setattr(logging_setup, "configure_logging", lambda: calls.append("logging"))
    monkeypatch.setattr(console_webview, "run_from_stdin", lambda: 7)

    assert entrypoint.main() == 7
    assert calls == ["logging"]
