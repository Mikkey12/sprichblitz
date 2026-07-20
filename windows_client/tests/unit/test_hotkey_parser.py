from __future__ import annotations

import pytest

from sprichblitz_client.hotkeys.base import (
    MOD_ALT,
    MOD_CONTROL,
    MOD_SHIFT,
    HotkeyCombo,
    InvalidHotkeyError,
    altgr_risk,
    parse_hotkey,
)


def test_parse_simple_ctrl_alt_digit() -> None:
    combo = parse_hotkey("ctrl+alt+1")
    assert isinstance(combo, HotkeyCombo)
    assert combo.modifiers == (MOD_CONTROL | MOD_ALT)
    assert combo.vk == ord("1")
    assert combo.raw == "ctrl+alt+1"


def test_parse_letter_with_shift() -> None:
    combo = parse_hotkey("ctrl+shift+d")
    assert combo.modifiers == (MOD_CONTROL | MOD_SHIFT)
    assert combo.vk == ord("D")


def test_parse_named_key_f5() -> None:
    combo = parse_hotkey("alt+f5")
    assert combo.modifiers == MOD_ALT
    assert combo.vk == 0x74  # VK_F5


@pytest.mark.parametrize("bad", ["", "+", "ctrl+", "ctrl+alt+1+2", "ctrl+frobnicate"])
def test_parse_invalid_strings(bad: str) -> None:
    with pytest.raises(InvalidHotkeyError):
        parse_hotkey(bad)


@pytest.mark.parametrize("risky", ["ctrl+alt+1", "ctrl+alt+2", "ctrl+alt+q", "alt+ctrl+0"])
def test_altgr_risk_flags_ctrl_alt_printable(risky: str) -> None:
    # Ctrl+Alt+<druckbar> = AltGr+<Taste> auf CH/EU-Layout (AltGr+2 = "@").
    assert altgr_risk(risky) is True


@pytest.mark.parametrize(
    "safe",
    ["ctrl+shift+f1", "ctrl+shift+f5", "alt+f5", "ctrl+shift+d", "ctrl+alt+space", ""],
)
def test_altgr_risk_allows_safe_combos(safe: str) -> None:
    # F-Tasten/benannte Tasten haben kein AltGr-Mapping; leerer String → kein Risiko.
    assert altgr_risk(safe) is False
