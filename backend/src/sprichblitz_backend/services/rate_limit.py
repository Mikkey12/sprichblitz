"""In-Memory-Token-Bucket pro Nutzer (Etappe 5) – prozesslokal, kein DB-Roundtrip.

``check`` wird aus async-Routen und synchronen FastAPI-Dependencies aufgerufen.
Ein ``threading.Lock`` schützt deshalb den Read/Modify/Write-Zyklus. Reset bei
Neustart ist akzeptabel. Geprüft wird VOR dem LocalInferenceGate.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from threading import Lock

from ..util.errors import RateLimited


@dataclass
class _Bucket:
    tokens: float
    last: float


class RateLimiter:
    def __init__(self, capacity: int = 60, refill_per_min: float = 120.0) -> None:
        self._capacity = float(capacity)
        self._refill_per_sec = refill_per_min / 60.0
        self._buckets: dict[int, _Bucket] = {}
        self._lock = Lock()

    def check(self, user_id: int, *, now: float | None = None) -> None:
        """Konsumiert 1 Token; wirft :class:`RateLimited` (429), wenn keiner frei ist.

        ``now`` ist nur für deterministische Tests injizierbar.
        """
        t = time.monotonic() if now is None else now
        with self._lock:
            bucket = self._buckets.get(user_id)
            if bucket is None:
                bucket = _Bucket(tokens=self._capacity, last=t)
                self._buckets[user_id] = bucket
            else:
                elapsed = max(0.0, t - bucket.last)
                bucket.tokens = min(self._capacity, bucket.tokens + elapsed * self._refill_per_sec)
                bucket.last = t
            if bucket.tokens < 1.0:
                raise RateLimited()
            bucket.tokens -= 1.0
