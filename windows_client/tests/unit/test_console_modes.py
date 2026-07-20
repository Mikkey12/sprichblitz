"""Headless-Tests: location-aware Diktat – Hotkey-Gate (disabled feuert nicht,
unknown/leer fail-open) + _refresh_modes (atomarer Swap, fail-open hält letzten Stand)."""

from __future__ import annotations

import pytest

from sprichblitz_client import app as app_module
from sprichblitz_client.app import ClientApp
from sprichblitz_client.config import ClientConfig
from sprichblitz_client.models import MeInfo, Mode, ModeStatus
from sprichblitz_client.ui.tabs.modes_tab import _mode_label, _ordered_modes


def _app() -> ClientApp:
    app = ClientApp()
    app._cfg = ClientConfig(backend_url="https://sprichblitz.test")
    app._token = "tok"
    app._state = "idle"
    return app


def test_disabled_mode_does_not_fire(monkeypatch: pytest.MonkeyPatch) -> None:
    app = _app()
    app._modes = {Mode.rage: ModeStatus(enabled=False, display_name="Cool")}
    started: list = []
    notified: list = []
    monkeypatch.setattr(app, "_start_recording", lambda m: started.append(m))
    monkeypatch.setattr(app_module, "notify", lambda *a, **k: notified.append(a))
    app._on_hotkey(Mode.rage)
    assert started == []  # deaktiviert → kein Diktat
    assert len(notified) == 1  # aber Feedback-Toast


def test_enabled_mode_fires(monkeypatch: pytest.MonkeyPatch) -> None:
    app = _app()
    app._modes = {Mode.exact_de: ModeStatus(enabled=True, display_name="Deutsch")}
    started: list = []
    monkeypatch.setattr(app, "_start_recording", lambda m: started.append(m))
    app._on_hotkey(Mode.exact_de)
    assert started == [Mode.exact_de]


def test_unknown_mode_fails_open(monkeypatch: pytest.MonkeyPatch) -> None:
    app = _app()
    app._modes = {}  # nichts geladen (Startup/Backend-Hickup) → alle feuern
    started: list = []
    monkeypatch.setattr(app, "_start_recording", lambda m: started.append(m))
    app._on_hotkey(Mode.exact_swiss)
    assert started == [Mode.exact_swiss]


def test_dynamic_mode_uses_backend_display_name_and_starts_without_hotkey() -> None:
    cfg = ClientConfig()
    mundart = Mode("mundart")
    modes = {mundart: ModeStatus(enabled=True, display_name="Mundart")}
    assert mundart in _ordered_modes(cfg, modes)
    assert not any(binding.mode == mundart for binding in cfg.hotkeys)
    assert _mode_label(mundart, modes) == "Mundart"


def test_removed_backend_mode_survives_from_local_config() -> None:
    removed = Mode("retired_mode")
    cfg = ClientConfig.model_validate(
        {"hotkeys": [{"mode": removed.value, "keys": "ctrl+shift+f8"}]}
    )
    assert removed in _ordered_modes(cfg, {})


class _FakeClient:
    def __init__(self, *a, **k) -> None:
        pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_refresh_modes_atomic_swap(monkeypatch: pytest.MonkeyPatch) -> None:
    app = _app()
    new = {Mode.mail: ModeStatus(enabled=False, display_name="Mail")}

    class _C(_FakeClient):
        def get_modes(self):
            return new

    monkeypatch.setattr(app_module, "BackendClient", _C)
    app._refresh_modes()
    assert app._modes is new  # atomarer Referenz-Swap auf das frische dict


def test_refresh_modes_failopen_keeps_last(monkeypatch: pytest.MonkeyPatch) -> None:
    app = _app()
    prev = {Mode.mail: ModeStatus(enabled=False, display_name="Mail")}
    app._modes = prev

    class _C(_FakeClient):
        def get_modes(self):
            raise RuntimeError("backend down")

    monkeypatch.setattr(app_module, "BackendClient", _C)
    app._refresh_modes()
    assert app._modes is prev  # Fehler → letzter Stand bleibt (kein Clear)


class _FakeTray:
    def __init__(self) -> None:
        self.tooltips: list[str] = []

    def set_tooltip(self, t: str) -> None:
        self.tooltips.append(t)


def test_tooltip_includes_location() -> None:
    app = _app()
    app._location = "online"
    assert app._tooltip_for("idle") == "Sprichblitz · online"
    app._location = None
    assert app._tooltip_for("idle") == "Sprichblitz (idle)"  # fail-open: generisch


def test_refresh_location_sets_and_failopen_keeps_last(monkeypatch: pytest.MonkeyPatch) -> None:
    app = _app()

    class _Ok(_FakeClient):
        def get_me(self):
            return MeInfo(name="admin", processing_location="local")

    monkeypatch.setattr(app_module, "BackendClient", _Ok)
    app._refresh_location()
    assert app._location == "local"

    class _Boom(_FakeClient):
        def get_me(self):
            raise RuntimeError("down")

    monkeypatch.setattr(app_module, "BackendClient", _Boom)
    app._refresh_location()
    assert app._location == "local"  # Fehler → letzter Stand bleibt


def test_refresh_idle_tooltip_only_when_idle() -> None:
    app = _app()
    app._location = "online"
    tray = _FakeTray()
    app._tray = tray
    app._state = "idle"
    app._refresh_idle_tooltip()
    assert tray.tooltips == ["Sprichblitz · online"]
    app._state = "recording"
    app._refresh_idle_tooltip()
    assert tray.tooltips == ["Sprichblitz · online"]  # kein Update ausserhalb idle
