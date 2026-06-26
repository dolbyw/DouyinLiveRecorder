from __future__ import annotations

import asyncio
from types import TracebackType


class AdjustableLimiter:
    def __init__(self, limit: int) -> None:
        self._validate_limit(limit)
        self._limit = limit
        self._active_count = 0
        self._waiting_count = 0
        self._condition = asyncio.Condition()

    @property
    def limit(self) -> int:
        return self._limit

    @property
    def active_count(self) -> int:
        return self._active_count

    @property
    def waiting_count(self) -> int:
        return self._waiting_count

    async def acquire(self) -> None:
        async with self._condition:
            self._waiting_count += 1
            try:
                await self._condition.wait_for(lambda: self._active_count < self._limit)
                self._active_count += 1
            finally:
                self._waiting_count -= 1

    async def release(self) -> None:
        async with self._condition:
            if self._active_count == 0:
                raise RuntimeError("limiter released without an active permit")
            self._active_count -= 1
            self._condition.notify_all()

    async def set_limit(self, limit: int) -> None:
        self._validate_limit(limit)
        async with self._condition:
            self._limit = limit
            self._condition.notify_all()

    async def __aenter__(self) -> AdjustableLimiter:
        await self.acquire()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        await self.release()

    @staticmethod
    def _validate_limit(limit: int) -> None:
        if limit <= 0:
            raise ValueError("limit must be greater than zero")
