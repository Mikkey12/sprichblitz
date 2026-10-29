"""Headless-Tests: Modusliste im Einstellungsfenster auffrischen.

Kern: ein Modus, der nach dem Client-Start in der Konsole angelegt wird, muss
beim nächsten Öffnen der Einstellungen erscheinen – ohne Client-Neustart.
Kein Tk: ``_rebuild_modes_tab`` wird ohne gebauten Tab aufgerufen (No-Op), die
Widget-Arbeit selbst deckt der manuelle Abnahmetest auf Windows ab.
"""

from __future__ import annotations

import pytest

from sprichblitz_client.app import ClientApp
from sprichblitz_client.config import ClientConfig
from sprichblitz_client.hotkeys.base import parse_hotkey
from sprichblitz_client.models import Mode, ModeStatus
from sprichblitz_client.ui.settings_window import SettingsWindow
from sprichblitz_client.ui.tabs.modes_tab import ModesTab, _combo_from_keysym


class _FakeWin:
    """Ersatz für das Tk-Root: sammelt ``after``-Callbacks statt sie zu planen."""

    def __init__(self) -> None:
        self.scheduled: list = []

    def after(self, _delay: int, callback) -> None:  # noqa: ANN001
        self.scheduled.append(callback)

    def run_scheduled(self) -> None:
        while self.scheduled:
            self.scheduled.pop(0)()


class _FakeVar:
    def __init__(self, value: str) -> None:
        self._value = value

    def get(self) -> str:
        return self._value


def _window(modes=None) -> SettingsWindow:
    return SettingsWindow(ClientConfig(backend_url="https://sprichblitz.test"), modes=modes)


def _status(name: str) -> ModeStatus:
    return ModeStatus(enabled=True, display_name=name)


def test_set_modes_ignores_unchanged_list() -> None:
    modes = {Mode.exact_de: _status("Deutsch")}
    win = _window(modes)
    win._win = _FakeWin()

    win.set_modes(dict(modes))

    assert win._win.scheduled == []  # kein Rebuild ohne Änderung


def test_set_modes_schedules_rebuild_when_mode_appears() -> None:
    before = {Mode.exact_de: _status("Deutsch")}
    after = {**before, Mode("prompting"): _status("Prompting")}
    win = _window(before)
    win._win = _FakeWin()

    win.set_modes(after)

    assert Mode("prompting") in win._modes
    assert len(win._win.scheduled) == 1
    win._win.run_scheduled()  # ohne gebauten Tab ein No-Op, darf nicht werfen


def test_set_modes_before_window_is_built_just_stores() -> None:
    win = _window({})

    win.set_modes({Mode("prompting"): _status("Prompting")})

    assert Mode("prompting") in win._modes  # Tab nutzt die Liste beim Bau
    assert win._win is None


def test_hotkey_values_returns_pending_edits() -> None:
    tab = ModesTab.__new__(ModesTab)
    tab._hotkey_vars = {  # type: ignore[attr-defined]
        Mode.exact_de: _FakeVar("ctrl+shift+f1"),
        Mode("prompting"): _FakeVar("ctrl+shift+f6"),
    }

    assert tab.hotkey_values() == {
        Mode.exact_de: "ctrl+shift+f1",
        Mode("prompting"): "ctrl+shift+f6",
    }


def test_push_modes_hands_fresh_list_to_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    app = ClientApp()
    app._cfg = ClientConfig(backend_url="https://sprichblitz.test")
    app._token = "tok"
    fresh = {Mode("prompting"): _status("Prompting")}
    monkeypatch.setattr(app, "_refresh_modes", lambda: setattr(app, "_modes", fresh))

    pushed: list[dict] = []

    class _Window:
        def set_modes(self, modes) -> None:  # noqa: ANN001
            pushed.append(dict(modes))

    app._settings_window = _Window()  # type: ignore[assignment]
    app._push_modes_into_settings()

    assert pushed == [fresh]


def test_push_modes_without_settings_window_is_noop(monkeypatch: pytest.MonkeyPatch) -> None:
    app = ClientApp()
    app._cfg = ClientConfig(backend_url="https://sprichblitz.test")
    app._token = "tok"
    called: list[int] = []
    monkeypatch.setattr(app, "_refresh_modes", lambda: called.append(1))

    app._refresh_modes_into_settings()  # kein Fenster → kein Thread, kein Call

    assert called == []


# --- Win-Taste als Modifier bei der Hotkey-Aufnahme ------------------------- #


def test_win_key_alone_keeps_waiting() -> None:
    # Tk meldet die Win-Taste als Win_L/Win_R – sie darf nicht als Haupt-Taste
    # im String landen (sonst "win+win_l" → nicht parsebar).
    assert _combo_from_keysym("Win_L", 0x40000) is None
    assert _combo_from_keysym("Win_R", 0x40000) is None


def test_win_plus_f6_records_valid_hotkey() -> None:
    combo = _combo_from_keysym("F6", 0x40000)
    assert combo == "win+f6"
    parse_hotkey(combo)  # darf nicht werfen


def test_win_shift_f6_order_and_parse() -> None:
    combo = _combo_from_keysym("F6", 0x40000 | 0x0001)
    assert combo == "shift+win+f6"
    assert parse_hotkey(combo).modifiers & 0x0008  # MOD_WIN gesetzt


def test_plain_key_without_modifier() -> None:
    assert _combo_from_keysym("F7", 0) == "f7"
