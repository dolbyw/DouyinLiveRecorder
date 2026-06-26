from __future__ import annotations

import threading
from collections.abc import Iterable
from dataclasses import replace
from datetime import datetime

from src.models import QualityLevel

from .models import RoomChangeSet, RoomSpec, RoomStatus, RuntimeSnapshot


class StateStore:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._desired_rooms: dict[str, RoomSpec] = {}
        self._statuses: dict[str, RoomStatus] = {}
        self._shutdown_requested = False

    def replace_desired_rooms(self, rooms: Iterable[RoomSpec]) -> RoomChangeSet:
        with self._lock:
            replacement: dict[str, RoomSpec] = {}
            for room in rooms:
                if room.room_id in replacement:
                    raise ValueError(f"duplicate room URL: {room.room_id}")
                replacement[room.room_id] = room

            added = tuple(room for room_id, room in replacement.items() if room_id not in self._desired_rooms)
            removed = tuple(room for room_id, room in self._desired_rooms.items() if room_id not in replacement)
            updated = tuple(
                (current, replacement[room_id])
                for room_id, current in self._desired_rooms.items()
                if room_id in replacement and current != replacement[room_id]
            )

            for room in added:
                self._statuses[room.room_id] = RoomStatus(room_id=room.room_id)
            for room in removed:
                status = self._statuses.get(room.room_id)
                if status is not None:
                    self._statuses[room.room_id] = replace(status, stop_requested=True)

            self._desired_rooms = replacement
            return RoomChangeSet(added=added, removed=removed, updated=updated)

    def mark_monitoring(self, room_id: str) -> None:
        with self._lock:
            self._statuses[room_id] = replace(self._require_status(room_id), monitoring=True)

    def mark_recording_started(
        self,
        room_id: str,
        recording_name: str,
        quality: QualityLevel,
        started_at: datetime,
    ) -> None:
        if started_at.tzinfo is None or started_at.utcoffset() is None:
            raise ValueError("recording start time must be timezone-aware")
        with self._lock:
            self._statuses[room_id] = replace(
                self._require_status(room_id),
                recording_name=recording_name,
                recording_quality=quality,
                recording_started_at=started_at,
            )

    def mark_recording_finished(self, room_id: str) -> None:
        with self._lock:
            self._statuses[room_id] = replace(
                self._require_status(room_id),
                recording_name=None,
                recording_quality=None,
                recording_started_at=None,
            )

    def mark_room_error(self, room_id: str, error: str) -> None:
        with self._lock:
            status = self._require_status(room_id)
            self._statuses[room_id] = replace(
                status,
                last_error=error,
                consecutive_errors=status.consecutive_errors + 1,
            )

    def mark_room_success(self, room_id: str) -> None:
        with self._lock:
            self._statuses[room_id] = replace(
                self._require_status(room_id),
                last_error=None,
                consecutive_errors=0,
            )

    def request_room_stop(self, room_id: str) -> None:
        with self._lock:
            self._statuses[room_id] = replace(self._require_status(room_id), stop_requested=True)

    def request_shutdown(self) -> None:
        with self._lock:
            self._shutdown_requested = True

    def snapshot(self) -> RuntimeSnapshot:
        with self._lock:
            return RuntimeSnapshot(
                desired_rooms=tuple(self._desired_rooms.values()),
                statuses=tuple(self._statuses.values()),
                shutdown_requested=self._shutdown_requested,
            )

    def _require_status(self, room_id: str) -> RoomStatus:
        try:
            return self._statuses[room_id]
        except KeyError:
            raise KeyError(f"unknown room: {room_id}") from None
