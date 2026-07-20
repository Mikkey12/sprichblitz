from __future__ import annotations

import inspect

import httpx
import pytest
import respx

from sprichblitz_client.backend.client import BackendClient
from sprichblitz_client.models import BackendError, Mode

BASE_URL = "https://sprichblitz.test"
WAV_BYTES = b"RIFF\x24\x00\x00\x00WAVEfmt "
TOKEN = "secret-token"


def _make_client() -> BackendClient:
    return BackendClient(BASE_URL, TOKEN)


@respx.mock
def test_full_success_returns_parsed_result() -> None:
    respx.post(f"{BASE_URL}/full").mock(
        return_value=httpx.Response(
            200,
            json={
                "mode": "exact_de",
                "raw_text": "Hallo Welt",
                "final_text": "Hallo Welt",
                "stt_provider": "openai_whisper",
                "stt_model": "whisper-1",
                "llm_provider": None,
                "llm_model": None,
                "used_fallback": False,
                "total_duration_ms": 1234,
            },
        )
    )

    with _make_client() as client:
        result = client.full(WAV_BYTES, Mode.exact_de)

    assert result.final_text == "Hallo Welt"
    assert result.stt_provider == "openai_whisper"
    assert result.used_fallback is False


@respx.mock
def test_full_sets_bearer_header_and_multipart_field() -> None:
    route = respx.post(f"{BASE_URL}/full").mock(
        return_value=httpx.Response(
            200,
            json={
                "mode": "exact_swiss",
                "raw_text": "x",
                "final_text": "x",
                "stt_provider": "lm_studio_whisper",
                "stt_model": "whisper-large-v3-turbo",
                "used_fallback": True,
                "total_duration_ms": 1,
            },
        )
    )
    with _make_client() as client:
        client.full(WAV_BYTES, Mode.exact_swiss)

    request = route.calls.last.request
    assert request.headers["authorization"] == f"Bearer {TOKEN}"
    body = request.content
    assert b'name="mode"' in body
    assert b"exact_swiss" in body
    assert b'name="file"' in body
    assert b"recording.wav" in body


@respx.mock
def test_full_maps_401_to_auth_failed() -> None:
    respx.post(f"{BASE_URL}/full").mock(return_value=httpx.Response(401, json={}))
    with _make_client() as client, pytest.raises(BackendError) as ei:
        client.full(WAV_BYTES, Mode.exact_de)
    assert ei.value.code == "auth_failed"
    assert ei.value.http_status == 401


@respx.mock
def test_full_maps_error_response_body_to_provider_field() -> None:
    respx.post(f"{BASE_URL}/full").mock(
        return_value=httpx.Response(
            502,
            json={
                "error": "OpenAI Whisper antwortet nicht",
                "code": "provider_unavailable",
                "provider": "openai_whisper",
            },
        )
    )
    with _make_client() as client, pytest.raises(BackendError) as ei:
        client.full(WAV_BYTES, Mode.exact_de)
    err = ei.value
    assert err.code == "provider_unavailable"
    assert err.provider == "openai_whisper"
    assert err.http_status == 502


@respx.mock
def test_full_maps_connection_error() -> None:
    respx.post(f"{BASE_URL}/full").mock(side_effect=httpx.ConnectError("nope"))
    with _make_client() as client, pytest.raises(BackendError) as ei:
        client.full(WAV_BYTES, Mode.exact_de)
    assert ei.value.code == "connection_error"


@respx.mock
def test_full_maps_timeout() -> None:
    respx.post(f"{BASE_URL}/full").mock(side_effect=httpx.ReadTimeout("slow"))
    with _make_client() as client, pytest.raises(BackendError) as ei:
        client.full(WAV_BYTES, Mode.exact_de)
    assert ei.value.code == "timeout"


def test_default_timeout_is_60_seconds() -> None:
    """Langsame lokale Inferenz erhält ein 60-Sekunden-Lesefenster."""
    client = _make_client()
    try:
        # Greift auf das interne httpx.Client-Objekt zu, das BackendClient hält.
        timeout = client._client.timeout  # type: ignore[attr-defined]
        assert timeout.read == 60.0
    finally:
        client.close()


