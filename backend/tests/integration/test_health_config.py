from __future__ import annotations

from fastapi.testclient import TestClient


def test_health_returns_ok(client: TestClient) -> None:
    res = client.get("/health")
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "ok"
    assert "version" in body
    assert isinstance(body["uptime_seconds"], int)


def test_config_returns_modes_and_providers(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    res = client.get("/config", headers=auth_headers)
    assert res.status_code == 200
    body = res.json()

    mode_names = {m["name"] for m in body["modes"]}
    assert "exact_de" in mode_names
    assert "mail" in mode_names

    stt_names = {p["name"] for p in body["stt_providers"]}
    assert "openai_whisper" in stt_names
    assert "lm_studio_whisper" in stt_names

    llm_names = {p["name"] for p in body["llm_providers"]}
    assert "anthropic" in llm_names

    # Die mitgelieferte Grundkonfiguration verwendet Haiku:
    anthropic = next(p for p in body["llm_providers"] if p["name"] == "anthropic")
    assert anthropic["default_model"] == "claude-haiku-4-5-20251001"
