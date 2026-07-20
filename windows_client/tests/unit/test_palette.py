"""Drift-Guard: die Windows-Palette muss docs/design_system.md entsprechen.

Der Vertrag lebt in ``docs/design_system.md`` (gespiegelt aus dem ``:root``-Block
von ``console_static/style.css``). Dieses Modul tippt die Werte ab – also prüft
dieser Test, dass sie nicht auseinanderlaufen. Ändert der Backend-Agent ein
Token, schlägt hier etwas an, statt dass der Client still falsch aussieht.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from sprichblitz_client.ui import palette

_DOC = Path(__file__).resolve().parents[3] / "docs" / "design_system.md"

# Doku-Token -> Palette-Konstante
_COLOR_TOKENS = {
    "--sb-accent": "ACCENT",
    "--sb-on-accent": "ON_ACCENT",
    "--sb-accent-subtle": "ACCENT_SUBTLE",
    "--sb-danger": "DANGER",
    "--sb-success": "SUCCESS",
    "--sb-bg": "BG",
    "--sb-surface": "SURFACE",
    "--sb-border": "BORDER",
    "--sb-border-strong": "BORDER_STRONG",
    "--sb-text": "TEXT",
    "--sb-text-muted": "TEXT_MUTED",
}

_SIZE_TOKENS = {
    "--sb-space-1": "SPACE_1",
    "--sb-space-2": "SPACE_2",
    "--sb-space-3": "SPACE_3",
    "--sb-space-4": "SPACE_4",
    "--sb-space-5": "SPACE_5",
    "--sb-space-6": "SPACE_6",
    "--sb-radius": "RADIUS",
    "--sb-radius-card": "RADIUS_CARD",
    "--sb-tap": "TAP",
}


def _doc_rows() -> dict[str, list[str]]:
    """Markdown-Tabellen: `| `--sb-x` | a | b | Zweck |` -> {token: [a, b, ...]}."""
    rows: dict[str, list[str]] = {}
    for line in _DOC.read_text(encoding="utf-8").splitlines():
        m = re.match(r"\|\s*`(--sb-[a-z0-9-]+)`\s*\|(.+)\|\s*$", line.strip())
        if not m:
            continue
        cells = [c.strip().strip("`").strip() for c in m.group(2).split("|")]
        rows[m.group(1)] = cells
    return rows


@pytest.fixture(scope="module")
def doc_rows() -> dict[str, list[str]]:
    assert _DOC.is_file(), f"Vertrag nicht gefunden: {_DOC}"
    return _doc_rows()


def test_doc_is_parsable(doc_rows: dict[str, list[str]]) -> None:
    """Schützt die anderen Tests: ändert sich das Tabellenformat, fällt es hier auf."""
    missing = (set(_COLOR_TOKENS) | set(_SIZE_TOKENS)) - set(doc_rows)
    assert not missing, f"Tokens nicht in der Doku-Tabelle gefunden: {sorted(missing)}"


@pytest.mark.parametrize("token,const", sorted(_COLOR_TOKENS.items()))
def test_colour_matches_contract(
    token: str, const: str, doc_rows: dict[str, list[str]]
) -> None:
    light, dark = doc_rows[token][0].lower(), doc_rows[token][1].lower()
    assert getattr(palette, const) == (light, dark), (
        f"{const} weicht von {token} in docs/design_system.md ab – "
        f"NICHT hier anpassen, sondern melden (der Backend-Agent pflegt den Vertrag)."
    )


@pytest.mark.parametrize("token,const", sorted(_SIZE_TOKENS.items()))
def test_size_matches_contract(
    token: str, const: str, doc_rows: dict[str, list[str]]
) -> None:
    px = int(re.sub(r"[^0-9]", "", doc_rows[token][0]))
    assert getattr(palette, const) == px, f"{const} weicht von {token} ab"


def test_exactly_one_accent_role() -> None:
    """Nur die primäre Aktion trägt die Akzentfläche; sekundär/destruktiv nicht."""
    assert palette.primary_button()["fg_color"] == palette.ACCENT
    assert palette.secondary_button()["fg_color"] == "transparent"
    assert palette.danger_button()["fg_color"] == "transparent"


def test_danger_is_only_destructive() -> None:
    """Rot erscheint ausschliesslich im destruktiven Button, nie als Akzent."""
    assert palette.danger_button()["text_color"] == palette.DANGER
    for role in (palette.primary_button(), palette.secondary_button()):
        assert palette.DANGER not in role.values()


def test_tap_target_not_below_contract() -> None:
    for role in (palette.primary_button(), palette.secondary_button(), palette.danger_button()):
        assert role["height"] >= palette.TAP
