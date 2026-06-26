from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from urllib.parse import urlsplit

from src.models import QualityLevel


@dataclass(frozen=True, slots=True)
class RoomSpec:
    url: str
    quality: QualityLevel
    name: str = ""

    def __post_init__(self) -> None:
        normalized_url = self.url.strip()
        parsed = urlsplit(normalized_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("room URL must be an absolute HTTP URL")
        object.__setattr__(self, "url", normalized_url)
        object.__setattr__(self, "name", self.name.strip())

    @property
    def room_id(self) -> str:
        return self.url


@dataclass(frozen=True, slots=True)
class RoomStatus:
    room_id: str
    monitoring: bool = False
    recording_name: str | None = None
    recording_quality: QualityLevel | None = None
    recording_started_at: datetime | None = None
    last_error: str | None = None
    consecutive_errors: int = 0
    stop_requested: bool = False


@dataclass(frozen=True, slots=True)
class RoomChangeSet:
    added: tuple[RoomSpec, ...] = ()
    removed: tuple[RoomSpec, ...] = ()
    updated: tuple[tuple[RoomSpec, RoomSpec], ...] = ()


@dataclass(frozen=True, slots=True)
class RuntimeSnapshot:
    desired_rooms: tuple[RoomSpec, ...]
    statuses: tuple[RoomStatus, ...]
    shutdown_requested: bool = False

    def status_for(self, room_id: str) -> RoomStatus:
        for status in self.statuses:
            if status.room_id == room_id:
                return status
        raise KeyError(room_id)
