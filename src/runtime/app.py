from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from .recording import RecordingExecutor
from .scheduler import RuntimeScheduler
from .state import StateStore


@dataclass(frozen=True, slots=True)
class ShutdownReport:
    unfinished_recordings: tuple[str, ...] = ()


class RuntimeApp:
    def __init__(
        self,
        state: StateStore,
        scheduler: RuntimeScheduler,
        recordings: RecordingExecutor,
        *,
        close_http: Callable[[], Awaitable[None]],
    ) -> None:
        self._state = state
        self._scheduler = scheduler
        self._recordings = recordings
        self._close_http = close_http
        self._shutdown_lock = asyncio.Lock()
        self._shutdown_report: ShutdownReport | None = None

    async def shutdown(self, *, timeout: float = 10.0) -> ShutdownReport:
        if self._shutdown_report is not None:
            return self._shutdown_report

        async with self._shutdown_lock:
            if self._shutdown_report is not None:
                return self._shutdown_report

            self._state.request_shutdown()
            self._recordings.request_shutdown()
            unfinished: tuple[str, ...] = ()
            try:
                await self._scheduler.stop_all()
            finally:
                try:
                    unfinished = await self._recordings.close(timeout)
                finally:
                    await self._close_http()

            self._shutdown_report = ShutdownReport(unfinished_recordings=unfinished)
            return self._shutdown_report
