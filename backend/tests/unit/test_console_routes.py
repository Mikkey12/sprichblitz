"""Console-Session: Bootstrap-Code-Flow (POST→code→GET bootstrap→Cookie),
Cookie-Auth + CSRF-Header, Bearer-Präzedenz, SOFORT-Revoke, exp, TLS, Scoping, Logout."""

from __future__ import annotations

import time

from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine
from sqlmodel import Session, select

from sprichblitz_backend.crypto import KeyVault
from sprichblitz_backend.db.models import ApiToken, User
from sprichblitz_backend.services import usage
from sprichblitz_backend.services.console_session import (
    CONSOLE_SESSION_INFO,
    ConsoleSessionSigner,
)

_CONSOLE_HDR = {"X-Sb-Console": "1"}


def _bootstrap_cookie(tls_client: TestClient, auth_headers: dict[str, str]) -> None:
    """Voller Flow: POST /console/session (Bearer) → code → GET /console/bootstrap;
    die 302 legt das Session-Cookie in den tls_client-Jar."""
    code = tls_client.post("/console/session", headers=auth_headers).json()["code"]
    res = tls_client.get(f"/console/bootstrap?code={code}", follow_redirects=False)
    assert res.status_code == 302


# --- Bootstrap-Code-Flow ---------------------------------------------------


def test_session_returns_code(tls_client: TestClient, auth_headers: dict[str, str]) -> None:
    res = tls_client.post("/console/session", headers=auth_headers)
    assert res.status_code == 200
    body = res.json()
    assert isinstance(body["code"], str) and body["code"]
    assert body["expires_in"] > 0
    assert "set-cookie" not in res.headers  # Cookie erst beim Bootstrap


def test_session_accepts_empty_body_from_native_clients(
    tls_client: TestClient, auth_headers: dict[str, str]
) -> None:
    """Nativer Client-Vertrag: leerer Body OHNE Content-Type muss weiter gehen.

    Der Android-Client postet ``"".toRequestBody(null)`` (OkHttp) und der Tray
    schickt ebenfalls keinen Body. Der optionale ``scope``-Body darf das nicht in
    ein 422 drehen – sonst bricht der Konsolen-Webview.
    """
    res = tls_client.post("/console/session", headers=auth_headers, content=b"")
    assert res.status_code == 200
    assert res.json()["scope"] == "admin"  # Default je Rolle (Testnutzer ist Admin)


def test_session_requires_bearer(tls_client: TestClient) -> None:
    # Bearer-only: ein Cookie darf keinen Code prägen (kein Self-Refresh).
    tls_client.cookies.set("sb_console", "irgendwas")
    assert tls_client.post("/console/session").status_code == 401


def test_session_requires_tls(client: TestClient, auth_headers: dict[str, str]) -> None:
    res = client.post("/console/session", headers=auth_headers)
    assert res.status_code == 403
    assert res.json()["code"] == "tls_required"


def test_bootstrap_sets_secure_cookie(
    tls_client: TestClient, auth_headers: dict[str, str]
) -> None:
    code = tls_client.post("/console/session", headers=auth_headers).json()["code"]
    res = tls_client.get(f"/console/bootstrap?code={code}", follow_redirects=False)
    assert res.status_code == 302
    assert res.headers["location"] == "/app/"
    sc = res.headers["set-cookie"].lower()
    assert "sb_console=" in sc
    assert "httponly" in sc and "secure" in sc and "samesite=strict" in sc
    assert res.headers["referrer-policy"] == "no-referrer"  # Code leakt nicht via Referer


def test_bootstrap_invalid_code_rejected(tls_client: TestClient) -> None:
    res = tls_client.get("/console/bootstrap?code=bogus", follow_redirects=False)
    assert res.status_code == 400
    assert res.json()["code"] == "invalid_bootstrap_code"
    assert "set-cookie" not in res.headers


def test_bootstrap_code_is_single_use(
    tls_client: TestClient, auth_headers: dict[str, str]
) -> None:
    code = tls_client.post("/console/session", headers=auth_headers).json()["code"]
    assert tls_client.get(f"/console/bootstrap?code={code}", follow_redirects=False).status_code == 302
    # zweite Einlösung desselben Codes → abgelehnt
    assert tls_client.get(f"/console/bootstrap?code={code}", follow_redirects=False).status_code == 400


