from __future__ import annotations

import asyncio
import random
import time
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass


def calculate_first_sweep_spacing(
    target_window_seconds: float,
    room_count: int,
    *,
    minimum_seconds: float = 1.0,
) -> float:
    if target_window_seconds <= 0:
        raise ValueError("first sweep target window must be greater than zero")
    if minimum_seconds < 0:
        raise ValueError("first sweep minimum spacing cannot be negative")
    return max(minimum_seconds, target_window_seconds / max(1, room_count))


def calculate_legacy_first_start_spacing(room_count: int, configured_seconds: float) -> float:
    adaptive = calculate_first_sweep_spacing(15.0, room_count, minimum_seconds=1.0)
    return max(0.0, configured_seconds, adaptive)


def calculate_start_spacing(
    window_seconds: float,
    room_count: int,
    configured_seconds: float = 0,
) -> float:
    automatic = window_seconds / max(1, room_count)
    return max(0.0, configured_seconds, automatic)


@dataclass(frozen=True, slots=True)
class FirstSweepProgress:
    total: int
    issued: int

    @property
    def permits_complete(self) -> bool:
        return self.issued >= self.total


class RequestPacer:
    def __init__(
        self,
        *,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        jitter: Callable[[float, float], float] = random.uniform,
    ) -> None:
        self._clock = clock
        self._sleep = sleep
        self._jitter = jitter
        self._spacing = 0.0
        self._first_sweep_spacing = 1.0
        self._next_allowed = 0.0
        self._room_ids: set[str] = set()
        self._seen_room_ids: set[str] = set()
        self._lock = asyncio.Lock()

    @property
    def spacing(self) -> float:
        return self._spacing

    @property
    def first_sweep_progress(self) -> FirstSweepProgress:
        return FirstSweepProgress(
            total=len(self._room_ids),
            issued=len(self._room_ids & self._seen_room_ids),
        )

    async def configure(
        self,
        *,
        window_seconds: float,
        room_ids: Iterable[str],
        first_sweep_target_seconds: float = 15.0,
        first_sweep_minimum_seconds: float = 1.0,
    ) -> None:
        if window_seconds <= 0:
            raise ValueError("pacing window must be greater than zero")
        configured_room_ids = set(room_ids)
        async with self._lock:
            self._room_ids = configured_room_ids
            self._seen_room_ids.intersection_update(configured_room_ids)
            self._spacing = window_seconds / max(1, len(configured_room_ids))
            self._first_sweep_spacing = calculate_first_sweep_spacing(
                first_sweep_target_seconds,
                len(configured_room_ids),
                minimum_seconds=first_sweep_minimum_seconds,
            )

    async def wait_turn(self, room_id: str) -> float:
        async with self._lock:
            if room_id not in self._room_ids:
                raise KeyError(f"unknown paced room: {room_id}")
            now = self._clock()
            delay = max(0.0, self._next_allowed - now)
            if delay:
                await self._sleep(delay)
            started_at = self._clock()
            is_first_permit = room_id not in self._seen_room_ids
            if is_first_permit:
                self._seen_room_ids.add(room_id)
            all_first_permits_issued = self._room_ids <= self._seen_room_ids
            next_spacing = self._spacing if all_first_permits_issued else self._first_sweep_spacing
            self._next_allowed = started_at + next_spacing * self._jitter(0.9, 1.1)
            return started_at
