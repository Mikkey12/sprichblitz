"""Headless-Tests: Konsolen-Webview – stdin-Parsing + Härtung (kein pywebview nötig)."""

from __future__ import annotations

import io
import json
import sys
import types

import pytest

from sprichblitz_client.ui import console_webview


def _fake_webview(calls: list) -> types.ModuleType:
    mod = types.ModuleType("webview")
    mod.create_window = lambda *a, **k: calls.append(("create_window", a, k))  # type: ignore[attr-defined]
    mod.start = lambda *a, **k: calls.append(("start", a, k))  # type: ignore[attr-defined]
    return mod


def test_run_from_stdin_opens_url(monkeypatch: pytest.MonkeyPatch) -> None:
    url = "https://sprichblitz.test/console/bootstrap?code=ABC"
    payload = {"url": url, "nonce": "client-nonce"}
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload) + "\n"))
    calls: list = []
    monkeypatch.setitem(sys.modules, "webview", _fake_webview(calls))
    assert console_webview.run_from_stdin() == 0
    assert ("create_window", (console_webview._WINDOW_TITLE, "about:blank"), {}) in calls
    start = next(c for c in calls if c[0] == "start")
    assert start[1][0] is console_webview._prepare_window_when_ready
    assert start[2]["gui"] == "edgechromium"


def test_run_from_stdin_empty_is_clean_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "stdin", io.StringIO(""))  # leeres stdin
    monkeypatch.setitem(sys.modules, "webview", None)  # darf nicht erreicht werden
    assert console_webview.run_from_stdin() == 2


def test_run_from_stdin_non_https_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = {"url": "http://evil.test/console/bootstrap?code=x", "nonce": "n"}
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload) + "\n"))
    monkeypatch.setitem(sys.modules, "webview", None)
    assert console_webview.run_from_stdin() == 2


@pytest.mark.parametrize(
    "url",
    [
        "https://evil.test/not-bootstrap?code=x",
        "https://user:password@evil.test/console/bootstrap?code=x",
        "//evil.test/console/bootstrap?code=x",
    ],
)
def test_console_launch_rejects_unsafe_urls(url: str) -> None:
    with pytest.raises(ValueError):
        console_webview.ConsoleLaunch.parse(json.dumps({"url": url, "nonce": "n"}))


class _Cookie:
    IsSecure = False
    IsHttpOnly = True


class _CookieManager:
    def __init__(self) -> None:
        self.created: tuple[str, str, str, str] | None = None
        self.added: _Cookie | None = None
        self.deleted_all = False

    def CreateCookie(self, name: str, value: str, domain: str, path: str) -> _Cookie:
        self.created = (name, value, domain, path)
        return _Cookie()

    def AddOrUpdateCookie(self, cookie: _Cookie) -> None:
        self.added = cookie

    def DeleteAllCookies(self) -> None:
        self.deleted_all = True


class _Event:
    def __init__(self) -> None:
        self.handlers: list = []

    def __iadd__(self, handler):
        self.handlers.append(handler)
        return self


class _Core:
    def __init__(self) -> None:
        self.CookieManager = _CookieManager()
        self.navigated: str | None = None

    def Navigate(self, url: str) -> None:
        self.navigated = url


class _Window:
    def __init__(self) -> None:
        self.native = types.SimpleNamespace(webview=types.SimpleNamespace(CoreWebView2=_Core()))
        self.events = types.SimpleNamespace(closing=_Event())
        self.destroyed = False

    def destroy(self) -> None:
        self.destroyed = True


def test_prepare_window_sets_nonce_cookie_before_navigation() -> None:
    launch = console_webview.ConsoleLaunch(
        url="https://sprichblitz.test/console/bootstrap?code=x",
        nonce="browser-nonce",
    )
    window = _Window()

    console_webview._prepare_window(window, launch)

    manager = window.native.webview.CoreWebView2.CookieManager
    assert manager.created == ("sb_boot", "browser-nonce", "sprichblitz.test", "/console")
    assert manager.added is not None
    assert manager.added.IsSecure is True
    assert manager.added.IsHttpOnly is False
    assert manager.deleted_all is False
    assert window.native.webview.CoreWebView2.navigated == launch.url
    assert window.destroyed is False
    assert len(window.events.closing.handlers) == 1
    window.events.closing.handlers[0]()
    assert manager.deleted_all is True


def test_prepare_dispatches_native_work_to_winforms_ui_thread(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    core = _Core()

    class _Control:
        CoreWebView2 = core

        def __init__(self) -> None:
            self.invoked = False

        def Invoke(self, action) -> None:  # noqa: ANN001, N802
            self.invoked = True
            action()

    control = _Control()
    window = types.SimpleNamespace(
        native=types.SimpleNamespace(webview=control),
        events=types.SimpleNamespace(closing=_Event()),
        destroy=lambda: None,
    )
    launch = console_webview.ConsoleLaunch(
        url="https://sprichblitz.test/console/bootstrap?code=x",
        nonce="browser-nonce",
    )
    monkeypatch.setitem(
        sys.modules,
        "System",
        types.SimpleNamespace(Action=lambda callback: callback),
    )

    console_webview._prepare_window(window, launch)

    assert control.invoked is True
    assert core.navigated == launch.url


def test_prepare_waits_until_native_webview_is_ready(monkeypatch: pytest.MonkeyPatch) -> None:
    core = object()
    window = types.SimpleNamespace(
        native=types.SimpleNamespace(
            webview=types.SimpleNamespace(CoreWebView2=core),
        )
    )
    launch = console_webview.ConsoleLaunch(
        url="https://sprichblitz.test/console/bootstrap?code=x",
        nonce="browser-nonce",
    )
    calls: list[tuple[object, object]] = []
    monkeypatch.setattr(
        console_webview,
        "_prepare_window",
        lambda prepared_window, prepared_launch: calls.append((prepared_window, prepared_launch)),
    )

    console_webview._prepare_window_when_ready(window, launch)

    assert calls == [(window, launch)]


def test_prepare_closes_window_after_ready_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    destroyed: list[bool] = []
    window = types.SimpleNamespace(
        native=None,
        destroy=lambda: destroyed.append(True),
    )
    launch = console_webview.ConsoleLaunch(
        url="https://sprichblitz.test/console/bootstrap?code=x",
        nonce="browser-nonce",
    )
    prepared: list[bool] = []
    monkeypatch.setattr(
        console_webview,
        "_prepare_window",
        lambda *_args: prepared.append(True),
    )
    monotonic_values = iter([0.0, console_webview._WEBVIEW_READY_TIMEOUT_S + 1.0])
    monkeypatch.setattr(
        console_webview.time,
        "monotonic",
        lambda: next(monotonic_values),
    )

    console_webview._prepare_window_when_ready(window, launch)

    assert destroyed == [True]
    assert prepared == []
