"""Admin-Routen: Rollen-Guard (Bearer + Console-Scope), Nutzer-CRUD, Token-Lifecycle.

Der Default-Testnutzer (``conftest.db_engine``) ist Admin; ein zweiter, nicht-
privilegierter Nutzer wird pro Test dazugelegt, wo die Abgrenzung zählt.
"""

from __future__ import annotations

from datetime import date

from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine
from sqlmodel import Session, select

from sprichblitz_backend.auth import hash_token
from sprichblitz_backend.db.models import ApiToken, ModeOverride, UsageDaily, User

_CONSOLE_HDR = {"X-Sb-Console": "1"}
_PLAIN_USER_TOKEN = "plain-user-token-0987654321"


def _add_plain_user(db_engine: Engine, *, name: str = "normalo") -> int:
    """Nicht-Admin + Token → gibt die user_id zurück."""
    with Session(db_engine) as s:
        user = User(name=name, is_admin=False, processing_location="online")
        s.add(user)
        s.commit()
        s.refresh(user)
        s.add(
            ApiToken(
                user_id=user.id, token_hash=hash_token(_PLAIN_USER_TOKEN), label="plain"
            )
        )
        s.commit()
        return user.id


def _plain_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {_PLAIN_USER_TOKEN}"}


def _bootstrap_cookie(tls_client: TestClient, headers: dict[str, str], **body) -> None:
    code = tls_client.post("/console/session", headers=headers, json=body or None).json()["code"]
    assert tls_client.get(f"/console/bootstrap?code={code}", follow_redirects=False).status_code == 302


# --- Rollen-Guard ----------------------------------------------------------


def test_admin_can_list_users_via_bearer(
    tls_client: TestClient, auth_headers: dict[str, str]
) -> None:
    res = tls_client.get("/admin/users", headers=auth_headers)
    assert res.status_code == 200
    assert [u["name"] for u in res.json()] == ["tester"]


def test_non_admin_forbidden(tls_client: TestClient, db_engine: Engine) -> None:
    _add_plain_user(db_engine)
    res = tls_client.get("/admin/users", headers=_plain_headers())
    assert res.status_code == 403
    assert res.json()["code"] == "admin_required"


def test_unauthenticated_is_401_not_403(tls_client: TestClient) -> None:
    # „wer bist du" (401) muss von „dir fehlt die Rolle" (403) unterscheidbar bleiben.
    assert tls_client.get("/admin/users").status_code == 401


# --- Console-Scope ---------------------------------------------------------


def test_admin_console_cookie_reaches_admin(
    tls_client: TestClient, auth_headers: dict[str, str]
) -> None:
    # Default-Scope für einen Admin ist „admin" → der Tab funktioniert mit dem
    # bestehenden Tray, der den Scope-Parameter gar nicht kennt.
    _bootstrap_cookie(tls_client, auth_headers)
    assert tls_client.get("/admin/users", headers=_CONSOLE_HDR).status_code == 200


def test_opted_down_console_cookie_cannot_reach_admin(
    tls_client: TestClient, auth_headers: dict[str, str]
) -> None:
    _bootstrap_cookie(tls_client, auth_headers, scope="user")
    # Self-Service bleibt erreichbar …
    assert tls_client.get("/me", headers=_CONSOLE_HDR).status_code == 200
    # … die Verwaltung nicht, obwohl der Nutzer Admin IST.
    res = tls_client.get("/admin/users", headers=_CONSOLE_HDR)
    assert res.status_code == 403
    assert res.json()["code"] == "admin_required"


def test_non_admin_cannot_request_admin_scope(
    tls_client: TestClient, db_engine: Engine
) -> None:
    _add_plain_user(db_engine)
    res = tls_client.post("/console/session", headers=_plain_headers(), json={"scope": "admin"})
    assert res.status_code == 403


