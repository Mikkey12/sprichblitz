from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from sprichblitz_backend.app import create_app
from sprichblitz_backend.providers.registry import ProviderRegistry

from ..conftest import StubLLM, StubSTT, _minimal_config


@pytest.fixture
def eszett_client(db_engine, key_vault):
    registry = ProviderRegistry(
        stt={
            "openai_whisper": StubSTT(
                "openai_whisper", text="Die Straße ist groß und weiß."
            ),
            "lm_studio_whisper": StubSTT("lm_studio_whisper", text="lokal"),
        },
        llm={"anthropic": StubLLM("anthropic", text="Strasse bleibt.")},
    )
    app = create_app(_minimal_config(), registry=registry, db_engine=db_engine, key_vault=key_vault)
    with TestClient(app) as c:
        yield c


def test_full_with_swiss_locale_replaces_eszett(
    eszett_client: TestClient, audio_16k_wav: bytes, auth_headers: dict[str, str]
) -> None:
    res = eszett_client.post(
        "/full",
        headers=auth_headers,
        files={"file": ("h.wav", audio_16k_wav, "audio/wav")},
        data={"mode": "exact_de", "locale": "de-CH"},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    # exact_de = STT-only → raw == final, beide normalisiert.
    assert "ß" not in body["raw_text"]
    assert body["raw_text"] == "Die Strasse ist gross und weiss."
    assert body["final_text"] == body["raw_text"]


def test_full_without_locale_keeps_eszett(
    eszett_client: TestClient, audio_16k_wav: bytes, auth_headers: dict[str, str]
) -> None:
    res = eszett_client.post(
        "/full",
        headers=auth_headers,
        files={"file": ("h.wav", audio_16k_wav, "audio/wav")},
        data={"mode": "exact_de"},
    )
    assert res.status_code == 200, res.text
    assert "ß" in res.json()["raw_text"]


def test_full_with_de_de_locale_keeps_eszett(
    eszett_client: TestClient, audio_16k_wav: bytes, auth_headers: dict[str, str]
) -> None:
    res = eszett_client.post(
        "/full",
        headers=auth_headers,
        files={"file": ("h.wav", audio_16k_wav, "audio/wav")},
        data={"mode": "exact_de", "locale": "de-DE"},
    )
    assert res.status_code == 200, res.text
    assert "ß" in res.json()["raw_text"]
