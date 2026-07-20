"""Hard-Timeout für laufende Aufnahmen.

Whisper-Cloud-Limit ist 60 s; wir cutten 1 s früher, um Race-Conditions
zwischen Aufnahme-Stop und HTTP-Upload zu vermeiden.
"""

from __future__ import annotations

import threading
from collections.abc import Callable

HARD_TIMEOUT_SECONDS = 59.0


class RecordingTimeout:
    """Wrapper um :class:`threading.Timer` mit Cancel-Idempotenz."""

    def __init__(
        self,
        on_timeout: Callable[[], None],
        seconds: float = HARD_TIMEOUT_SECONDS,
    ) -> None:
        self._on_timeout = on_timeout
        self._seconds = seconds
        self._timer: threading.Timer | None = None

    def start(self) -> None:
        self.cancel()
        self._timer = threading.Timer(self._seconds, self._on_timeout)
        self._timer.daemon = True
        self._timer.start()

    def cancel(self) -> None:
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None
