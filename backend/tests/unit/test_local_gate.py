"""LocalInferenceGate: Serialisierung (deterministisch), Timeout, kein Permit-Leak."""

from __future__ import annotations

import asyncio

import pytest

from sprichblitz_backend.services.local_gate import LocalInferenceGate
from sprichblitz_backend.util.errors import LocalGateTimeout


async def test_gate_serializes_concurrent_local_calls() -> None:
    gate = LocalInferenceGate(concurrency=1, acquire_timeout_s=5.0)
    first_in = asyncio.Event()
    release_first = asyncio.Event()
    second_at_gate = asyncio.Event()
    second_in = asyncio.Event()
    order: list[str] = []

    async def first() -> None:
        async with gate.slot():
            order.append("first-in")
            first_in.set()
            await release_first.wait()
            order.append("first-out")

    async def second() -> None:
        await first_in.wait()  # erst ran, wenn first den Slot hält
        second_at_gate.set()
        async with gate.slot():
            order.append("second-in")
            second_in.set()

    t1 = asyncio.create_task(first())
    t2 = asyncio.create_task(second())
    await first_in.wait()
    await second_at_gate.wait()
    await asyncio.sleep(0)  # ein Scheduler-Yield: second läuft bis zum acquire
    assert not second_in.is_set()  # von Semaphore(1) blockiert – deterministisch

    release_first.set()
    await asyncio.gather(t1, t2)
    assert order == ["first-in", "first-out", "second-in"]


async def test_gate_acquire_timeout_raises_503() -> None:
    gate = LocalInferenceGate(concurrency=1, acquire_timeout_s=0.05)
    async with gate.slot():  # einziges Permit belegt
        with pytest.raises(LocalGateTimeout):
            async with gate.slot():
                pass


async def test_no_permit_leak_after_many_timeouts() -> None:
    gate = LocalInferenceGate(concurrency=2, acquire_timeout_s=0.02)
    release = asyncio.Event()
    h1_in = asyncio.Event()
    h2_in = asyncio.Event()

    async def hold(marker: asyncio.Event) -> None:
        async with gate.slot():
            marker.set()
            await release.wait()

    holders = [asyncio.create_task(hold(h1_in)), asyncio.create_task(hold(h2_in))]
    await h1_in.wait()
    await h2_in.wait()  # beide Permits gehalten (deterministisch)

    for _ in range(50):  # alle Acquires laufen in den Timeout
        with pytest.raises(LocalGateTimeout):
            async with gate.slot():
                pass

    release.set()
    await asyncio.gather(*holders)

    # Kein Leak: beide Permits sind wieder frei → 2 gleichzeitig acquirebar.
    async with gate.slot(), gate.slot():
        pass
