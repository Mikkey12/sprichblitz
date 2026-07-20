from __future__ import annotations

import numpy as np

from sprichblitz_client.audio.vad.rms import RMSVAD, rms_dbfs

SAMPLE_RATE = 16000


def _silence(seconds: float) -> np.ndarray:
    return np.zeros(int(seconds * SAMPLE_RATE), dtype=np.int16)


def _sine(seconds: float, freq: float = 440.0, amplitude: float = 0.5) -> np.ndarray:
    n = int(seconds * SAMPLE_RATE)
    t = np.arange(n) / SAMPLE_RATE
    wave = np.sin(2 * np.pi * freq * t) * amplitude
    return (wave * 32767).astype(np.int16)


def test_rms_dbfs_silence_is_minus_infinity() -> None:
    assert rms_dbfs(_silence(0.05)) == float("-inf")


def test_rms_dbfs_full_scale_is_near_zero() -> None:
    full_scale = (np.ones(SAMPLE_RATE, dtype=np.int16) * 32767).astype(np.int16)
    assert -1.0 < rms_dbfs(full_scale) < 0.5


def test_rmsvad_marks_silence_as_no_speech() -> None:
    vad = RMSVAD(threshold_dbfs=-40.0)
    result = vad.analyse(_silence(2.0), SAMPLE_RATE, min_speech_ratio=0.05)
    assert result.is_speech is False
    assert result.speech_ratio == 0.0
    assert result.backend == "rms"


def test_rmsvad_marks_loud_sine_as_speech() -> None:
    vad = RMSVAD(threshold_dbfs=-40.0)
    result = vad.analyse(_sine(2.0, amplitude=0.3), SAMPLE_RATE, min_speech_ratio=0.05)
    assert result.is_speech is True
    assert result.speech_ratio > 0.5


def test_rmsvad_threshold_decides_borderline_quiet_signal() -> None:
    # Sehr leise Sinuswelle: bei -40 dBFS Schwelle nicht als Sprache,
    # bei -60 dBFS schon.
    quiet = _sine(2.0, amplitude=0.005)
    permissive = RMSVAD(threshold_dbfs=-60.0).analyse(quiet, SAMPLE_RATE, 0.05)
    strict = RMSVAD(threshold_dbfs=-40.0).analyse(quiet, SAMPLE_RATE, 0.05)
    assert permissive.is_speech is True
    assert strict.is_speech is False


def test_rmsvad_handles_empty_input() -> None:
    vad = RMSVAD()
    result = vad.analyse(np.zeros(0, dtype=np.int16), SAMPLE_RATE, min_speech_ratio=0.05)
    assert result.is_speech is False
    assert result.speech_ratio == 0.0
