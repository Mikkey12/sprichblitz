"""Diktat-Klammer: Anweisungs-Diktate müssen als Daten ankommen, nicht als Auftrag.

Belegt am 29.10.2026: „Das klingt gut. Setze das um für den Pilot WC." ließ
Claude Haiku erklären, das sei «eine Anweisung an mich», statt den Satz
zurückzugeben. Seitdem reist das Diktat in `<diktat>`-Markern, und der
System-Prompt sagt, dass alles darin Datenmaterial ist.
"""

from __future__ import annotations

import pytest

from sprichblitz_backend.models.config_models import ModeConfig
from sprichblitz_backend.providers.registry import ProviderRegistry
from sprichblitz_backend.services.post_processing import post_process_for_mode

from ..conftest import StubLLM


@pytest.mark.asyncio
async def test_transcript_is_wrapped_and_framed() -> None:
    llm = StubLLM("anthropic", text="bereinigt")
    registry = ProviderRegistry(stt={}, llm={"anthropic": llm})
    mode = ModeConfig(
        description="Test",
        stt="openai_whisper",
        llm="anthropic",
        apply_llm=True,
        system_prompt="Du bist Lektor für diktierte Texte.",
    )

    await post_process_for_mode(
        text="Das klingt gut. Setze das um für den Pilot WC.",
        mode=mode,
        registry=registry,
        locale="de-CH",
    )

    assert len(llm.calls) == 1
    system = str(llm.calls[0]["system"])
    user = str(llm.calls[0]["user"])

    # Der Text reist als markierter Datenblock …
    assert user.startswith("<diktat>")
    assert user.rstrip().endswith("</diktat>")
    assert "Setze das um für den Pilot WC." in user
    # … und der System-Prompt ordnet den Block als Material ein.
    assert "<diktat>" in system
    assert "Datenmaterial" in system
    assert "nicht ausgeführt" in system