def test_unknown_scope_rejected(tls_client: TestClient, auth_headers: dict[str, str]) -> None:
    res = tls_client.post("/console/session", headers=auth_headers, json={"scope": "root"})
    assert res.status_code == 422


def test_me_reports_admin_scope(tls_client: TestClient, auth_headers: dict[str, str]) -> None:
    # Die Konsole blendet den Tab danach ein – Guard und Anzeige müssen übereinstimmen.
    _bootstrap_cookie(tls_client, auth_headers, scope="user")
    body = tls_client.get("/me", headers=_CONSOLE_HDR).json()
    assert body["is_admin"] is True
    assert body["admin_scope"] is False  # Rolle ja, Session-Scope nein


# --- Nutzer-CRUD -----------------------------------------------------------


def test_create_user(tls_client: TestClient, auth_headers: dict[str, str]) -> None:
    res = tls_client.post(
        "/admin/users",
        headers=auth_headers,
        json={"name": "neu", "display_name": "Neue Nutzerin", "processing_location": "local"},
    )
    assert res.status_code == 201
    body = res.json()
    assert (body["name"], body["display_name"], body["processing_location"]) == (
        "neu",
        "Neue Nutzerin",
        "local",
    )
    assert body["is_admin"] is False and body["disabled"] is False


def test_create_user_defaults_to_online(
    tls_client: TestClient, auth_headers: dict[str, str]
) -> None:
    res = tls_client.post("/admin/users", headers=auth_headers, json={"name": "cloud-ready"})
    assert res.status_code == 201
    assert res.json()["processing_location"] == "online"


def test_create_duplicate_user_is_409(tls_client: TestClient, auth_headers: dict[str, str]) -> None:
    tls_client.post("/admin/users", headers=auth_headers, json={"name": "doppelt"})
    res = tls_client.post("/admin/users", headers=auth_headers, json={"name": "doppelt"})
    assert res.status_code == 409
    assert res.json()["code"] == "user_exists"


def test_patch_user_only_touches_given_fields(
    tls_client: TestClient, auth_headers: dict[str, str], db_engine: Engine
) -> None:
    uid = _add_plain_user(db_engine)
    res = tls_client.patch(
        f"/admin/users/{uid}", headers=auth_headers, json={"processing_location": "local"}
    )
    assert res.status_code == 200
    body = res.json()
    assert body["processing_location"] == "local"
    assert body["name"] == "normalo"  # unangetastet
    assert body["is_admin"] is False


def test_patch_unknown_user_is_404(tls_client: TestClient, auth_headers: dict[str, str]) -> None:
    res = tls_client.patch("/admin/users/9999", headers=auth_headers, json={"disabled": True})
    assert res.status_code == 404


def test_disable_and_reenable_user(
    tls_client: TestClient, auth_headers: dict[str, str], db_engine: Engine
) -> None:
    uid = _add_plain_user(db_engine)
    assert tls_client.patch(
        f"/admin/users/{uid}", headers=auth_headers, json={"disabled": True}
    ).json()["disabled"] is True
    # Deaktivierte müssen sichtbar bleiben, sonst wären sie nicht reaktivierbar.
    assert "normalo" in [u["name"] for u in tls_client.get("/admin/users", headers=auth_headers).json()]
    assert tls_client.get("/me", headers=_plain_headers()).status_code == 401
    assert tls_client.patch(
        f"/admin/users/{uid}", headers=auth_headers, json={"disabled": False}
    ).json()["disabled"] is False
    assert tls_client.get("/me", headers=_plain_headers()).status_code == 200


# --- Aussperr-Schutz -------------------------------------------------------


def test_admin_cannot_disable_self(
    tls_client: TestClient, auth_headers: dict[str, str], db_engine: Engine
) -> None:
    with Session(db_engine) as s:
        me = s.exec(select(User).where(User.name == "tester")).one()
    res = tls_client.patch(f"/admin/users/{me.id}", headers=auth_headers, json={"disabled": True})
    assert res.status_code == 409
    assert res.json()["code"] == "self_lockout"


