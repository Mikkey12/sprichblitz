from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from loguru import logger

from sprichblitz_backend.providers.llm.anthropic import AnthropicProvider


def test_build_messages_without_prefill() -> None:
    msgs = AnthropicProvider.build_messages("hallo", None)
    assert msgs == [{"role": "user", "content": "hallo"}]


def test_build_messages_with_prefill_appends_assistant_role() -> None:
    msgs = AnthropicProvider.build_messages("hallo", "Lieber ")
    assert msgs == [
        {"role": "user", "content": "hallo"},
        {"role": "assistant", "content": "Lieber "},
    ]


@pytest.mark.asyncio
async def test_complete_passes_prefill_in_messages_and_prepends_to_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Kern-Verifikation: Anthropic-API bekommt Prefill als assistant-Message,
    und das Resultat enthält den Prefill voran."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    captured: dict = {}

    async def fake_create(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(
            content=[SimpleNamespace(text="Alex, ich melde mich bald.")],
            usage=SimpleNamespace(input_tokens=42, output_tokens=17),
        )

    fake_messages = SimpleNamespace(create=fake_create)
    fake_client = SimpleNamespace(messages=fake_messages, models=AsyncMock())

    provider = AnthropicProvider(
        name="anthropic",
        api_key_env="ANTHROPIC_API_KEY",
        default_model="claude-haiku-4-5-20251001",
    )
    monkeypatch.setattr(provider, "_client", lambda *a, **k: fake_client)

    result = await provider.complete(
        system="Schreibe sauber.",
        user="hallo alex, melde mich bald",
        prefill="Lieber Alex, ",
    )

    # Messages-Liste enthält genau den Prefill als assistant-Eintrag:
    assert captured["messages"] == [
        {"role": "user", "content": "hallo alex, melde mich bald"},
        {"role": "assistant", "content": "Lieber Alex, "},
    ]
    assert captured["system"] == "Schreibe sauber."
    assert captured["model"] == "claude-haiku-4-5-20251001"

    # Text-Resultat: Prefill + API-Antwort, damit der Client die ganze
    # Mail bekommt, nicht nur die Fortsetzung.
    assert result.text == "Lieber Alex, Alex, ich melde mich bald."
    assert result.provider == "anthropic"
    assert result.input_tokens == 42
    assert result.output_tokens == 17


@pytest.mark.asyncio
async def test_list_models_returns_documented_slugs() -> None:
    provider = AnthropicProvider(
        name="anthropic",
        api_key_env="ANTHROPIC_API_KEY",
        default_model="claude-haiku-4-5-20251001",
    )
    models = await provider.list_models()
    assert "claude-haiku-4-5-20251001" in models
    assert "claude-sonnet-4-6" in models
    assert "claude-opus-4-7" in models


@pytest.mark.asyncio
async def test_complete_maps_api_status_error_without_leaking_body(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """4xx muss auf ProviderInvalidResponse mappen (nicht 500-Generic) – aber
    P1-2-Mechanik: die Upstream-Message darf NICHT in die Exception-Message
    lecken (geht als `error` an Client + Logs; kann Request-Inhalte echoen)."""
    import anthropic
    import httpx

    from sprichblitz_backend.util.errors import ProviderInvalidResponse

    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")

    secret = "das geheime diktat transkript"
    body = {
        "type": "error",
        "error": {
            "type": "invalid_request_error",
            "message": f"Invalid request echoed: {secret}",
        },
    }
    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    response = httpx.Response(400, request=request, json=body)
    api_err = anthropic.BadRequestError(message="bad", response=response, body=body)

    async def boom(**kwargs):
        raise api_err

    fake_client = SimpleNamespace(messages=SimpleNamespace(create=boom))
    provider = AnthropicProvider(
        name="anthropic",
        api_key_env="ANTHROPIC_API_KEY",
        default_model="claude-haiku-4-5-20251001",
    )
    monkeypatch.setattr(provider, "_client", lambda *a, **k: fake_client)

    logged: list[str] = []
    sink_id = logger.add(lambda message: logged.append(str(message)), level="DEBUG")
    try:
        with pytest.raises(ProviderInvalidResponse) as exc:
            await provider.complete(system="s", user=secret)
    finally:
        logger.remove(sink_id)
    assert exc.value.provider == "anthropic"
    assert "400" in exc.value.message  # Status bleibt (kein Inhalt)
    assert secret not in exc.value.message.lower()
    assert secret not in "".join(logged).lower()
