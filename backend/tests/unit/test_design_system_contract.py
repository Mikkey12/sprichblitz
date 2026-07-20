"""Der Design-System-Vertrag gegen seine Konsumenten.

``docs/design_system.md`` ist der Vertrag, ``console_static/style.css`` die
Referenzimplementierung. Beide leben im Backend – und wer ein Token aendert,
faehrt **diese** Suite. Deshalb prueft sie auch die nativen Clients: sonst faellt
ein Drift erst auf, wenn Monate spaeter zufaellig jemand die Client-Suite laeuft,
und bis dahin sieht die App-Familie aus wie drei Produkte.

Der Windows-Client hat mit ``windows_client/tests/unit/test_palette.py`` einen
eigenen Check – die Doppelung ist Absicht: der faengt den Drift beim Client-Agenten,
dieser hier beim Backend-Agenten, also bei dem, der die Werte tatsaechlich aendert.
Fuer Android gibt es gar keinen (Kotlin-Tests brauchen Gradle) – hier ist es der
einzige Schutz.

Abgedeckt sind die FARBEN: ihre Werte sind literal und damit maschinell
vergleichbar. Abstaende/Radien/Typo pruefen die Tests bewusst nicht – dort weichen
die Namen plattformbedingt ab (``--sb-space-1`` vs. ``Space1``), und ein
Namens-Mapping zu erfinden waere mehr Attrappe als Schutz. Die stehen im Vertrag
und im Review.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

import sprichblitz_backend

_REPO_ROOT = Path(sprichblitz_backend.__file__).parents[3]
_DOC = _REPO_ROOT / "docs" / "design_system.md"
_WINDOWS_PALETTE = (
    _REPO_ROOT / "windows_client" / "src" / "sprichblitz_client" / "ui" / "palette.py"
)
_ANDROID_THEME = (
    _REPO_ROOT
    / "android_client"
    / "app"
    / "src"
    / "main"
    / "java"
    / "io"
    / "github"
    / "mikkey12"
    / "sprichblitz"
    / "ui"
    / "theme"
    / "Theme.kt"
)


def _contract_colours() -> dict[str, tuple[str, str]]:
    """Die Farbtabelle aus dem Vertrag: ``token -> (hell, dunkel)``."""
    rows = re.findall(
        r"\|\s*`(--sb-[a-z-]+)`\s*\|\s*`(#[0-9a-fA-F]{6})`\s*\|\s*`(#[0-9a-fA-F]{6})`\s*\|",
        _DOC.read_text(),
    )
    return {token: (light.lower(), dark.lower()) for token, light, dark in rows}


def _read_or_skip(path: Path, what: str) -> str:
    """Fehlt der Client, wird uebersprungen statt rot.

    Das Backend muss allein testbar bleiben: der Docker-Build kopiert nur
    ``backend/``, und der geplante Public-Split trennt die Clients ohnehin ab.
    Ein Fehlschlag waere dort eine Luege ueber den Vertrag.
    """
    if not path.exists():
        pytest.skip(
            f"{what} nicht vorhanden ({path.relative_to(_REPO_ROOT)}) – Backend-only-Checkout"
        )
    return path.read_text().lower()


def test_contract_table_is_parseable() -> None:
    """Erst der Selbsttest: eine kaputte Tabelle wuerde alle Checks still gruen faerben.

    Ohne das hier waere ``_contract_colours() == {}`` – und jede Schleife darunter
    liefe ueber nichts und meldete Erfolg.
    """
    colours = _contract_colours()
    assert len(colours) >= 10, f"Farbtabelle im Vertrag nicht gefunden/unvollstaendig: {colours}"
    assert "--sb-accent" in colours


def test_windows_palette_matches_contract() -> None:
    palette = _read_or_skip(_WINDOWS_PALETTE, "Windows-Palette")
    missing = [
        f"{token} ({mode}) {value}"
        for token, values in _contract_colours().items()
        for value, mode in zip(values, ("hell", "dunkel"), strict=True)
        if value not in palette
    ]
    assert missing == [], f"Windows-Palette weicht vom Vertrag ab: {missing}"


def test_android_theme_matches_contract() -> None:
    theme = _read_or_skip(_ANDROID_THEME, "Android-Theme")
    missing = [
        f"{token} ({mode}) {value}"
        # Compose schreibt Farben als 0xFFRRGGBB.
        for token, values in _contract_colours().items()
        for value, mode in zip(values, ("hell", "dunkel"), strict=True)
        if value.replace("#", "0xff") not in theme
    ]
    assert missing == [], f"Android-Theme weicht vom Vertrag ab: {missing}"


def test_android_uses_the_stricter_touch_target() -> None:
    # Der Vertrag nennt 44px als Untergrenze; Materials Minimum ist 48dp und
    # gewinnt als die strengere Regel (so steht es auch im Dokument).
    theme = _read_or_skip(_ANDROID_THEME, "Android-Theme")
    assert "48.dp" in theme


def test_android_does_not_let_material_you_override_the_brand() -> None:
    """``dynamicColor`` wuerde den Akzent durch die Wallpaper-Palette ersetzen.

    Damit waere das Design-System auf Android wirkungslos – die eine Regel, die
    man hier wirklich kaputtmachen kann. In Kommentaren ist das Wort erlaubt
    (dort steht die Begruendung), im Code nicht.
    """
    theme = _read_or_skip(_ANDROID_THEME, "Android-Theme")
    code = "\n".join(
        line for line in theme.splitlines() if not line.strip().startswith(("*", "//", "/*"))
    )
    assert "dynamiccolor" not in code
