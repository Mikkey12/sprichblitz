"""c2: Konsolen-Skelett (StaticFiles unter /app) + strikte CSP + globaler nosniff."""

from __future__ import annotations

import re
from pathlib import Path

from fastapi.testclient import TestClient

import sprichblitz_backend

_EXPECTED_CSP = (
    "default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self'; "
    "connect-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
)


def test_console_index_served(client: TestClient) -> None:
    res = client.get("/app/")
    assert res.status_code == 200
    assert "Sprichblitz" in res.text


def test_console_csp_is_exact(client: TestClient) -> None:
    # Exakter Policy-String → fängt künftiges Lockern, nicht nur "Header vorhanden".
    res = client.get("/app/")
    assert res.headers["content-security-policy"] == _EXPECTED_CSP
    assert res.headers["referrer-policy"] == "no-referrer"
    assert res.headers["x-content-type-options"] == "nosniff"


def test_nosniff_is_global_on_api(client: TestClient) -> None:
    # nosniff auch auf API-Antworten (kein HTML-Sniffing einer JSON-Response).
    assert client.get("/health").headers["x-content-type-options"] == "nosniff"


def test_session_api_not_shadowed_by_static(
    tls_client: TestClient, auth_headers: dict[str, str]
) -> None:
    # /console/session bleibt die API (Static liegt unter /app, kein Overlap).
    # Status 200 = liefert jetzt den Bootstrap-Code (Stage A), nicht beschattet vom /app-Mount.
    assert tls_client.post("/console/session", headers=auth_headers).status_code == 200


def test_skeleton_has_no_inline_script_or_style() -> None:
    html = (
        (Path(sprichblitz_backend.__file__).parent / "console_static" / "index.html")
        .read_text()
        .lower()
    )
    assert "<style" not in html  # inline <style> (style-src 'self' verbietet es)
    assert "style=" not in html  # inline style-Attribute
    assert "<script>" not in html  # inline script (nur <script src=...> erlaubt)


def test_console_index_has_screens(client: TestClient) -> None:
    html = client.get("/app/").text
    for heading in ("Übersicht", "Konto", "Modi", "Einstellungen", "Statistik"):
        assert heading in html


def _css() -> str:
    return (
        Path(sprichblitz_backend.__file__).parent / "console_static" / "style.css"
    ).read_text()


def _root_blocks(css: str) -> list[str]:
    """Die :root-Blöcke (hell + Dark-Mode-Override) – nur dort DÜRFEN Hex-Werte stehen."""
    return [
        css[m.start() : css.index("}", m.start()) + 1] for m in re.finditer(r":root\s*\{", css)
    ]


def test_design_tokens_are_the_only_source_of_color() -> None:
    """Ausserhalb von :root darf keine Farbe hardcodiert sein.

    Sonst driftet die Konsole am Design-System vorbei und docs/design_system.md
    wird zur Lüge – die nativen Clients spiegeln die Tokens, nicht das CSS.
    """
    css = _css()
    outside = css
    for block in _root_blocks(css):
        outside = outside.replace(block, "")
    stray = re.findall(r"#[0-9a-fA-F]{3,8}\b", outside)
    assert stray == [], f"Hardcodierte Farben ausserhalb der Tokens: {stray}"


def test_every_token_has_a_dark_value() -> None:
    """Jedes Farb-Token braucht einen Dark-Mode-Wert – sonst ist ein Modus kaputt."""
    css = _css()
    dark = css[css.index("prefers-color-scheme: dark") :]
    colour_tokens = {
        "--sb-accent",
        "--sb-on-accent",
        "--sb-accent-subtle",
        "--sb-danger",
        "--sb-success",
        "--sb-bg",
        "--sb-surface",
        "--sb-border",
        "--sb-border-strong",
        "--sb-text",
        "--sb-text-muted",
    }
    for token in colour_tokens:
        assert f"{token}:" in css, f"{token} fehlt in :root"
        assert re.search(rf"{re.escape(token)}\s*:", dark), f"{token} fehlt im Dark-Mode-Block"


