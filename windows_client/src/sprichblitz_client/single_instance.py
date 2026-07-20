"""Single-Instance-Lock.

Auf Windows via ``win32event.CreateMutex``. Auf anderen Plattformen
ein No-Op-Stub, damit Imports auch auf macOS-Dev funktionieren.
"""

from __future__ import annotations

import sys

MUTEX_NAME = "Global\\SprichblitzClientMutex"


class AlreadyRunningError(RuntimeError):
    """Wird geworfen, wenn bereits eine Instanz läuft."""


class SingleInstance:
    """Acquired auf ``__enter__``, freigegeben auf ``__exit__``."""

    def __init__(self, mutex_name: str = MUTEX_NAME) -> None:
        self._mutex_name = mutex_name
        self._handle: object | None = None

    def acquire(self) -> None:
        if sys.platform != "win32":
            # Auf macOS/Linux: kein Mutex, da Client dort nicht produktiv läuft.
            return
        try:
            import win32api  # type: ignore[import-not-found]
            import win32event  # type: ignore[import-not-found]
            import winerror  # type: ignore[import-not-found]
        except ImportError as exc:  # pragma: no cover - nur auf Win relevant
            raise RuntimeError("pywin32 nicht installiert") from exc

        self._handle = win32event.CreateMutex(None, False, self._mutex_name)
        if win32api.GetLastError() == winerror.ERROR_ALREADY_EXISTS:
            raise AlreadyRunningError("Sprichblitz läuft bereits.")

    def release(self) -> None:
        if self._handle is None:
            return
        try:
            import win32api  # type: ignore[import-not-found]

            win32api.CloseHandle(self._handle)
        except Exception:  # pragma: no cover
            pass
        self._handle = None

    def __enter__(self) -> SingleInstance:
        self.acquire()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.release()
