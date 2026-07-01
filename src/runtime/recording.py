from __future__ import annotations

import asyncio
import threading
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, TypeVar

ResultT = TypeVar("ResultT")


class StopToken:
    def __init__(self) -> None:
        self._room_stop = threading.Event()
        self._shutdown = threading.Event()

    @property
    def room_stop_requested(self) -> bool:
        return self._room_stop.is_set()

    @property
    def shutdown_requested(self) -> bool:
        return self._shutdown.is_set()

    def request_room_stop(self) -> None:
        self._room_stop.set()

    def request_shutdown(self) -> None:
        self._shutdown.set()


RecordingOperation = Callable[[StopToken], ResultT]


@dataclass(slots=True)
class _RecordingJob:
    token: StopToken
    future: asyncio.Future[Any]
    thread: threading.Thread


class RecordingExecutor:
    def __init__(self, *, max_workers: int = 4) -> None:
        if max_workers <= 0:
            raise ValueError("max workers must be greater than zero")
        self._jobs: dict[str, _RecordingJob] = {}
        self._closed = False
        self._worker_slots = asyncio.Semaphore(max_workers)

    @property
    def active_room_ids(self) -> frozenset[str]:
        return frozenset(self._jobs)

    async def run(self, room_id: str, operation: RecordingOperation[ResultT]) -> ResultT:
        if self._closed:
            raise RuntimeError("recording executor is closed")
        if room_id in self._jobs:
            raise RuntimeError(f"room is already recording: {room_id}")

        loop = asyncio.get_running_loop()
        token = StopToken()
        future: asyncio.Future[Any] = loop.create_future()

        def worker() -> None:
            try:
                result = operation(token)
            except BaseException as error:
                loop.call_soon_threadsafe(self._set_future_exception, future, error)
            else:
                loop.call_soon_threadsafe(self._set_future_result, future, result)

        thread = threading.Thread(
            target=worker,
            name=f"recording:{room_id}",
            daemon=True,
        )
        job = _RecordingJob(token=token, future=future, thread=thread)
        self._jobs[room_id] = job
        acquired_slot = False
        try:
            await self._worker_slots.acquire()
            acquired_slot = True
            if self._closed or token.shutdown_requested:
                raise RuntimeError("recording executor is closed")
            thread.start()
            return await asyncio.shield(future)
        except asyncio.CancelledError as cancellation:
            token.request_room_stop()
            if acquired_slot:
                try:
                    await asyncio.shield(future)
                except BaseException:
                    pass
            raise cancellation
        finally:
            if self._jobs.get(room_id) is job:
                self._jobs.pop(room_id)
            if acquired_slot:
                self._worker_slots.release()

    def request_room_stop(self, room_id: str) -> bool:
        job = self._jobs.get(room_id)
        if job is None:
            return False
        job.token.request_room_stop()
        return True

    def request_shutdown(self) -> None:
        for job in self._jobs.values():
            job.token.request_shutdown()

    async def close(self, timeout: float) -> tuple[str, ...]:
        if timeout < 0:
            raise ValueError("close timeout cannot be negative")
        self._closed = True
        self.request_shutdown()
        jobs = tuple(self._jobs.items())
        if jobs:
            await asyncio.wait(
                [job.future for _room_id, job in jobs],
                timeout=timeout,
            )
        unfinished = tuple(sorted(room_id for room_id, job in jobs if not job.future.done()))
        for room_id, job in jobs:
            if room_id not in unfinished:
                job.thread.join(timeout=0)
        return unfinished

    @staticmethod
    def _set_future_result(future: asyncio.Future[Any], result: Any) -> None:
        if not future.done():
            future.set_result(result)

    @staticmethod
    def _set_future_exception(future: asyncio.Future[Any], error: BaseException) -> None:
        if not future.done():
            future.set_exception(error)
