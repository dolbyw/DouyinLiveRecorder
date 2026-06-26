import asyncio
from collections import Counter

import pytest

from src.models import QualityLevel
from src.runtime import RoomSpec, RuntimeScheduler, StateStore


def room(url: str, quality: QualityLevel = QualityLevel.ORIGIN, name: str = "") -> RoomSpec:
    return RoomSpec(url=url, quality=quality, name=name)


@pytest.mark.asyncio
async def test_reconcile_starts_added_room_only_once():
    starts: Counter[str] = Counter()
    running = asyncio.Event()

    async def worker(spec: RoomSpec) -> None:
        starts[spec.room_id] += 1
        running.set()
        await asyncio.Event().wait()

    scheduler = RuntimeScheduler(StateStore(), worker)
    spec = room("https://live.douyin.com/1")

    await scheduler.reconcile([spec])
    await running.wait()
    await scheduler.reconcile([spec])

    assert starts[spec.room_id] == 1
    assert scheduler.room_ids == frozenset({spec.room_id})
    await scheduler.stop_all()


@pytest.mark.asyncio
async def test_reconcile_cancels_removed_room():
    cancelled = asyncio.Event()

    async def worker(_spec: RoomSpec) -> None:
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    scheduler = RuntimeScheduler(StateStore(), worker)
    spec = room("https://live.douyin.com/1")
    await scheduler.reconcile([spec])
    await asyncio.sleep(0)

    await scheduler.reconcile([])

    assert cancelled.is_set()
    assert scheduler.room_ids == frozenset()


@pytest.mark.asyncio
async def test_reconcile_restarts_updated_room():
    starts: list[RoomSpec] = []
    started_twice = asyncio.Event()

    async def worker(spec: RoomSpec) -> None:
        starts.append(spec)
        if len(starts) == 2:
            started_twice.set()
        await asyncio.Event().wait()

    scheduler = RuntimeScheduler(StateStore(), worker)
    original = room("https://live.douyin.com/1")
    updated = room(original.url, QualityLevel.HD, "new name")

    await scheduler.reconcile([original])
    await asyncio.sleep(0)
    await scheduler.reconcile([updated])
    await started_twice.wait()

    assert starts == [original, updated]
    await scheduler.stop_all()


@pytest.mark.asyncio
async def test_room_failure_retries_without_cancelling_sibling():
    attempts: Counter[str] = Counter()
    bad_retried = asyncio.Event()
    sibling_running = asyncio.Event()

    async def worker(spec: RoomSpec) -> None:
        attempts[spec.room_id] += 1
        if spec.room_id.endswith("/bad"):
            if attempts[spec.room_id] >= 2:
                bad_retried.set()
            raise RuntimeError("probe failed")
        sibling_running.set()
        await asyncio.Event().wait()

    state = StateStore()
    scheduler = RuntimeScheduler(state, worker, retry_delay=0)
    bad = room("https://live.douyin.com/bad")
    good = room("https://live.douyin.com/good")

    await scheduler.reconcile([bad, good])
    await asyncio.wait_for(sibling_running.wait(), timeout=1)
    await asyncio.wait_for(bad_retried.wait(), timeout=1)

    assert good.room_id in scheduler.room_ids
    assert state.snapshot().status_for(bad.room_id).consecutive_errors >= 2
    assert state.snapshot().status_for(good.room_id).consecutive_errors == 0
    await scheduler.stop_all()


@pytest.mark.asyncio
async def test_stop_cancellation_is_not_retried():
    attempts = 0
    started = asyncio.Event()

    async def worker(_spec: RoomSpec) -> None:
        nonlocal attempts
        attempts += 1
        started.set()
        await asyncio.Event().wait()

    scheduler = RuntimeScheduler(StateStore(), worker, retry_delay=0)
    spec = room("https://live.douyin.com/1")
    await scheduler.reconcile([spec])
    await started.wait()

    await scheduler.stop_all()
    await asyncio.sleep(0)

    assert attempts == 1
