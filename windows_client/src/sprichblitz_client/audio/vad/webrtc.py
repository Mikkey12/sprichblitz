"""Optionale WebRTC-VAD-Implementierung.

Nutzt ``webrtcvad`` (vorkompiliertes Wheel nötig). Falls das Paket fehlt,
ist die Klasse importierbar, aber :pyattr:`AVAILABLE` ist ``False`` und
:meth:`WebRTCVAD.analyse` wirft :class:`RuntimeError`.

Default-VAD bleibt RMS – siehe :mod:`sprichblitz_client.audio.vad.rms`.
"""

from __future__ import annotations

import numpy as np

from .base import BaseVAD, VADResult

try:
    import webrtcvad as _webrtcvad  # type: ignore[import-not-found]

    AVAILABLE = True
except Exception:  # pragma: no cover - kein Wheel vorhanden
    _webrtcvad = None
    AVAILABLE = False


SUPPORTED_SAMPLE_RATES = (8000, 16000, 32000, 48000)
FRAME_MS = 30


class WebRTCVAD(BaseVAD):
    name = "webrtc"

    def __init__(self, aggressiveness: int = 2) -> None:
        if not AVAILABLE:
            self._vad = None
            return
        self._vad = _webrtcvad.Vad(aggressiveness)

    def analyse(
        self,
        samples: np.ndarray,
        sample_rate: int,
        min_speech_ratio: float,
    ) -> VADResult:
        if not AVAILABLE or self._vad is None:
            raise RuntimeError("webrtcvad-Paket nicht verfügbar")
        if sample_rate not in SUPPORTED_SAMPLE_RATES:
            raise ValueError(
                f"webrtcvad unterstützt nur {SUPPORTED_SAMPLE_RATES}, nicht {sample_rate}"
            )
        if samples.size == 0:
            return VADResult(speech_ratio=0.0, is_speech=False, backend=self.name)
        frame_size = int(sample_rate * FRAME_MS / 1000)
        n_frames = samples.size // frame_size
        if n_frames == 0:
            return VADResult(speech_ratio=0.0, is_speech=False, backend=self.name)
        pcm = samples.astype(np.int16, copy=False).tobytes()
        bytes_per_frame = frame_size * 2
        active = 0
        for i in range(n_frames):
            chunk = pcm[i * bytes_per_frame : (i + 1) * bytes_per_frame]
            if self._vad.is_speech(chunk, sample_rate):
                active += 1
        ratio = active / n_frames
        return VADResult(
            speech_ratio=ratio,
            is_speech=ratio >= min_speech_ratio,
            backend=self.name,
        )