def test_admin_cannot_drop_own_admin_role(
    tls_client: TestClient, auth_headers: dict[str, str], db_engine: Engine
) -> None:
    with Session(db_engine) as s:
        me = s.exec(select(User).where(User.name == "tester")).one()
    res = tls_client.patch(f"/admin/users/{me.id}", headers=auth_headers, json={"is_admin": False})
    assert res.status_code == 409


def test_admin_can_demote_someone_else(
    tls_client: TestClient, auth_headers: dict[str, str], db_engine: Engine
) -> None:
    uid = _add_plain_user(db_engine)
    tls_client.patch(f"/admin/users/{uid}", headers=auth_headers, json={"is_admin": True})
    res = tls_client.patch(f"/admin/users/{uid}", headers=auth_headers, json={"is_admin": False})
    assert res.status_code == 200 and res.json()["is_admin"] is False


# --- Loeschen --------------------------------------------------------------


def test_delete_user_removes_all_children(
    tls_client: TestClient, auth_headers: dict[str, str], db_engine: Engine
) -> None:
    """Harte Loeschung raeumt alle vier Kindtabellen mit ab.

    Ohne explizites Aufraeumen scheitert das DELETE am FK-Constraint
    (PRAGMA foreign_keys=ON, kein ON DELETE CASCADE) – dieser Test nagelt fest,
    dass die Kaskade wirklich laeuft statt zu werfen.
    """
    uid = _add_plain_user(db_engine)
    tls_client.post(f"/admin/users/{uid}/tokens", headers=auth_headers, json={"label": "x"})
    with Session(db_engine) as s:
        s.add(ModeOverride(user_id=uid, mode_key="mail", display_name="Eigen"))
        s.add(UsageDaily(user_id=uid, mode_key="mail", day=date(2026, 7, 1), count=3))
        s.commit()

    assert tls_client.delete(f"/admin/users/{uid}", headers=auth_headers).status_code == 204

    with Session(db_engine) as s:
        assert s.get(User, uid) is None
        assert s.exec(select(ApiToken).where(ApiToken.user_id == uid)).all() == []
        assert s.exec(select(ModeOverride).where(ModeOverride.user_id == uid)).all() == []
        assert s.exec(select(UsageDaily).where(UsageDaily.user_id == uid)).all() == []


def test_deleted_users_token_stops_authenticating(
    tls_client: TestClient, auth_headers: dict[str, str], db_engine: Engine
) -> None:
    uid = _add_plain_user(db_engine)
    assert tls_client.get("/me", headers=_plain_headers()).status_code == 200
    tls_client.delete(f"/admin/users/{uid}", headers=auth_headers)
    assert tls_client.get("/me", headers=_plain_headers()).status_code == 401


def test_delete_user_is_gone_from_list(
    tls_client: TestClient, auth_headers: dict[str, str], db_engine: Engine
) -> None:
    uid = _add_plain_user(db_engine)
    tls_client.delete(f"/admin/users/{uid}", headers=auth_headers)
    names = [u["name"] for u in tls_client.get("/admin/users", headers=auth_headers).json()]
    assert names == ["tester"]  # anders als disabled: wirklich weg


def test_admin_cannot_delete_self(
    tls_client: TestClient, auth_headers: dict[str, str], db_engine: Engine
) -> None:
    with Session(db_engine) as s:
        me = s.exec(select(User).where(User.name == "tester")).one()
    res = tls_client.delete(f"/admin/users/{me.id}", headers=auth_headers)
    assert res.status_code == 409
    assert res.json()["code"] == "self_lockout"


def test_delete_unknown_user_is_404(tls_client: TestClient, auth_headers: dict[str, str]) -> None:
    assert tls_client.delete("/admin/users/9999", headers=auth_headers).status_code == 404


