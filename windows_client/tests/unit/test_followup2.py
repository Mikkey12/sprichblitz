from __future__ import annotations

import httpx
import respx

from sprichblitz_client.autostart import (
    SHORTCUT_NAME,
    frozen_executable_target,
    shortcut_path,
)
from sprichblitz_client.backend.client import BackendClient
from sprichblitz_client.config import ClientConfig
from sprichblitz_client.locale_detect import klid_to_locale, resolve_effective_locale
from sprichblitz_client.models import Mode
from sprichblitz_client.ui.tabs.behaviour_tab import format_speech_ratio_percent

_FULL_JSON = {
    "mode": "exact_de",
    "raw_text": "x",
    "final_text": "x",
    "stt_provider": "lm_studio_whisper",
    "stt_model": "whisper-large-v3-turbo",
    "used_fallback": False,
    "total_duration_ms": 1,
}


def test_format_speech_ratio_percent() -> None:
    assert format_speech_ratio_percent(0.05) == "5 %"
    assert format_speech_ratio_percent(0.0) == "0 %"
    assert format_speech_ratio_percent(0.30) == "30 %"
    assert format_speech_ratio_percent(0.123) == "12 %"


def test_frozen_executable_target_returns_path_when_frozen() -> None:
    assert frozen_executable_target(r"C:\X\Sprichblitz.exe", True) == r"C:\X\Sprichblitz.exe"


def test_frozen_executable_target_none_when_not_frozen_or_empty() -> None:
    assert frozen_executable_target(r"C:\X\python.exe", False) is None
    assert frozen_executable_target("", True) is None


def test_shortcut_path_uses_startup_folder(monkeypatch) -> None:
    monkeypatch.setenv("APPDATA", r"C:\Users\test\AppData\Roaming")
    sp = shortcut_path()
    assert sp is not None
    assert sp.name == SHORTCUT_NAME
    parts = sp.as_posix()
    assert "Microsoft/Windows/Start Menu/Programs/Startup" in parts


def test_shortcut_path_none_without_appdata(monkeypatch) -> None:
    monkeypatch.delenv("APPDATA", raising=False)
    assert shortcut_path() is None


# --- Locale-Erkennung & -Auflösung ---------------------------------------
def test_klid_to_locale_known() -> None:
    assert klid_to_locale("00000807") == "de-CH"
    assert klid_to_locale("0807") == "de-CH"
    assert klid_to_locale("0407") == "de-DE"
    assert klid_to_locale("100C") == "fr-CH"  # case-insensitive
    assert klid_to_locale("0810") == "it-CH"


def test_klid_to_locale_unknown_returns_none() -> None:
    assert klid_to_locale("ffff") is None
    assert klid_to_locale("") is None


def test_resolve_effective_locale() -> None:
    assert resolve_effective_locale("off") is None
    assert resolve_effective_locale("") is None
    assert resolve_effective_locale("de-CH") == "de-CH"
    assert resolve_effective_locale("de-DE") == "de-DE"
    # "auto" liefert eine erkannte Locale ODER None (kein Crash, kein Throw).
    result = resolve_effective_locale("auto")
    assert result is None or isinstance(result, str)


def test_clientconfig_locale_override_default_is_auto() -> None:
    assert ClientConfig().locale_override == "auto"


@respx.mock
def test_full_sends_locale_field() -> None:
    route = respx.post("https://bt.test/full").mock(
        return_value=httpx.Response(200, json=_FULL_JSON)
    )
    with BackendClient("https://bt.test", "tok") as client:
        client.full(b"RIFF", Mode.exact_de, locale="de-CH")
    body = route.calls.last.request.content
    assert b'name="locale"' in body
    assert b"de-CH" in body


@respx.mock
def test_full_omits_locale_when_not_set() -> None:
    route = respx.post("https://bt.test/full").mock(
        return_value=httpx.Response(200, json=_FULL_JSON)
    )
    with BackendClient("https://bt.test", "tok") as client:
        client.full(b"RIFF", Mode.exact_de)
    assert b'name="locale"' not in route.calls.last.request.content
