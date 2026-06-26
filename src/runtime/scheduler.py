from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Iterable

from .models import RoomChangeSet, RoomSpec
from .state import StateStore

RoomWorker = Callable[[RoomSpec], Awaitable[None]]


class RuntimeScheduler:
    def __init__(
        self,
        state: StateStore,
        worker: RoomWorker,
        *,
        retry_delay: float = 5.0,
    ) -> None:
        if retry_delay < 0:
            raise ValueError("retry delay cannot be negative")
        self._state = state
        self._worker = worker
        self._retry_delay = retry_delay
        self._tasks: dict[str, asyncio.Task[None]] = {}

    @property
    def room_ids(self) -> frozenset[str]:
        return frozenset(self._tasks)

    async def reconcile(self, rooms: Iterable[RoomSpec]) -> RoomChangeSet:
        changes = self._state.replace_desired_rooms(rooms)
        cancel_ids = {room.room_id for room in changes.removed}
        cancel_ids.update(previous.room_id for previous, _current in changes.updated)
        await self._cancel_rooms(cancel_ids)

        for room in changes.added:
            self._start_room(room)
        for _previous, current in changes.updated:
            self._start_room(current)
        return changes

    async def stop_all(self) -> None:
        room_ids = tuple(self._tasks)
        for room_id in room_ids:
            self._state.request_room_stop(room_id)
        await self._cancel_rooms(room_ids)

    def _start_room(self, room: RoomSpec) -> None:
        self._tasks[room.room_id] = asyncio.create_task(
            self._supervise(room),
            name=f"room:{room.room_id}",
        )

    async def _cancel_rooms(self, room_ids: Iterable[str]) -> None:
        tasks = [self._tasks.pop(room_id) for room_id in room_ids if room_id in self._tasks]
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _supervise(self, room: RoomSpec) -> None:
        self._state.mark_monitoring(room.room_id)
        while True:
            try:
                await self._worker(room)
            except asyncio.CancelledError:
                raise
            except Exception as error:
                self._state.mark_room_error(room.room_id, str(error))
                await asyncio.sleep(self._retry_delay)
            else:
                self._state.mark_room_success(room.room_id)
                return