def test_non_admin_cannot_delete(tls_client: TestClient, db_engine: Engine) -> None:
    uid = _add_plain_user(db_engine)
    assert tls_client.delete(f"/admin/users/{uid}", headers=_plain_headers()).status_code == 403


def test_user_list_reports_what_would_be_lost(
    tls_client: TestClient, auth_headers: dict[str, str], db_engine: Engine
) -> None:
    # Die Konsole benennt in der Bestaetigung, was mitgeht – dafuer braucht sie Zahlen.
    uid = _add_plain_user(db_engine)
    with Session(db_engine) as s:
        s.add(UsageDaily(user_id=uid, mode_key="mail", day=date(2026, 7, 1), count=3))
        s.add(UsageDaily(user_id=uid, mode_key="mail", day=date(2026, 7, 2), count=5))
        s.commit()
    users = {u["name"]: u for u in tls_client.get("/admin/users", headers=auth_headers).json()}
    assert users["normalo"]["token_count"] == 1  # aus _add_plain_user
    assert users["normalo"]["usage_days"] == 2


# --- Token-Lifecycle -------------------------------------------------------


def test_issued_token_is_usable_and_shown_once(
    tls_client: TestClient, auth_headers: dict[str, str], db_engine: Engine
) -> None:
    uid = _add_plain_user(db_engine)
    res = tls_client.post(
        f"/admin/users/{uid}/tokens", headers=auth_headers, json={"label": "android"}
    )
    assert res.status_code == 201
    plaintext = res.json()["token"]
    # Das ausgestellte Token authentifiziert wirklich …
    assert tls_client.get("/me", headers={"Authorization": f"Bearer {plaintext}"}).json()["name"] == "normalo"
    # … taucht aber nirgends wieder auf: die Liste zeigt nur Metadaten.
    listed = tls_client.get(f"/admin/users/{uid}/tokens", headers=auth_headers).json()
    assert {"android", "plain"} == {t["label"] for t in listed}
    assert all("token" not in t for t in listed)


def test_token_is_stored_hashed_only(
    tls_client: TestClient, auth_headers: dict[str, str], db_engine: Engine
) -> None:
    uid = _add_plain_user(db_engine)
    plaintext = tls_client.post(f"/admin/users/{uid}/tokens", headers=auth_headers, json={}).json()["token"]
    with Session(db_engine) as s:
        hashes = [t.token_hash for t in s.exec(select(ApiToken)).all()]
    assert plaintext not in hashes  # kein Klartext in der DB
    assert hash_token(plaintext) in hashes


def test_issue_token_requires_tls(client: TestClient, auth_headers: dict[str, str], db_engine: Engine) -> None:
    # Die Antwort trägt ein Secret → wie beim Key-Upload nur über TLS.
    uid = _add_plain_user(db_engine)
    res = client.post(f"/admin/users/{uid}/tokens", headers=auth_headers, json={})
    assert res.status_code == 403
    assert res.json()["code"] == "tls_required"


def test_revoked_token_stops_authenticating(
    tls_client: TestClient, auth_headers: dict[str, str], db_engine: Engine
) -> None:
    uid = _add_plain_user(db_engine)
    issued = tls_client.post(f"/admin/users/{uid}/tokens", headers=auth_headers, json={}).json()
    hdr = {"Authorization": f"Bearer {issued['token']}"}
    assert tls_client.get("/me", headers=hdr).status_code == 200
    assert tls_client.delete(f"/admin/tokens/{issued['id']}", headers=auth_headers).status_code == 204
    assert tls_client.get("/me", headers=hdr).status_code == 401


def test_revoke_unknown_token_is_404(tls_client: TestClient, auth_headers: dict[str, str]) -> None:
    assert tls_client.delete("/admin/tokens/9999", headers=auth_headers).status_code == 404


def test_tokens_of_unknown_user_is_404(tls_client: TestClient, auth_headers: dict[str, str]) -> None:
    assert tls_client.get("/admin/users/9999/tokens", headers=auth_headers).status_code == 404
