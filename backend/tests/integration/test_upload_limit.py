from __future__ import annotations

from fastapi.testclient import TestClient

from sprichblitz_backend.audio.limits import MAX_AUDIO_BYTES
from sprichblitz_backend.middleware.body_limit import (
    MAX_MULTIPART_OVERHEAD_BYTES,
    MAX_STANDARD_BODY_BYTES,
)


def test_full_rejects_upload_without_content_length(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    # Chunked/streamed Body → httpx setzt kein Content-Length → Middleware 411,
    # bevor Starlette den Multipart-Body auf Disk spoolt / in RAM lädt.
    def _chunks():
        yield b"x" * 64

    res = client.post("/full", headers=auth_headers, content=_chunks())
    assert res.status_code == 411, res.text
    assert res.json()["code"] == "length_required"


def test_full_rejects_oversized_upload_via_content_length(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    # Der Request-Body darf zusätzlich zum Audio begrenzten Multipart-Overhead
    # enthalten. Ein angekündigtes Byte mehr wird vor dem Parsen abgewiesen.
    announced = MAX_AUDIO_BYTES + MAX_MULTIPART_OVERHEAD_BYTES + 1
    res = client.post(
        "/full",
        headers={
            **auth_headers,
            "Content-Type": "multipart/form-data; boundary=x",
            "Content-Length": str(announced),
        },
        content=b"--x--\r\n",
    )
    assert res.status_code == 413, res.text
    assert res.json()["code"] == "audio_too_large"


def test_oversized_json_is_rejected_before_auth(client: TestClient) -> None:
    body = b'{"ignored":"' + (b"x" * MAX_STANDARD_BODY_BYTES) + b'"}'
    res = client.post("/process", headers={"Content-Type": "application/json"}, content=body)
    assert res.status_code == 413, res.text
    assert res.json()["code"] == "request_too_large"
    assert res.headers["X-Content-Type-Options"] == "nosniff"


def test_chunked_json_is_bounded_without_content_length(client: TestClient) -> None:
    def _chunks():
        yield b'{"ignored":"'
        for _ in range(5):
            yield b"x" * (MAX_STANDARD_BODY_BYTES // 4)
        yield b'"}'

    res = client.post(
        "/process",
        headers={"Content-Type": "application/json"},
        content=_chunks(),
    )
    assert res.status_code == 413, res.text
    assert res.json()["code"] == "request_too_large"
    assert res.headers["X-Content-Type-Options"] == "nosniff"


def test_transcribe_normal_upload_passes_guard(
    client: TestClient, audio_16k_wav: bytes, auth_headers: dict[str, str]
) -> None:
    res = client.post(
        "/transcribe",
        headers=auth_headers,
        files={"file": ("h.wav", audio_16k_wav, "audio/wav")},
        data={"mode": "exact_de"},
    )
    assert res.status_code == 200, res.text
