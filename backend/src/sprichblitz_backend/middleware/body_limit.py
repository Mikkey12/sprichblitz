"""Frühes, streamendes Request-Body-Limit vor FastAPI/Pydantic/Multipart."""

from __future__ import annotations

import json

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from ..audio.limits import MAX_AUDIO_BYTES

AUDIO_PATHS = frozenset({"/full", "/transcribe"})
BODY_METHODS = frozenset({"POST", "PUT", "PATCH"})

# Multipart-Grenze gilt für den gesamten HTTP-Body. Das eigentliche Audio wird
# nach dem Parsen weiterhin exakt gegen MAX_AUDIO_BYTES geprüft.
MAX_MULTIPART_OVERHEAD_BYTES = 64 * 1024
MAX_STANDARD_BODY_BYTES = 256 * 1024


def _parse_content_length(scope: Scope) -> int | None:
    for key, value in scope.get("headers", []):
        if key.lower() != b"content-length":
            continue
        try:
            parsed = int(value)
        except ValueError:
            return None
        return parsed if parsed >= 0 else None
    return None


def _request_limit(scope: Scope) -> tuple[int, bool, str] | None:
    """Return ``(bytes, require_content_length, error_code)`` for this request."""
    if scope.get("method", "").upper() not in BODY_METHODS:
        return None
    if scope.get("path") in AUDIO_PATHS:
        return (
            MAX_AUDIO_BYTES + MAX_MULTIPART_OVERHEAD_BYTES,
            True,
            "audio_too_large",
        )
    return MAX_STANDARD_BODY_BYTES, False, "request_too_large"


async def _send_error(send: Send, status: int, error: str, code: str) -> None:
    body = json.dumps({"error": error, "code": code}, separators=(",", ":")).encode()
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode()),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})


class RequestBodyLimitMiddleware:
    """Reject oversized bodies before route auth, JSON or multipart parsing.

    Audio uploads require Content-Length because the multipart parser may spool
    unknown-length data before the application sees the file. Other bodies may
    be streamed/chunked, but the wrapped ``receive`` enforces the cumulative
    byte limit even when Content-Length is missing or dishonest.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        rule = _request_limit(scope)
        if rule is None:
            await self.app(scope, receive, send)
            return

        limit, require_length, error_code = rule
        content_length = _parse_content_length(scope)
        if require_length and content_length is None:
            await _send_error(
                send,
                411,
                "Content-Length header required for audio uploads",
                "length_required",
            )
            return
        if content_length is not None and content_length > limit:
            await _send_error(send, 413, f"Request body exceeds {limit} bytes", error_code)
            return

        received = 0
        response_started = False
        exceeded = False

        async def limited_receive() -> Message:
            nonlocal exceeded, received
            if exceeded:
                return {"type": "http.request", "body": b"", "more_body": False}
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > limit:
                    # FastAPI wandelt Exceptions aus receive() beim JSON-Parsing
                    # selbst in 400 um. Stattdessen Body kontrolliert beenden und
                    # dessen Downstream-Response unten durch unsere 413 ersetzen.
                    exceeded = True
                    return {"type": "http.request", "body": b"", "more_body": False}
            return message

        async def tracked_send(message: Message) -> None:
            nonlocal response_started
            if exceeded:
                return
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        await self.app(scope, limited_receive, tracked_send)
        if exceeded:
            # FastAPI liest die hier betroffenen Request-Bodies vor dem
            # Response-Start. Ein zukünftiger Streaming-Endpoint darf nicht mit
            # einer zweiten Response korrumpiert werden.
            if response_started:
                raise RuntimeError("Request body limit exceeded after response start")
            await _send_error(send, 413, f"Request body exceeds {limit} bytes", error_code)