def test_bootstrap_requires_tls(client: TestClient) -> None:
    # require_tls greift VOR dem Redeem (Code egal) → Secure-Cookie nie über http.
    res = client.get("/console/bootstrap?code=anything", follow_redirects=False)
    assert res.status_code == 403
    assert res.json()["code"] == "tls_required"


# --- Cookie-Auth + CSRF + Präzedenz ----------------------------------------


def test_cookie_auth_works_on_me(tls_client: TestClient, auth_headers: dict[str, str]) -> None:
    _bootstrap_cookie(tls_client, auth_headers)
    res = tls_client.get("/me", headers=_CONSOLE_HDR)  # nur Cookie + CSRF-Header
    assert res.status_code == 200
    assert res.json()["name"] == "tester"


def test_cookie_auth_requires_console_header(
    tls_client: TestClient, auth_headers: dict[str, str]
) -> None:
    _bootstrap_cookie(tls_client, auth_headers)
    assert tls_client.get("/me").status_code == 401  # Cookie ohne X-Sb-Console → CSRF-Schutz


def test_bearer_wins_over_cookie(tls_client: TestClient, auth_headers: dict[str, str]) -> None:
    tls_client.cookies.set("sb_console", "kaputt")
    res = tls_client.get("/me", headers={**auth_headers, **_CONSOLE_HDR})
    assert res.status_code == 200  # gültiger Bearer gewinnt, Cookie ignoriert


def test_revoked_user_rejected_on_cookie_path_immediately(
    tls_client: TestClient, auth_headers: dict[str, str], db_engine: Engine
) -> None:
    _bootstrap_cookie(tls_client, auth_headers)
    assert tls_client.get("/me", headers=_CONSOLE_HDR).status_code == 200
    with Session(db_engine) as s:
        user = s.exec(select(User)).first()
        user.disabled = True
        s.add(user)
        s.commit()
    assert tls_client.get("/me", headers=_CONSOLE_HDR).status_code == 401  # SOFORT


def test_revoking_bootstrap_token_kills_cookie_immediately(
    tls_client: TestClient, auth_headers: dict[str, str], db_engine: Engine
) -> None:
    """tid-Bindung: der Revoke EINES Tokens beendet die daraus abgeleitete Session SOFORT.

    Vorher überlebte das Cookie bis zum TTL – nur „Nutzer deaktivieren" wirkte sofort.
    Das war die Lücke, wegen der die Verwaltung dem Cookie verschlossen blieb.
    """
    _bootstrap_cookie(tls_client, auth_headers)
    assert tls_client.get("/me", headers=_CONSOLE_HDR).status_code == 200
    with Session(db_engine) as s:
        token = s.exec(select(ApiToken)).one()
        token.revoked = True
        s.add(token)
        s.commit()
    assert tls_client.get("/me", headers=_CONSOLE_HDR).status_code == 401  # SOFORT


def test_expired_cookie_rejected(tls_client: TestClient, key_vault: KeyVault) -> None:
    signer = ConsoleSessionSigner(key_vault.derive_subkey(CONSOLE_SESSION_INFO))
    expired = signer.mint(1, token_id=1, now=time.time() - 100_000)
    tls_client.cookies.set("sb_console", expired)
    assert tls_client.get("/me", headers=_CONSOLE_HDR).status_code == 401


def test_invalid_bearer_does_not_fall_through_to_cookie(
    tls_client: TestClient, auth_headers: dict[str, str]
) -> None:
    _bootstrap_cookie(tls_client, auth_headers)  # gültiges Cookie im Jar
    res = tls_client.get(
        "/me", headers={"Authorization": "Bearer total-ungueltig", "X-Sb-Console": "1"}
    )
    assert res.status_code == 401  # Präsenz-basiert: Bearer-Branch raist, kein Fallthrough


def test_malformed_authorization_does_not_fall_through_to_cookie(
    tls_client: TestClient, auth_headers: dict[str, str]
) -> None:
    _bootstrap_cookie(tls_client, auth_headers)
    res = tls_client.get("/me", headers={"Authorization": "Basic abc123", "X-Sb-Console": "1"})
    assert res.status_code == 401


# --- Reichweite (Least Privilege) ------------------------------------------


def test_cookie_rejected_on_dictation_endpoint(
    tls_client: TestClient, auth_headers: dict[str, str], audio_16k_wav: bytes
) -> None:
    _bootstrap_cookie(tls_client, auth_headers)
    res = tls_client.post(
        "/transcribe",
        headers=_CONSOLE_HDR,  # Cookie automatisch, KEIN Bearer
        files={"file": ("a.wav", audio_16k_wav, "audio/wav")},
        data={"mode": "exact_de"},
    )
    assert res.status_code == 401  # Diktat = Bearer-only


