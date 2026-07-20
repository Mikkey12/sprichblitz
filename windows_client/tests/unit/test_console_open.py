"""Headless-Tests: ClientApp._open_console – Subprozess-Spawn (URL, KEIN Bearer),
Single-Instance. Kein echtes pywebview/Subprozess (alles gemockt)."""

from __future__ import annotations

import json
import threading

import pytest

from sprichblitz_client import app as app_module
from sprichblitz_client.app import ClientApp
from sprichblitz_client.config import ClientConfig


class _FakeStdin:
    def __init__(self) -> None:
        self.data: list[str] = []

    def write(self, s: str) -> None:
        self.data.append(s)

    def flush(self) -> None:
        pass

    def close(self) -> None:
        pass


class _FakePopen:
    def __init__(self, argv) -> None:
        self.argv = argv
        self.stdin = _FakeStdin()
        self._done = threading.Event()

    def poll(self):
        return 0 if self._done.is_set() else None

    def wait(self, timeout=None):
        self._done.wait(timeout)
        return 0

    def terminate(self) -> None:
        self._done.set()

    def finish(self) -> None:  # Test-Helper: Reaper-Thread entsperren
        self._done.set()


class _FakeBackendClient:
    last_boot_nonce: str | None = None

    def __init__(self, url, token, **kw) -> None:
        self.url = url
        self.token = token

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def create_console_session(self, *, boot_nonce: str | None = None) -> str:
        type(self).last_boot_nonce = boot_nonce
        return "TESTCODE"


def _app() -> ClientApp:
    app = ClientApp()
    app._cfg = ClientConfig(backend_url="https://sprichblitz.test")
    app._token = "secret-bearer"
    return app


def test_open_console_spawns_webview_with_url_not_bearer(monkeypatch: pytest.MonkeyPatch) -> None:
    spawned: list[_FakePopen] = []

    def fake_popen(argv, **kw):
        p = _FakePopen(argv)
        spawned.append(p)
        return p

    monkeypatch.setattr(app_module, "BackendClient", _FakeBackendClient)
    monkeypatch.setattr(app_module.subprocess, "Popen", fake_popen)

    app = _app()
    app._open_console()

    assert len(spawned) == 1
    proc = spawned[0]
    assert "--console-webview" in proc.argv
    written = "".join(proc.stdin.data)
    payload = json.loads(written)
    assert payload["url"] == "https://sprichblitz.test/console/bootstrap?code=TESTCODE"
    assert payload["nonce"] == _FakeBackendClient.last_boot_nonce
    assert len(payload["nonce"]) >= 32
    assert set(payload) == {"url", "nonce"}
    # Bearer NIE an den Child – weder in argv noch über stdin.
    assert "secret-bearer" not in " ".join(proc.argv)
    assert "secret-bearer" not in written
    proc.finish()


def test_open_console_single_instance(monkeypatch: pytest.MonkeyPatch) -> None:
    spawned: list[_FakePopen] = []

    def fake_popen(argv, **kw):
        p = _FakePopen(argv)
        spawned.append(p)
        return p

    monkeypatch.setattr(app_module, "BackendClient", _FakeBackendClient)
    monkeypatch.setattr(app_module.subprocess, "Popen", fake_popen)

    app = _app()
    app._open_console()  # spawnt #1 (bleibt "alive")
    app._open_console()  # zweiter Klick → KEIN zweiter Spawn
    assert len(spawned) == 1
    spawned[0].finish()
