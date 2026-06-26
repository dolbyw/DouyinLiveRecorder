import asyncio
import threading
from collections import Counter

import pytest

from src.models import QualityLevel
from src.runtime import (
    AdjustableLimiter,
    RoomChangeSet,
    RoomSpec,
    RuntimeConfig,
    RuntimeCoordinator,
    RuntimeScheduler,
    StateStore,
)


class CapturingScheduler:
    def __init__(self) -> None:
        self.rooms: tuple[RoomSpec, ...] = ()

    async def reconcile(self, rooms) -> RoomChangeSet:
        self.rooms = tuple(rooms)
        return RoomChangeSet(added=self.rooms)


@pytest.mark.asyncio
async def test_refresh_loads_off_loop_resizes_limiter_and_reconciles():
    loop_thread = threading.get_ident()
    loader_thread = loop_thread
    spec = RoomSpec("https://live.douyin.com/1", QualityLevel.HD)

    def load() -> RuntimeConfig:
        nonlocal loader_thread
        loader_thread = threading.get_ident()
        return RuntimeConfig(rooms=(spec,), max_requests=3)

    limiter = AdjustableLimiter(1)
    scheduler = CapturingScheduler()
    coordinator = RuntimeCoordinator(load, scheduler, limiter, refresh_interval=1)

    changes = await coordinator.refresh_once()

    assert loader_thread != loop_thread
    assert limiter.limit == 3
    assert scheduler.rooms == (spec,)
    assert changes.added == (spec,)


@pytest.mark.asyncio
async def test_repeated_identical_refresh_does_not_duplicate_room_task():
    spec = RoomSpec("https://live.douyin.com/1", QualityLevel.ORIGIN)
    starts: Counter[str] = Counter()
    started = asyncio.Event()

    async def worker(room: RoomSpec) -> None:
        starts[room.room_id] += 1
        started.set()
        await asyncio.Event().wait()

    scheduler = RuntimeScheduler(StateStore(), worker)
    coordinator = RuntimeCoordinator(
        lambda: RuntimeConfig(rooms=(spec,), max_requests=1),
        scheduler,
        AdjustableLimiter(1),
        refresh_interval=1,
    )

    await coordinator.refresh_once()
    await started.wait()
    await coordinator.refresh_once()
    await asyncio.sleep(0)

    assert starts[spec.room_id] == 1
    await scheduler.stop_all()


@pytest.mark.asyncio
async def test_refresh_updates_pacer_from_poll_window_and_room_count():
    rooms = tuple(
        RoomSpec(f"https://live.douyin.com/{index}", QualityLevel.ORIGIN)
        for index in range(1, 15)
    )

    class CapturingPacer:
        def __init__(self) -> None:
            self.configurations = []

        async def configure(
            self,
            *,
            window_seconds,
            room_ids,
            first_sweep_target_seconds,
            first_sweep_minimum_seconds,
        ):
            self.configurations.append(
                (
                    window_seconds,
                    tuple(room_ids),
                    first_sweep_target_seconds,
                    first_sweep_minimum_seconds,
                )
            )

    pacer = CapturingPacer()
    coordinator = RuntimeCoordinator(
        lambda: RuntimeConfig(rooms=rooms, max_requests=5),
        CapturingScheduler(),
        AdjustableLimiter(1),
        pacer=pacer,
        poll_interval=300,
        refresh_interval=1,
    )

    await coordinator.refresh_once()

    assert pacer.configurations == [
        (300, tuple(room.room_id for room in rooms), 15.0, 1.0)
    ]
