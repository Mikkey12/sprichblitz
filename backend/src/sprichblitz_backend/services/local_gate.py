"""Prozessweites Gate für lokale Inferenz (WhisperKit / LM Studio) – Etappe 5.

Eine ``asyncio.Semaphore`` serialisiert die **echt-async** lokalen Provider-Calls
(httpx.AsyncClient/AsyncAnthropic) im awaitenden Kontext. Acquire/Release pro
**einzelnem** Call (nicht über den Request gehalten, nicht verschachtelt) →
``Semaphore(1)`` ohne Deadlock. Acquire mit Timeout → :class:`LocalGateTimeout`
(503). Cloud-Calls laufen NICHT durchs Gate.

Permit-Leak-Sicherheit: ``self._sem.release()`` steht ausschliesslich im
``finally`` des **yield**-Blocks, der nur nach erfolgreichem Acquire erreicht
wird. Ein Acquire-Timeout wirft, bevor dieser Block beginnt → es wird nie
fälschlich released, und (Python 3.11+ ``wait_for``) bei Acquire-im-Timeout-Race
liefert ``wait_for`` das Permit zurück statt es zu verlieren.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from ..util.errors import LocalGateTimeout


class LocalInferenceGate:
    def __init__(self, concurrency: int = 1, acquire_timeout_s: float = 30.0) -> None:
        self._sem = asyncio.Semaphore(max(1, concurrency))
        self._timeout = acquire_timeout_s

    @asynccontextmanager
    async def slot(self) -> AsyncIterator[None]:
        try:
            await asyncio.wait_for(self._sem.acquire(), timeout=self._timeout)
        except TimeoutError as exc:
            raise LocalGateTimeout() from exc
        try:
            yield
        finally:
            self._sem.release()
