"""RateLimiter: Burst→429, Refill über Zeit, Per-User-Isolation (deterministisch)."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import pytest

from sprichblitz_backend.services.rate_limit import RateLimiter
from sprichblitz_backend.util.errors import RateLimited


def test_burst_then_429() -> None:
    rl = RateLimiter(capacity=3, refill_per_min=0.0)
    for _ in range(3):
        rl.check(1, now=0.0)
    with pytest.raises(RateLimited):
        rl.check(1, now=0.0)


def test_refill_over_time() -> None:
    rl = RateLimiter(capacity=2, refill_per_min=60.0)  # 1 Token/Sek
    rl.check(1, now=0.0)
    rl.check(1, now=0.0)
    with pytest.raises(RateLimited):
        rl.check(1, now=0.0)
    rl.check(1, now=1.0)  # nach 1 s wieder 1 Token
    with pytest.raises(RateLimited):
        rl.check(1, now=1.0)


def test_per_user_isolation() -> None:
    rl = RateLimiter(capacity=1, refill_per_min=0.0)
    rl.check(1, now=0.0)
    rl.check(2, now=0.0)  # eigener Bucket
    with pytest.raises(RateLimited):
        rl.check(1, now=0.0)


def test_concurrent_checks_never_exceed_capacity() -> None:
    capacity = 7
    rl = RateLimiter(capacity=capacity, refill_per_min=0.0)

    def consume(_: int) -> bool:
        try:
            rl.check(1, now=0.0)
        except RateLimited:
            return False
        return True

    with ThreadPoolExecutor(max_workers=32) as pool:
        accepted = list(pool.map(consume, range(100)))

    assert sum(accepted) == capacity
