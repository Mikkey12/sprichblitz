"""Audio-Capture: 16 kHz, Mono, 16-bit PCM, in-memory.

PortAudio (über sounddevice) macht das Resampling auf C-Ebene, daher
KEIN scipy im Client. Aufnahme landet als WAV-Bytes im RAM und wird
nach dem Senden verworfen.
"""

from __future__ import annotations

import io
import threading
import wave
from collections.abc import Callable

import numpy as np

SAMPLE_RATE = 16000
CHANNELS = 1
DTYPE = "int16"


def encode_wav(samples: np.ndarray, sample_rate: int = SAMPLE_RATE) -> bytes:
    """Schreibt ein int16-NumPy-Array als RIFF/WAV-Bytes."""
    if samples.dtype != np.int16:
        samples = samples.astype(np.int16, copy=False)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wav:
        wav.setnchannels(CHANNELS)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(samples.tobytes())
    return buf.getvalue()


class Recorder:
    """Streaming-Recorder mit in-memory-Puffer.

    Verwendet ``sounddevice.InputStream``. Ein eigener Lock schützt das
    Sammeln der Frames; ``stop()`` gibt das WAV-Bytes-Array zurück und
    leert intern den Puffer.
    """

    def __init__(
        self,
        sample_rate: int = SAMPLE_RATE,
        channels: int = CHANNELS,
        on_overflow: Callable[[], None] | None = None,
    ) -> None:
        self.sample_rate = sample_rate
        self.channels = channels
        self._on_overflow = on_overflow
        self._frames: list[np.ndarray] = []
        self._lock = threading.Lock()
        self._stream: object | None = None

    def _callback(self, indata, frames, time_info, status) -> None:  # noqa: D401, ANN001
        if status and self._on_overflow and getattr(status, "input_overflow", False):
            self._on_overflow()
        with self._lock:
            # Kopie speichern – sounddevice recycelt den Buffer.
            self._frames.append(indata.copy())

    def start(self) -> None:
        # Lazy-Import: sounddevice öffnet beim Import PortAudio, das wollen
        # wir auf macOS-Dev nur dann tun, wenn wirklich aufgenommen wird.
        import sounddevice as sd

        with self._lock:
            self._frames.clear()
        self._stream = sd.InputStream(
            samplerate=self.sample_rate,
            channels=self.channels,
            dtype=DTYPE,
            callback=self._callback,
        )
        self._stream.start()  # type: ignore[attr-defined]

    def stop(self) -> bytes:
        if self._stream is None:
            return encode_wav(np.zeros(0, dtype=np.int16), self.sample_rate)
        try:
            self._stream.stop()  # type: ignore[attr-defined]
            self._stream.close()  # type: ignore[attr-defined]
        finally:
            self._stream = None
        with self._lock:
            if not self._frames:
                samples = np.zeros(0, dtype=np.int16)
            else:
                samples = np.concatenate(self._frames, axis=0).reshape(-1)
            self._frames.clear()
        return encode_wav(samples, self.sample_rate)

    def is_running(self) -> bool:
        return self._stream is not None


def record_for_seconds(seconds: float) -> bytes:
    """Bequemer Helfer für Smoke-Tests: nimmt synchron N Sekunden auf."""
    import sounddevice as sd

    n_samples = int(seconds * SAMPLE_RATE)
    data = sd.rec(
        n_samples,
        samplerate=SAMPLE_RATE,
        channels=CHANNELS,
        dtype=DTYPE,
        blocking=True,
    )
    return encode_wav(np.asarray(data).reshape(-1), SAMPLE_RATE)
