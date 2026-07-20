"""Globale Modi: Aufloesungskette, Zwei-Klassen-Loeschen, Admin-Routen.

Kette: config.yml (Kanon)  <  ModeDefinition (global, DB)  <  ModeOverride (Nutzer).
Der Default-Testnutzer (conftest) ist Admin und steht auf processing_location=online.
"""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine
from sqlmodel import Session, select

from sprichblitz_backend.db.models import ModeDefinition

_CONSOLE_HDR = {"X-Sb-Console": "1"}


def _put_mode(client: TestClient, headers: dict[str, str], key: str, **body):
    return client.put(f"/admin/modes/{key}", headers=headers, json=body)


# --- Aufloesung: config < global -------------------------------------------


def test_config_mode_unchanged_without_definition(
    tls_client: TestClient, auth_headers: dict[str, str]
) -> None:
    modes = {m["mode_key"]: m for m in tls_client.get("/admin/modes", headers=auth_headers).json()}
    assert modes["exact_de"]["from_config"] is True
    assert modes["exact_de"]["has_global_override"] is False
    assert modes["exact_de"]["enabled"] is True


def test_global_override_beats_config(
    tls_client: TestClient, auth_headers: dict[str, str]
) -> None:
    res = _put_mode(tls_client, auth_headers, "exact_de", description="Global umbenannt")
    assert res.status_code == 200
    assert res.json()["description"] == "Global umbenannt"
    assert res.json()["has_global_override"] is True
    # Und es gilt fuer die Nutzersicht, nicht nur fuer die Verwaltung.
    me = {m["mode_key"]: m for m in tls_client.get("/me/modes", headers=auth_headers).json()}
    assert me["exact_de"]["display_name"] == "Global umbenannt"


def test_unset_field_keeps_config_value(
    tls_client: TestClient, auth_headers: dict[str, str]
) -> None:
    # None heisst "Config-Wert gilt" – ein Teil-Override darf den Rest nicht plattmachen.
    _put_mode(tls_client, auth_headers, "exact_swiss", description="Nur der Name")
    modes = {m["mode_key"]: m for m in tls_client.get("/admin/modes", headers=auth_headers).json()}
    assert modes["exact_swiss"]["description"] == "Nur der Name"
    assert modes["exact_swiss"]["stt"] == "lm_studio_whisper"  # aus config.yml
    assert modes["exact_swiss"]["fallback_stt"] == "openai_whisper"  # aus config.yml


def test_user_override_beats_global(
    tls_client: TestClient, auth_headers: dict[str, str]
) -> None:
    """Die volle Kette: der persoenliche Override gewinnt zuletzt."""
    _put_mode(tls_client, auth_headers, "exact_de", description="Global")
    tls_client.put("/me/modes/exact_de", headers=auth_headers, json={"display_name": "Meiner"})
    me = {m["mode_key"]: m for m in tls_client.get("/me/modes", headers=auth_headers).json()}
    assert me["exact_de"]["display_name"] == "Meiner"


# --- Global deaktivieren = der ehrliche Ersatz fuers Loeschen ----------------


def test_disabled_config_mode_disappears_everywhere(
    tls_client: TestClient, auth_headers: dict[str, str], audio_16k_wav: bytes
) -> None:
    _put_mode(tls_client, auth_headers, "exact_de", enabled=False)

    # /me/modes kennt ihn nicht mehr …
    keys = [m["mode_key"] for m in tls_client.get("/me/modes", headers=auth_headers).json()]
    assert "exact_de" not in keys
    # … /config auch nicht …
    names = [m["name"] for m in tls_client.get("/config", headers=auth_headers).json()["modes"]]
    assert "exact_de" not in names
    # … und Diktieren ist wie bei einem unbekannten Modus 400.
    res = tls_client.post(
        "/full",
        headers=auth_headers,
        files={"file": ("a.wav", audio_16k_wav, "audio/wav")},
        data={"mode": "exact_de"},
    )
    assert res.status_code == 400
    assert res.json()["code"] == "mode_not_configured"


def test_disabled_mode_still_visible_to_admin(
    tls_client: TestClient, auth_headers: dict[str, str]
) -> None:
    # Sonst koennte man ihn nie wieder einschalten.
    _put_mode(tls_client, auth_headers, "exact_de", enabled=False)
    modes = {m["mode_key"]: m for m in tls_client.get("/admin/modes", headers=auth_headers).json()}
    assert modes["exact_de"]["enabled"] is False


def test_reenabling_brings_the_mode_back(
    tls_client: TestClient, auth_headers: dict[str, str]
) -> None:
    _put_mode(tls_client, auth_headers, "exact_de", enabled=False)
    _put_mode(tls_client, auth_headers, "exact_de", enabled=True)
    keys = [m["mode_key"] for m in tls_client.get("/me/modes", headers=auth_headers).json()]
    assert "exact_de" in keys


