from __future__ import annotations

from fastapi.testclient import TestClient


def test_transcribe_returns_text_and_metadata(
    client: TestClient, audio_16k_wav: bytes, auth_headers: dict[str, str]
) -> None:
    res = client.post(
        "/transcribe",
        headers=auth_headers,
        files={"file": ("hello.wav", audio_16k_wav, "audio/wav")},
        data={"mode": "exact_de"},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["mode"] == "exact_de"
    assert body["text"] == "cloud transcript"
    assert body["stt_provider"] == "openai_whisper"
    assert body["used_fallback"] is False
    assert body["audio_seconds"] > 0
    assert isinstance(body["duration_ms"], int)


def test_transcribe_rejects_missing_auth(
    client: TestClient, audio_16k_wav: bytes
) -> None:
    res = client.post(
        "/transcribe",
        files={"file": ("h.wav", audio_16k_wav, "audio/wav")},
        data={"mode": "exact_de"},
    )
    assert res.status_code == 401


def test_transcribe_rejects_unknown_mode(
    client: TestClient, audio_16k_wav: bytes, auth_headers: dict[str, str]
) -> None:
    res = client.post(
        "/transcribe",
        headers=auth_headers,
        files={"file": ("h.wav", audio_16k_wav, "audio/wav")},
        data={"mode": "no_such_mode"},
    )
    # Modi sind config-getrieben (kein Enum-Gate mehr): ein unbekannter Modus
    # wird nicht mehr vom Form-Validator (422) abgewiesen, sondern von der
    # Pipeline gegen die Config → ModeNotConfigured (400).
    assert res.status_code == 400
    assert res.json()["code"] == "mode_not_configured"
