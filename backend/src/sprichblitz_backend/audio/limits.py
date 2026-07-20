from __future__ import annotations

from fastapi import HTTPException, status

# OpenAI-Whisper-Limit: 25 MB / 60 s. Wir spiegeln das als Backend-Grenze
# für alle Modi, damit ein Fallback-Wechsel keine Format-Probleme erzeugt.
MAX_AUDIO_BYTES: int = 25 * 1024 * 1024
MAX_AUDIO_SECONDS: float = 60.0


class AudioTooLarge(HTTPException):
    def __init__(self, *, code: str, detail: str) -> None:
        super().__init__(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail={"error": detail, "code": code},
        )


def enforce_byte_limit(num_bytes: int) -> None:
    if num_bytes > MAX_AUDIO_BYTES:
        raise AudioTooLarge(
            code="audio_too_large",
            detail=f"Audio exceeds {MAX_AUDIO_BYTES} bytes",
        )


def enforce_duration_limit(seconds: float) -> None:
    if seconds > MAX_AUDIO_SECONDS:
        raise AudioTooLarge(
            code="audio_too_long",
            detail=f"Audio exceeds {MAX_AUDIO_SECONDS} seconds",
        )