def test_config_mode_cannot_be_deleted(
    tls_client: TestClient, auth_headers: dict[str, str]
) -> None:
    """Die YAML-Zeilen kann eine API nicht entfernen – „Loeschen" waere gelogen."""
    res = tls_client.delete("/admin/modes/exact_de", headers=auth_headers)
    assert res.status_code == 409
    assert res.json()["code"] == "mode_from_config"


# --- Eigenstaendige DB-Modi -------------------------------------------------


def test_new_db_mode_works_end_to_end(
    tls_client: TestClient, auth_headers: dict[str, str], audio_16k_wav: bytes
) -> None:
    res = _put_mode(
        tls_client,
        auth_headers,
        "notiz",
        description="Kurznotiz",
        stt="openai_whisper",
        apply_llm=False,
    )
    assert res.status_code == 200
    assert res.json()["from_config"] is False

    # Er taucht in der Nutzersicht auf …
    keys = [m["mode_key"] for m in tls_client.get("/me/modes", headers=auth_headers).json()]
    assert "notiz" in keys
    # … und diktiert wirklich – reine DB, keine Zeile in config.yml.
    res = tls_client.post(
        "/full",
        headers=auth_headers,
        files={"file": ("a.wav", audio_16k_wav, "audio/wav")},
        data={"mode": "notiz"},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["mode"] == "notiz"
    assert body["final_text"] == "cloud transcript"
    assert body["stt_provider"] == "openai_whisper"  # der in der DB gewaehlte Provider


def test_db_mode_can_really_be_deleted(
    tls_client: TestClient, auth_headers: dict[str, str], db_engine: Engine
) -> None:
    _put_mode(tls_client, auth_headers, "notiz", description="Kurznotiz", stt="openai_whisper")
    assert tls_client.delete("/admin/modes/notiz", headers=auth_headers).status_code == 204
    keys = [m["mode_key"] for m in tls_client.get("/me/modes", headers=auth_headers).json()]
    assert "notiz" not in keys
    with Session(db_engine) as s:
        assert s.exec(select(ModeDefinition).where(ModeDefinition.mode_key == "notiz")).all() == []


def test_new_mode_needs_description_and_stt(
    tls_client: TestClient, auth_headers: dict[str, str]
) -> None:
    # Ohne die beiden laesst sich keine ModeConfig bauen.
    res = _put_mode(tls_client, auth_headers, "notiz", description="Nur Name")
    assert res.status_code == 422
    assert res.json()["code"] == "incomplete_mode"


def test_new_mode_key_is_validated(
    tls_client: TestClient, auth_headers: dict[str, str]
) -> None:
    res = _put_mode(
        tls_client, auth_headers, "Nicht Erlaubt!", description="x", stt="openai_whisper"
    )
    assert res.status_code == 422
    assert res.json()["code"] == "invalid_mode_key"


def test_unknown_provider_rejected(
    tls_client: TestClient, auth_headers: dict[str, str]
) -> None:
    # Sonst faellt der kaputte Modus erst beim Diktieren auf – mit 500 statt 422.
    res = _put_mode(tls_client, auth_headers, "notiz", description="x", stt="gibts_nicht")
    assert res.status_code == 422
    assert res.json()["code"] == "unknown_provider"


def test_delete_unknown_mode_is_404(
    tls_client: TestClient, auth_headers: dict[str, str]
) -> None:
    assert tls_client.delete("/admin/modes/gibtsnicht", headers=auth_headers).status_code == 404


def test_incomplete_row_does_not_break_the_listing(
    tls_client: TestClient, auth_headers: dict[str, str], db_engine: Engine
) -> None:
    """Eine unvollstaendige Zeile (von Hand, alte Version) darf nichts zerlegen."""
    with Session(db_engine) as s:
        s.add(ModeDefinition(mode_key="kaputt", description="ohne stt"))
        s.commit()
    assert tls_client.get("/admin/modes", headers=auth_headers).status_code == 200
    assert tls_client.get("/me/modes", headers=auth_headers).status_code == 200
    keys = [m["mode_key"] for m in tls_client.get("/me/modes", headers=auth_headers).json()]
    assert "kaputt" not in keys


# --- Stats + Guard ----------------------------------------------------------


def test_new_mode_appears_in_stats(
    tls_client: TestClient, auth_headers: dict[str, str]
) -> None:
    _put_mode(tls_client, auth_headers, "notiz", description="Kurznotiz", stt="openai_whisper")
    stats = tls_client.get("/stats", headers=auth_headers).json()
    assert "notiz" in stats["per_mode"]


def test_modes_admin_requires_admin(tls_client: TestClient, db_engine: Engine) -> None:
    from tests.unit.test_admin_routes import _add_plain_user, _plain_headers

    _add_plain_user(db_engine, name="modeless")
    assert tls_client.get("/admin/modes", headers=_plain_headers()).status_code == 403
    assert _put_mode(tls_client, _plain_headers(), "notiz", description="x").status_code == 403
    assert tls_client.delete("/admin/modes/notiz", headers=_plain_headers()).status_code == 403
