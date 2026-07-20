from __future__ import annotations

import io
import subprocess
import wave
from collections.abc import Callable

import pytest
from fastapi import HTTPException

from sprichblitz_backend.audio.limits import MAX_AUDIO_BYTES
from sprichblitz_backend.audio.normalizer import (
    TARGET_CHANNELS,
    TARGET_SAMPLE_RATE,
    NormalizedAudio,
    _decode_to_pcm_bounded,
    normalize_to_pcm16k_mono,
)


def _read_wav(buf: bytes) -> tuple[int, int, int]:
    """Returns (channels, sampwidth, framerate) from a WAV byte string."""
    with wave.open(io.BytesIO(buf), "rb") as w:
        return w.getnchannels(), w.getsampwidth(), w.getframerate()


@pytest.mark.asyncio
async def test_normalize_passthrough_16k_mono(audio_16k_wav: bytes) -> None:
    out = await normalize_to_pcm16k_mono(audio_16k_wav, format_hint="wav")
    assert isinstance(out, NormalizedAudio)
    assert out.sample_rate == TARGET_SAMPLE_RATE
    assert out.channels == TARGET_CHANNELS

    channels, sampwidth, framerate = _read_wav(out.pcm_wav_bytes)
    assert channels == 1
    assert sampwidth == 2
    assert framerate == 16_000


@pytest.mark.asyncio
async def test_normalize_resamples_8k_to_16k(audio_8k_wav: bytes) -> None:
    out = await normalize_to_pcm16k_mono(audio_8k_wav, format_hint="wav")
    _, _, framerate = _read_wav(out.pcm_wav_bytes)
    assert framerate == 16_000
    # Duration sollte ~ Original-Dauer entsprechen (synth fixture: 2.0 s).
    assert 1.5 < out.duration_seconds < 2.5


@pytest.mark.asyncio
async def test_normalize_rejects_oversized_input() -> None:
    big = b"\x00" * (MAX_AUDIO_BYTES + 1)
    with pytest.raises(HTTPException) as exc:
        await normalize_to_pcm16k_mono(big, format_hint="wav")
    # FastAPI HTTPException mit status_code 413
    assert getattr(exc.value, "status_code", None) == 413


@pytest.mark.asyncio
async def test_normalize_rejects_too_long_audio(
    make_wav_bytes: Callable[..., bytes],
) -> None:
    long_wav = make_wav_bytes(sample_rate=16_000, duration_s=61.0)
    with pytest.raises(HTTPException) as exc:
        await normalize_to_pcm16k_mono(long_wav, format_hint="wav")
    assert getattr(exc.value, "status_code", None) == 413


def test_ffmpeg_decode_is_time_output_and_thread_bounded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[list[str]] = []

    def _run(command, **kwargs):  # noqa: ANN001,ANN003
        captured.append(command)
        assert kwargs["timeout"] == 15.0
        return subprocess.CompletedProcess(command, 0, stdout=b"\x00" * 3200, stderr=b"")

    monkeypatch.setattr(subprocess, "run", _run)
    assert len(_decode_to_pcm_bounded(b"audio", "m4a")) == 3200

    command = captured[0]
    assert command[command.index("-threads") + 1] == "1"
    assert command[command.index("-t") + 1] == "61.0"
    assert command[command.index("-ac") + 1] == "1"
    assert command[command.index("-ar") + 1] == "16000"
    assert command[command.index("-f") + 1] == "mov"
    assert command[-3:] == ["-f", "s16le", "pipe:1"]


def test_ffmpeg_timeout_returns_sanitized_422(monkeypatch: pytest.MonkeyPatch) -> None:
    def _run(*args, **kwargs):  # noqa: ANN002,ANN003
        raise subprocess.TimeoutExpired(cmd="ffmpeg", timeout=15.0)

    monkeypatch.setattr(subprocess, "run", _run)
    with pytest.raises(HTTPException) as exc:
        _decode_to_pcm_bounded(b"audio", None)
    assert getattr(exc.value, "status_code", None) == 422
    assert exc.value.detail["code"] == "audio_decode_timeout"


def test_ffmpeg_error_does_not_return_stderr(monkeypatch: pytest.MonkeyPatch) -> None:
    secret = b"container metadata must not be returned"

    def _run(command, **kwargs):  # noqa: ANN001,ANN003
        return subprocess.CompletedProcess(command, 1, stdout=b"", stderr=secret)

    monkeypatch.setattr(subprocess, "run", _run)
    with pytest.raises(HTTPException) as exc:
        _decode_to_pcm_bounded(b"audio", "wav")
    assert getattr(exc.value, "status_code", None) == 422
    assert exc.value.detail["code"] == "audio_invalid"
    assert secret.decode() not in str(exc.value.detail)
