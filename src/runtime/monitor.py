from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field

from .limiter import AdjustableLimiter
from .models import RoomSpec
from .pacer import RequestPacer


@dataclass(frozen=True, slots=True)
class ProbeResult:
    is_live: bool
    payload: Mapping[str, object] = field(default_factory=dict)


RoomProbe = Callable[[RoomSpec], Awaitable[ProbeResult]]
RoomRecorder = Callable[[RoomSpec, ProbeResult], Awaitable[None]]
ProbeLifecycleCallback = Callable[[RoomSpec], Awaitable[None]]


class RoomMonitor:
    def __init__(
        self,
        limiter: AdjustableLimiter,
        probe: RoomProbe,
        record: RoomRecorder,
        *,
        pacer: RequestPacer | None = None,
        offline: RoomRecorder | None = None,
        on_success: RoomRecorder | None = None,
        on_probe_started: ProbeLifecycleCallback | None = None,
        on_probe_finished: ProbeLifecycleCallback | None = None,
        poll_interval: float,
    ) -> None:
        if poll_interval <= 0:
            raise ValueError("poll interval must be greater than zero")
        self._limiter = limiter
        self._probe = probe
        self._record = record
        self._pacer = pacer
        self._offline = offline
        self._on_success = on_success
        self._on_probe_started = on_probe_started
        self._on_probe_finished = on_probe_finished
        self._poll_interval = poll_interval

    async def run_once(self, room: RoomSpec) -> ProbeResult:
        if self._pacer is not None:
            await self._pacer.wait_turn(room.room_id)
        if self._on_probe_started is not None:
            await self._on_probe_started(room)
        try:
            async with self._limiter:
                result = await self._probe(room)
        finally:
            if self._on_probe_finished is not None:
                await self._on_probe_finished(room)
        if result.is_live:
            await self._record(room, result)
        elif self._offline is not None:
            await self._offline(room, result)
        if self._on_success is not None:
            await self._on_success(room, result)
        return result

    async def run(self, room: RoomSpec) -> None:
        while True:
            await self.run_once(room)
            await asyncio.sleep(self._poll_interval)