@respx.mock
def test_full_sends_only_mode_no_provider_overrides() -> None:
    # d4: keine per-Request-STT/LLM-Overrides mehr – Felder weg (Signatur + Body)
    # UND der Kern produziert weiter (Response wird geparst).
    params = set(inspect.signature(BackendClient.full).parameters)
    assert not ({"stt", "llm", "llm_model"} & params)
    route = respx.post(f"{BASE_URL}/full").mock(
        return_value=httpx.Response(
            200,
            json={
                "mode": "exact_de",
                "raw_text": "Hallo",
                "final_text": "Hallo",
                "stt_provider": "openai_whisper",
                "stt_model": "whisper-1",
                "llm_provider": None,
                "llm_model": None,
                "used_fallback": False,
                "total_duration_ms": 12,
            },
        )
    )
    with _make_client() as client:
        result = client.full(WAV_BYTES, Mode.exact_de)
    body = route.calls.last.request.content
    assert b'name="mode"' in body and b'name="file"' in body
    for field in (b'name="stt"', b'name="llm"', b'name="llm_model"'):
        assert field not in body
    assert result.final_text == "Hallo"  # Kern produziert weiter


@respx.mock
def test_create_console_session_returns_code() -> None:
    route = respx.post(f"{BASE_URL}/console/session").mock(
        return_value=httpx.Response(200, json={"code": "BOOT-CODE-XYZ", "expires_in": 60})
    )
    with _make_client() as client:
        code = client.create_console_session()
    assert code == "BOOT-CODE-XYZ"
    assert route.calls.last.request.headers["authorization"] == f"Bearer {TOKEN}"


@respx.mock
def test_console_nonce_is_sent() -> None:
    route = respx.post(f"{BASE_URL}/console/session").mock(
        return_value=httpx.Response(200, json={"code": "CODE", "expires_in": 60})
    )
    with BackendClient(BASE_URL, TOKEN) as client:
        assert client.create_console_session(boot_nonce="browser-nonce") == "CODE"

    headers = route.calls.last.request.headers
    assert headers["x-sb-boot-nonce"] == "browser-nonce"


@respx.mock
def test_create_console_session_maps_auth_error() -> None:
    respx.post(f"{BASE_URL}/console/session").mock(return_value=httpx.Response(401, json={}))
    with _make_client() as client, pytest.raises(BackendError) as ei:
        client.create_console_session()
    assert ei.value.code == "auth_failed"
    assert ei.value.http_status == 401


@respx.mock
def test_get_modes_preserves_arbitrary_mode_keys() -> None:
    respx.get(f"{BASE_URL}/me/modes").mock(
        return_value=httpx.Response(
            200,
            json=[
                {"mode_key": "exact_de", "display_name": "Deutsch exakt", "enabled": True},
                {"mode_key": "rage", "display_name": "Cool", "enabled": False},
                {"mode_key": "unknown_mode", "display_name": "X", "enabled": True},
            ],
        )
    )
    with _make_client() as client:
        modes = client.get_modes()
    assert set(modes) == {Mode.exact_de, Mode.rage, Mode("unknown_mode")}
    assert modes[Mode.exact_de].enabled is True
    assert modes[Mode.rage].enabled is False
    assert modes[Mode.rage].display_name == "Cool"
    assert modes[Mode("unknown_mode")].display_name == "X"


@respx.mock
def test_get_modes_maps_auth_error() -> None:
    respx.get(f"{BASE_URL}/me/modes").mock(return_value=httpx.Response(401, json={}))
    with _make_client() as client, pytest.raises(BackendError) as ei:
        client.get_modes()
    assert ei.value.code == "auth_failed"


@respx.mock
def test_get_me_returns_profile() -> None:
    respx.get(f"{BASE_URL}/me").mock(
        return_value=httpx.Response(
            200, json={"name": "admin", "processing_location": "online", "keys": {}}
        )
    )
    with _make_client() as client:
        me = client.get_me()
    assert me.name == "admin"
    assert me.processing_location == "online"


@respx.mock
def test_get_me_maps_auth_error() -> None:
    respx.get(f"{BASE_URL}/me").mock(return_value=httpx.Response(401, json={}))
    with _make_client() as client, pytest.raises(BackendError) as ei:
        client.get_me()
    assert ei.value.code == "auth_failed"
