from __future__ import annotations

import asyncio
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Protocol

from .limiter import AdjustableLimiter
from .models import RoomChangeSet, RoomSpec
from .pacer import RequestPacer


@dataclass(frozen=True, slots=True)
class RuntimeConfig:
    rooms: tuple[RoomSpec, ...]
    max_requests: int


RuntimeConfigLoader = Callable[[], RuntimeConfig]


class RoomReconciler(Protocol):
    async def reconcile(self, rooms: Iterable[RoomSpec]) -> RoomChangeSet: ...


class RuntimeCoordinator:
    def __init__(
        self,
        loader: RuntimeConfigLoader,
        scheduler: RoomReconciler,
        limiter: AdjustableLimiter,
        *,
        pacer: RequestPacer | None = None,
        poll_interval: float | None = None,
        first_sweep_target_seconds: float = 15.0,
        first_sweep_minimum_seconds: float = 1.0,
        refresh_interval: float,
    ) -> None:
        if refresh_interval <= 0:
            raise ValueError("refresh interval must be greater than zero")
        self._loader = loader
        self._scheduler = scheduler
        self._limiter = limiter
        self._pacer = pacer
        self._poll_interval = poll_interval
        self._first_sweep_target_seconds = first_sweep_target_seconds
        self._first_sweep_minimum_seconds = first_sweep_minimum_seconds
        self._refresh_interval = refresh_interval

    async def refresh_once(self) -> RoomChangeSet:
        config = await asyncio.to_thread(self._loader)
        if self._pacer is not None:
            if self._poll_interval is None or self._poll_interval <= 0:
                raise ValueError("poll interval must be greater than zero when pacing is enabled")
            await self._pacer.configure(
                window_seconds=self._poll_interval,
                room_ids=(room.room_id for room in config.rooms),
                first_sweep_target_seconds=self._first_sweep_target_seconds,
                first_sweep_minimum_seconds=self._first_sweep_minimum_seconds,
            )
        await self._limiter.set_limit(config.max_requests)
        return await self._scheduler.reconcile(config.rooms)

    async def run(self) -> None:
        while True:
            await self.refresh_once()
            await asyncio.sleep(self._refresh_interval)