def test_documented_tokens_match_the_css() -> None:
    """docs/design_system.md ist der Vertrag für die nativen Clients – er muss stimmen.

    Ein Doku-Drift ist hier kein Schönheitsfehler: Android und Windows spiegeln die
    Werte aus dem Dokument, nicht aus dem CSS.
    """
    doc = (Path(sprichblitz_backend.__file__).parents[3] / "docs" / "design_system.md").read_text()
    for block in _root_blocks(_css()):
        for token in re.findall(r"--sb-[a-z0-9-]+", block):
            assert token in doc, f"{token} ist in style.css definiert, aber nicht dokumentiert"


def test_touch_targets_are_finger_sized() -> None:
    # 44px ist die Untergrenze für alles Antippbare – die Konsole läuft auf dem Handy.
    assert "--sb-tap: 44px" in _css()


def test_console_assets_are_revalidated(client: TestClient) -> None:
    """Konsolen-Assets dürfen nicht ohne Rückfrage aus einem Cache kommen.

    Ohne Cache-Control vom Origin cacht Cloudflare .js/.css per Default 4h, während
    das HTML ungecacht durchgeht → index.html und app.js driften auseinander und die
    Konsole ist stillschweigend kaputt. Genau so blieb der Admin-Tab unsichtbar.
    """
    for path in ("/app/", "/app/app.js", "/app/style.css"):
        assert client.get(path).headers["cache-control"] == "no-cache", path


def test_admin_nav_ships_hidden() -> None:
    # Der Verwaltungs-Tab wird erst von init() anhand von /me.admin_scope eingeblendet.
    # Käme er sichtbar aus dem Skelett, sähe ihn jeder Nicht-Admin kurz aufblitzen.
    html = (
        (Path(sprichblitz_backend.__file__).parent / "console_static" / "index.html")
        .read_text()
    )
    nav = next(line for line in html.splitlines() if 'data-nav="admin"' in line)
    assert "hidden" in nav


def test_console_survives_html_js_drift() -> None:
    """Kein direkter Property-Zugriff auf ein Einzelelement-Lookup.

    index.html und app.js koennen auseinanderlaufen (Cache, halber Deploy). Dann
    liefert getElementById/querySelector null und ein direkter Zugriff wirft –
    steht der im Init-Pfad, rendert die Konsole gar nicht mehr, obwohl bloss ein
    Detail fehlt. Genau so ist es im Android-WebView passiert. Also: Ergebnis
    erst pruefen, dann benutzen. (querySelectorAll ist ausgenommen: eine leere
    NodeList ist harmlos.)
    """
    js = (
        Path(sprichblitz_backend.__file__).parent / "console_static" / "app.js"
    ).read_text()
    stray = re.findall(r"(?:getElementById|querySelector)\([^)]*\)\s*\.\w+", js)
    assert stray == [], f"Ungeschuetzter DOM-Zugriff (null-Guard fehlt): {stray}"


def test_console_key_input_masked_and_has_finally_clear() -> None:
    # Smoke-Guards (Details = verbatim-Review): Key-Feld maskiert + Clearing-Pfad da.
    js = (
        (Path(sprichblitz_backend.__file__).parent / "console_static" / "app.js")
        .read_text()
        .lower()
    )
    assert 'type = "password"' in js  # Key-Eingabe maskiert
    assert "finally" in js  # Feld-Clearing auf Erfolg UND Fehler


def test_api_spread_does_not_clobber_console_header() -> None:
    # Regression-Guard für den d3-Review-Bug: `...opts` muss VOR der erzwungenen
    # `headers:`-Zeile stehen, sonst überschreibt der Spread X-Sb-Console (write()→401).
    js = (Path(sprichblitz_backend.__file__).parent / "console_static" / "app.js").read_text()
    assert js.index("...opts,") < js.index('headers: { "X-Sb-Console"')


def test_console_js_no_client_storage_and_sets_security_request_bits() -> None:
    # Statischer Guard: das Konsolen-JS nutzt KEINEN persistenten Client-Storage und
    # setzt no-store + X-Sb-Console. Komplement zum manuellen d3-Key-Review.
    js = (
        (Path(sprichblitz_backend.__file__).parent / "console_static" / "app.js")
        .read_text()
        .lower()
    )
    assert "x-sb-console" in js
    assert "no-store" in js
    for forbidden in ("localstorage", "sessionstorage", "indexeddb"):
        assert forbidden not in js
