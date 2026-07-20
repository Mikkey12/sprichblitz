from __future__ import annotations

from types import SimpleNamespace

import pytest
from loguru import logger

from sprichblitz_backend.providers.llm.gemini import GeminiProvider


@pytest.mark.asyncio
async def test_complete_uses_system_instruction(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "k")

    captured: dict = {}

    async def fake_generate(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(
            text="hallo gemini",
            usage_metadata=SimpleNamespace(prompt_token_count=3, candidates_token_count=4),
        )

    fake_models = SimpleNamespace(
        generate_content=fake_generate,
        list=lambda: iter([]),  # not used in this test
    )
    fake_aio = SimpleNamespace(models=fake_models)
    fake_client = SimpleNamespace(aio=fake_aio)

    provider = GeminiProvider(
        name="gemini",
        api_key_env="GEMINI_API_KEY",
        default_model="gemini-2.5-flash",
    )
    monkeypatch.setattr(provider, "_client", lambda *a, **k: fake_client)

    result = await provider.complete(system="sys", user="u")

    assert result.text == "hallo gemini"
    assert result.model == "gemini-2.5-flash"
    assert captured["model"] == "gemini-2.5-flash"
    assert captured["contents"] == "u"
    cfg = captured["config"]
    assert cfg.system_instruction == "sys"


@pytest.mark.asyncio
async def test_complete_ignores_prefill_silently(monkeypatch: pytest.MonkeyPatch) -> None:
    """Gemini supports kein Prefill – Aufruf darf nicht crashen."""
    monkeypatch.setenv("GEMINI_API_KEY", "k")

    async def fake_generate(**kwargs):
        return SimpleNamespace(text="x", usage_metadata=None)

    fake_client = SimpleNamespace(
        aio=SimpleNamespace(models=SimpleNamespace(generate_content=fake_generate))
    )
    provider = GeminiProvider(
        name="gemini",
        api_key_env="GEMINI_API_KEY",
        default_model="gemini-2.5-flash",
    )
    monkeypatch.setattr(provider, "_client", lambda *a, **k: fake_client)

    result = await provider.complete(system="s", user="u", prefill="Lieber Alex, ")
    # Prefill darf nicht in die Response durchgereicht werden für Gemini
    # (anders als bei Anthropic), weil das Modell nicht von dort weiter-
    # generiert hat.
    assert result.text == "x"


@pytest.mark.asyncio
async def test_complete_error_does_not_leak_exception_detail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """P1-2-Mechanik: str(exc) kann den Upstream-Body (inkl. Request-Inhalte)
    enthalten – darf NICHT in die ProviderError-Message (geht an Client + Logs)."""
    from sprichblitz_backend.util.errors import ProviderUnavailable

    monkeypatch.setenv("GEMINI_API_KEY", "k")

    secret = "das geheime diktat transkript"

    async def boom(**kwargs):
        raise RuntimeError(f"response body echoed: {secret}")

    fake_client = SimpleNamespace(
        aio=SimpleNamespace(models=SimpleNamespace(generate_content=boom))
    )
    provider = GeminiProvider(
        name="gemini",
        api_key_env="GEMINI_API_KEY",
        default_model="gemini-2.5-flash",
    )
    monkeypatch.setattr(provider, "_client", lambda *a, **k: fake_client)

    logged: list[str] = []
    sink_id = logger.add(lambda message: logged.append(str(message)), level="DEBUG")
    try:
        with pytest.raises(ProviderUnavailable) as exc:
            await provider.complete(system="s", user=secret)
    finally:
        logger.remove(sink_id)
    assert exc.value.provider == "gemini"
    assert "RuntimeError" in exc.value.message  # Klasse bleibt (kein Inhalt)
    assert secret not in exc.value.message.lower()
    assert secret not in "".join(logged).lower()
