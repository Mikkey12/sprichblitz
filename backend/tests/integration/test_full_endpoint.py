from __future__ import annotations

from fastapi.testclient import TestClient


def test_full_pipeline_audio_to_polished_text(
    client: TestClient, audio_16k_wav: bytes, auth_headers: dict[str, str]
) -> None:
    res = client.post(
        "/full",
        headers=auth_headers,
        files={"file": ("h.wav", audio_16k_wav, "audio/wav")},
        data={"mode": "mail"},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["mode"] == "mail"
    assert body["raw_text"] == "cloud transcript"
    assert body["final_text"] == "polished text"
    assert body["stt_provider"] == "openai_whisper"
    assert body["llm_provider"] == "anthropic"
    assert body["llm_model"] == "claude-haiku-4-5-20251001"
    assert body["used_fallback"] is False


def test_full_skips_llm_for_exact_de(
    client: TestClient, audio_16k_wav: bytes, auth_headers: dict[str, str]
) -> None:
    res = client.post(
        "/full",
        headers=auth_headers,
        files={"file": ("h.wav", audio_16k_wav, "audio/wav")},
        data={"mode": "exact_de"},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["raw_text"] == body["final_text"] == "cloud transcript"
    assert body["llm_provider"] is None
    assert body["llm_model"] is None


def test_full_stt_override_switches_provider(
    client: TestClient, audio_16k_wav: bytes, auth_headers: dict[str, str]
) -> None:
    res = client.post(
        "/full",
        headers=auth_headers,
        files={"file": ("h.wav", audio_16k_wav, "audio/wav")},
        data={"mode": "exact_de", "stt": "lm_studio_whisper"},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["stt_provider"] == "lm_studio_whisper"
    assert body["raw_text"] == "local transcript"


def test_full_rejects_unknown_stt_override(
    client: TestClient, audio_16k_wav: bytes, auth_headers: dict[str, str]
) -> None:
    res = client.post(
        "/full",
        headers=auth_headers,
        files={"file": ("h.wav", audio_16k_wav, "audio/wav")},
        data={"mode": "exact_de", "stt": "nope"},
    )
    assert res.status_code == 400
    assert res.json()["code"] == "override_not_allowed"
