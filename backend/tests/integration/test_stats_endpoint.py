from __future__ import annotations

from fastapi.testclient import TestClient
from sqlmodel import Session

from sprichblitz_backend.auth import hash_token
from sprichblitz_backend.db.models import ApiToken, User


def test_stats_increments_after_request(
    client: TestClient, audio_16k_wav: bytes, auth_headers: dict[str, str]
) -> None:
    base = client.get("/stats", headers=auth_headers).json()["per_mode"]["exact_de"]
    assert base["requests"] == 0

    res = client.post(
        "/transcribe",
        headers=auth_headers,
        files={"file": ("h.wav", audio_16k_wav, "audio/wav")},
        data={"mode": "exact_de"},
    )
    assert res.status_code == 200

    after = client.get("/stats", headers=auth_headers).json()["per_mode"]["exact_de"]
    assert after["requests"] == 1
    assert after["errors"] == 0
    assert after["total_audio_seconds"] > 0  # Audio-Dauer gebucht


def test_stats_user_scoped_vs_admin_aggregate(
    client: TestClient, db_engine, audio_16k_wav: bytes, auth_headers: dict[str, str]
) -> None:
    # 'tester' ist Admin (Fixture). Zusätzlich ein Nicht-Admin 'u'.
    with Session(db_engine) as s:
        u = User(name="u", is_admin=False, processing_location="online")
        s.add(u)
        s.commit()
        s.refresh(u)
        s.add(ApiToken(user_id=u.id, token_hash=hash_token("u-tok"), label="u"))
        s.commit()
    u_headers = {"Authorization": "Bearer u-tok"}
    files = {"file": ("a.wav", audio_16k_wav, "audio/wav")}

    client.post("/transcribe", headers=u_headers, files=files, data={"mode": "exact_de"})
    client.post("/transcribe", headers=auth_headers, files=files, data={"mode": "exact_de"})

    # Nicht-Admin sieht nur die eigene Nutzung (1):
    u_stats = client.get("/stats", headers=u_headers).json()["per_mode"]["exact_de"]
    assert u_stats["requests"] == 1
    # Admin sieht das Aggregat über alle Nutzer (2):
    admin_stats = client.get("/stats", headers=auth_headers).json()["per_mode"]["exact_de"]
    assert admin_stats["requests"] == 2
