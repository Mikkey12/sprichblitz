from __future__ import annotations

import pytest
import respx
from httpx import Response

from sprichblitz_backend.providers.llm.openai_compatible import OpenAICompatibleLLMProvider
from sprichblitz_backend.util.errors import ProviderInvalidResponse


@respx.mock
async def test_chat_completion_uses_default_model(monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "k")
    route = respx.post("https://api.openai.com/v1/chat/completions").mock(
        return_value=Response(
            200,
            json={
                "choices": [{"message": {"content": "hallo"}}],
                "usage": {"prompt_tokens": 5, "completion_tokens": 7},
            },
        )
    )
    provider = OpenAICompatibleLLMProvider(
        name="openai",
        base_url="https://api.openai.com/v1",
        api_key_env="OPENAI_API_KEY",
        default_model="gpt-4o-mini",
    )
    result = await provider.complete(system="sys", user="u")
    assert result.text == "hallo"
    assert result.model == "gpt-4o-mini"
    assert result.input_tokens == 5
    assert result.output_tokens == 7

    body = route.calls.last.request.read()
    assert b"gpt-4o-mini" in body
    assert b'"role":"system"' in body
    assert b'"role":"user"' in body


@respx.mock
async def test_lm_studio_chat_no_auth_header() -> None:
    route = respx.post("http://localhost:1234/v1/chat/completions").mock(
        return_value=Response(
            200, json={"choices": [{"message": {"content": "ok"}}]}
        )
    )
    provider = OpenAICompatibleLLMProvider(
        name="lm_studio",
        base_url="http://localhost:1234/v1",
        api_key_env="",
        default_model="qwen3.5-9b",
    )
    await provider.complete(system="sys", user="u")
    headers = {k.lower() for k in route.calls.last.request.headers}
    assert "authorization" not in headers


@respx.mock
async def test_list_models_parses_data_array(monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "k")
    respx.get("https://api.openai.com/v1/models").mock(
        return_value=Response(
            200, json={"data": [{"id": "gpt-4o-mini"}, {"id": "whisper-1"}]}
        )
    )
    provider = OpenAICompatibleLLMProvider(
        name="openai",
        base_url="https://api.openai.com/v1",
        api_key_env="OPENAI_API_KEY",
        default_model="gpt-4o-mini",
    )
    models = await provider.list_models()
    assert "gpt-4o-mini" in models
    assert "whisper-1" in models


@respx.mock
async def test_health_check_returns_false_on_5xx(monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "k")
    respx.get("https://api.openai.com/v1/models").mock(return_value=Response(503))
    provider = OpenAICompatibleLLMProvider(
        name="openai",
        base_url="https://api.openai.com/v1",
        api_key_env="OPENAI_API_KEY",
        default_model="gpt-4o-mini",
    )
    # Health-Check tolerates 5xx as "down" without retrying
    healthy = await provider.health_check()
    assert healthy is False


@respx.mock
async def test_health_check_false_on_401(monkeypatch) -> None:
    """P2d: ein 401 (falscher/abgelaufener Key) darf nicht als 'healthy'
    durchgehen – vorher galt jeder Status < 500 als gesund."""
    monkeypatch.setenv("OPENAI_API_KEY", "wrong")
    respx.get("https://api.openai.com/v1/models").mock(return_value=Response(401))
    provider = OpenAICompatibleLLMProvider(
        name="openai",
        base_url="https://api.openai.com/v1",
        api_key_env="OPENAI_API_KEY",
        default_model="gpt-4o-mini",
    )
    assert await provider.health_check() is False


@respx.mock
async def test_health_check_404_is_not_healthy(monkeypatch) -> None:
    """Ein beliebiger 404 beweist weder Dienst- noch API-Bereitschaft."""
    monkeypatch.setenv("OPENAI_API_KEY", "k")
    respx.get("https://api.openai.com/v1/models").mock(return_value=Response(404))
    provider = OpenAICompatibleLLMProvider(
        name="openai",
        base_url="https://api.openai.com/v1",
        api_key_env="OPENAI_API_KEY",
        default_model="gpt-4o-mini",
    )
    assert await provider.health_check() is False


