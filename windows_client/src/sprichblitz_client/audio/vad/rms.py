"""RMS-Energy-Threshold-VAD.

Berechnet pro ~30 ms Frame den RMS-Pegel in dBFS und zählt den Anteil
Frames, deren Pegel über der Schwelle liegt. Liegt dieser Anteil
unterhalb von ``min_speech_ratio`` (default 5 %), gilt die Aufnahme als
Stille.

Pflichtmodul – läuft ohne C-Compiler.
"""

from __future__ import annotations

import numpy as np

from .base import BaseVAD, VADResult

INT16_MAX = 32768.0
FRAME_MS = 30


def rms_dbfs(frame: np.ndarray) -> float:
    """RMS in dBFS für ein int16-Frame; -inf bei Stille."""
    if frame.size == 0:
        return float("-inf")
    arr = frame.astype(np.float32) / INT16_MAX
    rms = float(np.sqrt(np.mean(arr * arr)))
    if rms <= 0.0:
        return float("-inf")
    return 20.0 * float(np.log10(rms))


class RMSVAD(BaseVAD):
    name = "rms"

    def __init__(self, threshold_dbfs: float = -40.0) -> None:
        self.threshold_dbfs = threshold_dbfs

    def analyse(
        self,
        samples: np.ndarray,
        sample_rate: int,
        min_speech_ratio: float,
    ) -> VADResult:
        if samples.size == 0:
            return VADResult(speech_ratio=0.0, is_speech=False, backend=self.name)
        frame_size = max(1, int(sample_rate * FRAME_MS / 1000))
        n_frames = samples.size // frame_size
        if n_frames == 0:
            # Sehr kurze Aufnahme: gesamte Aufnahme als ein Frame werten.
            level = rms_dbfs(samples)
            ratio = 1.0 if level >= self.threshold_dbfs else 0.0
            return VADResult(
                speech_ratio=ratio,
                is_speech=ratio >= min_speech_ratio,
                backend=self.name,
            )
        active = 0
        for i in range(n_frames):
            frame = samples[i * frame_size : (i + 1) * frame_size]
            if rms_dbfs(frame) >= self.threshold_dbfs:
                active += 1
        ratio = active / n_frames
        return VADResult(
            speech_ratio=ratio,
            is_speech=ratio >= min_speech_ratio,
            backend=self.name,
        )