def test_cookie_reads_own_config(tls_client: TestClient, auth_headers: dict[str, str]) -> None:
    _bootstrap_cookie(tls_client, auth_headers)
    assert tls_client.get("/config", headers=_CONSOLE_HDR).status_code == 200


def test_cookie_reads_own_stats(tls_client: TestClient, auth_headers: dict[str, str]) -> None:
    _bootstrap_cookie(tls_client, auth_headers)
    assert tls_client.get("/stats", headers=_CONSOLE_HDR).status_code == 200


def test_admin_cookie_stats_is_own_scoped_not_aggregate(
    tls_client: TestClient, auth_headers: dict[str, str], db_engine: Engine
) -> None:
    # 'tester' ist Admin. Der zweite User darf nur im BEARER-Aggregat auftauchen,
    # NICHT im Admin-COOKIE-View (Least Privilege auf dem Cookie-Pfad).
    with Session(db_engine) as s:
        tester = s.exec(select(User).where(User.name == "tester")).first()
        other = User(name="other", is_admin=False, processing_location="online")
        s.add(other)
        s.commit()
        s.refresh(other)
        usage.record_success(s, tester.id, "exact_de", audio_seconds=3.0)
        usage.record_success(s, other.id, "exact_de", audio_seconds=5.0)
    _bootstrap_cookie(tls_client, auth_headers)
    cookie_view = tls_client.get("/stats", headers=_CONSOLE_HDR).json()["per_mode"]["exact_de"]
    assert cookie_view["requests"] == 1  # nur 'tester' (eigen-scopet)
    bearer_view = tls_client.get("/stats", headers=auth_headers).json()["per_mode"]["exact_de"]
    assert bearer_view["requests"] == 2  # Aggregat (tester + other)


def test_delete_session_clears_cookie(
    tls_client: TestClient, auth_headers: dict[str, str]
) -> None:
    _bootstrap_cookie(tls_client, auth_headers)
    res = tls_client.delete("/console/session")
    assert res.status_code == 204
    assert "sb_console=" in res.headers["set-cookie"].lower()


# --- Anti-Session-Fixation: Client-Nonce-Bindung ----------------------------


def test_bootstrap_with_matching_nonce_succeeds(
    tls_client: TestClient, auth_headers: dict[str, str]
) -> None:
    code = tls_client.post(
        "/console/session", headers={**auth_headers, "X-Sb-Boot-Nonce": "n0nce"}
    ).json()["code"]
    tls_client.cookies.set("sb_boot", "n0nce")  # Client hätte das in der WebView gesetzt
    res = tls_client.get(f"/console/bootstrap?code={code}", follow_redirects=False)
    assert res.status_code == 302
    assert "sb_console=" in res.headers["set-cookie"].lower()


def test_bootstrap_with_wrong_nonce_rejected(
    tls_client: TestClient, auth_headers: dict[str, str]
) -> None:
    code = tls_client.post(
        "/console/session", headers={**auth_headers, "X-Sb-Boot-Nonce": "n0nce"}
    ).json()["code"]
    tls_client.cookies.set("sb_boot", "falsch")
    res = tls_client.get(f"/console/bootstrap?code={code}", follow_redirects=False)
    assert res.status_code == 400
    assert res.json()["code"] == "invalid_bootstrap_code"


def test_bootstrap_missing_nonce_cookie_rejected(
    tls_client: TestClient, auth_headers: dict[str, str]
) -> None:
    # An Nonce gebundener Code, aber kein sb_boot-Cookie (Angreifer-Link im Opfer-Browser).
    code = tls_client.post(
        "/console/session", headers={**auth_headers, "X-Sb-Boot-Nonce": "n0nce"}
    ).json()["code"]
    res = tls_client.get(f"/console/bootstrap?code={code}", follow_redirects=False)
    assert res.status_code == 400


def test_bootstrap_nonceless_rejected_when_required(
    tls_client: TestClient, auth_headers: dict[str, str]
) -> None:
    tls_client.app.state.require_console_nonce = True
    code = tls_client.post("/console/session", headers=auth_headers).json()["code"]  # kein Nonce
    res = tls_client.get(f"/console/bootstrap?code={code}", follow_redirects=False)
    assert res.status_code == 400