@respx.mock
async def test_explicit_health_path_requires_success_status() -> None:
    ok = respx.get("http://localhost:1234/health").mock(return_value=Response(204))
    provider = OpenAICompatibleLLMProvider(
        name="local",
        base_url="http://localhost:1234/v1",
        api_key_env="",
        default_model="qwen",
        health_path="/health",
    )
    assert await provider.health_check() is True
    assert ok.called


@respx.mock
async def test_chat_malformed_success_json_maps_to_invalid_response() -> None:
    respx.post("http://localhost:1234/v1/chat/completions").mock(
        return_value=Response(200, text="<html>not JSON</html>")
    )
    provider = OpenAICompatibleLLMProvider(
        name="local",
        base_url="http://localhost:1234/v1",
        api_key_env="",
        default_model="qwen",
    )
    with pytest.raises(ProviderInvalidResponse, match="invalid JSON"):
        await provider.complete(system="s", user="u")


@respx.mock
async def test_chat_non_object_or_non_string_content_is_rejected() -> None:
    route = respx.post("http://localhost:1234/v1/chat/completions").mock(
        side_effect=[
            Response(200, json=[]),
            Response(200, json={"choices": [{"message": {"content": 123}}]}),
        ]
    )
    provider = OpenAICompatibleLLMProvider(
        name="local",
        base_url="http://localhost:1234/v1",
        api_key_env="",
        default_model="qwen",
    )
    with pytest.raises(ProviderInvalidResponse, match="non-object"):
        await provider.complete(system="s", user="u")
    with pytest.raises(ProviderInvalidResponse, match="not a string"):
        await provider.complete(system="s", user="u")
    assert route.call_count == 2


@respx.mock
async def test_list_models_tolerates_malformed_success_payload() -> None:
    route = respx.get("http://localhost:1234/v1/models").mock(
        side_effect=[
            Response(200, text="not-json"),
            Response(200, json=[]),
            Response(200, json={"data": [{"id": 123}, {"id": "valid"}]}),
        ]
    )
    provider = OpenAICompatibleLLMProvider(
        name="local",
        base_url="http://localhost:1234/v1",
        api_key_env="",
        default_model="qwen",
    )
    assert await provider.list_models() == []
    assert await provider.list_models() == []
    assert await provider.list_models() == ["valid"]
    assert route.call_count == 3


async def test_health_check_false_when_key_env_missing(monkeypatch) -> None:
    """Leere Key-Env → ProviderAuthError darf nicht durchschlagen, sondern
    health_check muss sauber False liefern."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    provider = OpenAICompatibleLLMProvider(
        name="openai",
        base_url="https://api.openai.com/v1",
        api_key_env="OPENAI_API_KEY",
        default_model="gpt-4o-mini",
    )
    assert await provider.health_check() is False


@respx.mock
async def test_chat_4xx_maps_to_provider_invalid_response_without_body(monkeypatch) -> None:
    """Bei 4xx muss der Provider auf ProviderInvalidResponse mappen (nicht 500-
    Generic) – aber P1-2: der Upstream-Body darf NICHT in die Message lecken
    (die geht als `error` an Client + Logs; könnte Transkript-Text echoen)."""
    monkeypatch.setenv("OPENAI_API_KEY", "k")
    respx.post("http://localhost:1234/v1/chat/completions").mock(
        return_value=Response(
            400,
            json={"error": {"message": "Model 'qwen3.5-9b' not found"}},
        )
    )
    provider = OpenAICompatibleLLMProvider(
        name="lm_studio",
        base_url="http://localhost:1234/v1",
        api_key_env="",
        default_model="qwen3.5-9b",
    )
    with pytest.raises(ProviderInvalidResponse) as exc:
        await provider.complete(system="s", user="u")

    assert exc.value.provider == "lm_studio"
    assert "400" in exc.value.message  # Status bleibt (kein Inhalt)
    # Body-Snippet darf NICHT mehr durchsickern:
    assert "Model 'qwen3.5-9b' not found" not in exc.value.message
