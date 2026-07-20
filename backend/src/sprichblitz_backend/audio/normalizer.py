from __future__ import annotations

import asyncio
import io
import subprocess
import threading
import wave
from dataclasses import dataclass

from fastapi import HTTPException, status

from .limits import MAX_AUDIO_SECONDS, enforce_byte_limit, enforce_duration_limit

TARGET_SAMPLE_RATE: int = 16_000
TARGET_CHANNELS: int = 1
TARGET_SAMPWIDTH: int = 2  # 16-bit PCM
_DECODE_MARGIN_SECONDS: float = 1.0
_DECODE_TIMEOUT_SECONDS: float = 15.0
_MAX_FFMPEG_ALLOC_BYTES: int = 64 * 1024 * 1024
_MAX_CONCURRENT_DECODES: int = 2
_DECODE_GATE = threading.BoundedSemaphore(_MAX_CONCURRENT_DECODES)

_FORMAT_DEMUXERS = {
    "wav": "wav",
    "mp3": "mp3",
    "m4a": "mov",
    "mp4": "mov",
    "aac": "aac",
    "ogg": "ogg",
    "webm": "matroska",
}


@dataclass(frozen=True)
class NormalizedAudio:
    pcm_wav_bytes: bytes
    sample_rate: int
    channels: int
    duration_seconds: float


def _input_format_args(format_hint: str | None) -> list[str]:
    fmt = format_hint.lower().lstrip(".") if format_hint else None
    demuxer = _FORMAT_DEMUXERS.get(fmt or "")
    return ["-f", demuxer] if demuxer else []


def _decode_to_pcm_bounded(raw: bytes, format_hint: str | None) -> bytes:
    """Decode directly to bounded 16-kHz mono PCM through ffmpeg.

    The previous pydub/scipy path decoded and resampled the complete input before
    checking duration. Here ffmpeg caps decoded time, output format, allocation
    size, threads and wall time before Python receives PCM bytes.
    """
    decode_seconds = MAX_AUDIO_SECONDS + _DECODE_MARGIN_SECONDS
    command = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-nostdin",
        "-max_alloc",
        str(_MAX_FFMPEG_ALLOC_BYTES),
        "-threads",
        "1",
        "-probesize",
        "5M",
        "-analyzeduration",
        "5M",
        *_input_format_args(format_hint),
        "-i",
        "pipe:0",
        "-map_metadata",
        "-1",
        "-vn",
        "-sn",
        "-dn",
        "-t",
        str(decode_seconds),
        "-ac",
        str(TARGET_CHANNELS),
        "-ar",
        str(TARGET_SAMPLE_RATE),
        "-acodec",
        "pcm_s16le",
        "-f",
        "s16le",
        "pipe:1",
    ]
    try:
        completed = subprocess.run(
            command,
            input=raw,
            capture_output=True,
            check=False,
            timeout=_DECODE_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"error": "Audio decoding timed out", "code": "audio_decode_timeout"},
        ) from exc
    except FileNotFoundError as exc:  # Deploymentfehler, kein Clientfehler.
        raise RuntimeError("ffmpeg executable not found") from exc

    if completed.returncode != 0:
        # stderr kann Dateinamen/Container-Metadaten enthalten und wird deshalb
        # weder geloggt noch an den Client zurückgegeben.
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"error": "Unsupported or invalid audio", "code": "audio_invalid"},
        )
    return completed.stdout


def _pcm_to_wav_bytes(pcm: bytes) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(TARGET_CHANNELS)
        w.setsampwidth(TARGET_SAMPWIDTH)
        w.setframerate(TARGET_SAMPLE_RATE)
        w.writeframes(pcm)
    return buf.getvalue()


def _normalize_sync(raw: bytes, format_hint: str | None) -> NormalizedAudio:
    enforce_byte_limit(len(raw))

    with _DECODE_GATE:
        pcm = _decode_to_pcm_bounded(raw, format_hint)

    bytes_per_second = TARGET_SAMPLE_RATE * TARGET_CHANNELS * TARGET_SAMPWIDTH
    duration = len(pcm) / float(bytes_per_second)
    enforce_duration_limit(duration)

    wav_bytes = _pcm_to_wav_bytes(pcm)
    return NormalizedAudio(
        pcm_wav_bytes=wav_bytes,
        sample_rate=TARGET_SAMPLE_RATE,
        channels=TARGET_CHANNELS,
        duration_seconds=duration,
    )


async def normalize_to_pcm16k_mono(
    raw: bytes,
    format_hint: str | None = None,
) -> NormalizedAudio:
    """Normalize ``raw`` audio to 16 kHz mono 16-bit PCM, wrapped as WAV.

    All CPU-heavy work runs in ``asyncio.to_thread`` so the FastAPI event
    loop stays responsive. Raises ``AudioTooLarge`` (HTTP 413) on size or
    duration overruns.
    """
    return await asyncio.to_thread(_normalize_sync, raw, format_hint)
