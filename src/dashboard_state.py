from __future__ import annotations

import re
import threading
from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum
from urllib.parse import urlsplit

from src.runtime.models import RoomSpec


class RoomDisplayStatus(StrEnum):
    WAITING = "等待监控"
    PROBING = "首次检测"
    MONITORING = "监控中"
    RECORDING = "录制中"
    CONVERTING = "转码中"
    RETRYING = "重试中"
    DISABLED = "已停用"


class AppDisplayPhase(StrEnum):
    RUNNING = "运行正常"
    STOPPING = "正在停止"
    FINALIZING = "正在收尾"
    COMPLETE = "收尾完成"


class AttentionDisposition(StrEnum):
    AUTOMATIC = "自动恢复"
    ACTION_REQUIRED = "需要处理"


_PHASE_PRIORITY = {
    AppDisplayPhase.RUNNING: 0,
    AppDisplayPhase.STOPPING: 1,
    AppDisplayPhase.FINALIZING: 2,
    AppDisplayPhase.COMPLETE: 3,
}


_STATUS_PRIORITY = {
    RoomDisplayStatus.DISABLED: 0,
    RoomDisplayStatus.WAITING: 1,
    RoomDisplayStatus.PROBING: 2,
    RoomDisplayStatus.MONITORING: 3,
    RoomDisplayStatus.RETRYING: 4,
    RoomDisplayStatus.RECORDING: 5,
    RoomDisplayStatus.CONVERTING: 6,
}


@dataclass(frozen=True, slots=True)
class DashboardConfig:
    save_format: str = "-"
    quality: str = "-"
    split_seconds: int | None = None
    poll_seconds: int = 0
    max_requests: int = 0
    use_proxy: bool = False
    convert_to_mp4: bool = False
    save_path: str = "-"
    disk_free_gb: float | None = None
    recordings_size_bytes: int | None = None


@dataclass(frozen=True, slots=True)
class DashboardRoom:
    room_id: str
    index: int
    name: str
    platform: str
    quality: str
    status: RoomDisplayStatus
    status_since: datetime | None = None
    recording_name: str | None = None
    recording_started_at: datetime | None = None
    task_name: str | None = None
    progress_percent: float | None = None
    elapsed_seconds: float | None = None
    duration_seconds: float | None = None
    last_error: str | None = None
    last_checked_at: datetime | None = None
    output_path: str | None = None


@dataclass(frozen=True, slots=True)
class DashboardEvent:
    room_id: str
    event_type: str
    message: str
    at: datetime
    occurrences: int = 1
    correlation_id: str | None = None
    details: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True, slots=True)
class DashboardIncident:
    room_id: str
    incident_id: str
    message: str
    disposition: AttentionDisposition
    started_at: datetime
    updated_at: datetime
    occurrences: int = 1
    retry_attempt: int | None = None
    retry_limit: int | None = None
    next_retry_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class DashboardSnapshot:
    config: DashboardConfig
    rooms: tuple[DashboardRoom, ...]
    events: tuple[DashboardEvent, ...]
    current_time: datetime
    incidents: tuple[DashboardIncident, ...] = ()
    started_at: datetime | None = None
    phase: AppDisplayPhase = AppDisplayPhase.RUNNING
    error_count: int = 0
    ffmpeg_ready: bool = True
    first_sweep_total: int = 0
    first_sweep_started: int = 0
    first_sweep_completed: int = 0
    first_sweep_started_at: datetime | None = None
    first_sweep_completed_at: datetime | None = None

    @property
    def recording_count(self) -> int:
        return sum(room.status is RoomDisplayStatus.RECORDING for room in self.rooms)

    @property
    def converting_count(self) -> int:
        return sum(room.status is RoomDisplayStatus.CONVERTING for room in self.rooms)

    @property
    def monitoring_count(self) -> int:
        return sum(room.status is RoomDisplayStatus.MONITORING for room in self.rooms)


@dataclass(slots=True)
class _MutableRoom:
    spec: RoomSpec
    index: int
    status: RoomDisplayStatus = RoomDisplayStatus.WAITING
    status_since: datetime | None = None
    recording_name: str | None = None
    recording_started_at: datetime | None = None
    task_name: str | None = None
    progress_percent: float | None = None
    elapsed_seconds: float | None = None
    duration_seconds: float | None = None
    last_error: str | None = None
    last_checked_at: datetime | None = None
    output_path: str | None = None
    initial_probe_started: bool = False
    initial_probe_completed: bool = False


class DashboardStateStore:
    def __init__(self, *, started_at: datetime | None = None) -> None:
        self._lock = threading.RLock()
        self._rooms: dict[str, _MutableRoom] = {}
        self._config = DashboardConfig()
        self._events: list[DashboardEvent] = []
        self._incidents: dict[tuple[str, str], DashboardIncident] = {}
        self._error_count = 0
        self._ffmpeg_ready = True
        self._started_at = started_at or datetime.now().astimezone()
        self._phase = AppDisplayPhase.RUNNING
        self._first_sweep_room_ids: set[str] = set()
        self._first_sweep_started_at: datetime | None = None
        self._first_sweep_completed_at: datetime | None = None
        self._last_initial_probe_finished_at: datetime | None = None

    def set_phase(self, phase: AppDisplayPhase) -> None:
        with self._lock:
            if _PHASE_PRIORITY[phase] >= _PHASE_PRIORITY[self._phase]:
                self._phase = phase

    def set_config(self, config: DashboardConfig) -> None:
        with self._lock:
            self._config = config

    def set_health(self, *, error_count: int, ffmpeg_ready: bool = True) -> None:
        with self._lock:
            self._error_count = max(0, error_count)
            self._ffmpeg_ready = ffmpeg_ready

    def reconcile_rooms(self, rooms: tuple[RoomSpec, ...] | list[RoomSpec]) -> None:
        with self._lock:
            replacement: dict[str, _MutableRoom] = {}
            for index, spec in enumerate(rooms, start=1):
                current = self._rooms.get(spec.room_id)
                if current is None:
                    current = _MutableRoom(spec=spec, index=index)
                else:
                    current.spec = spec
                    current.index = index
                replacement[spec.room_id] = current
            self._rooms = replacement
            active_room_ids = set(replacement)
            self._incidents = {
                key: incident
                for key, incident in self._incidents.items()
                if key[0] in active_room_ids or key[0] == "system"
            }
            if self._first_sweep_completed_at is None:
                self._first_sweep_room_ids = set(replacement)
                self._complete_first_sweep_if_ready()

    def mark_initial_probe_started(self, room_id: str, *, at: datetime | None = None) -> None:
        with self._lock:
            room = self._room(room_id)
            if room.initial_probe_started:
                return
            timestamp = at or datetime.now().astimezone()
            room.initial_probe_started = True
            if room.status is RoomDisplayStatus.WAITING:
                room.status = RoomDisplayStatus.PROBING
                room.status_since = timestamp
            if room_id in self._first_sweep_room_ids and self._first_sweep_started_at is None:
                self._first_sweep_started_at = timestamp

    def mark_initial_probe_finished(self, room_id: str, *, at: datetime | None = None) -> None:
        with self._lock:
            room = self._room(room_id)
            if room.initial_probe_completed:
                return
            timestamp = at or datetime.now().astimezone()
            room.initial_probe_started = True
            room.initial_probe_completed = True
            self._last_initial_probe_finished_at = timestamp
            if room_id in self._first_sweep_room_ids and self._first_sweep_started_at is None:
                self._first_sweep_started_at = timestamp
            self._complete_first_sweep_if_ready(timestamp)

    def mark_monitoring(
        self,
        room_id: str,
        *,
        at: datetime | None = None,
        checked: bool = True,
    ) -> None:
        with self._lock:
            room = self._room(room_id)
            timestamp = at or datetime.now().astimezone()
            if room.status not in {RoomDisplayStatus.RECORDING, RoomDisplayStatus.CONVERTING}:
                if room.status is not RoomDisplayStatus.MONITORING:
                    room.status_since = timestamp
                room.status = RoomDisplayStatus.MONITORING
                room.last_error = None
                if checked:
                    room.last_checked_at = timestamp

    def mark_recording(
        self,
        room_id: str,
        recording_name: str,
        quality: str,
        started_at: datetime,
        output_path: str | None = None,
    ) -> None:
        with self._lock:
            room = self._room(room_id)
            room.status = RoomDisplayStatus.RECORDING
            room.status_since = started_at
            room.recording_name = recording_name
            room.recording_started_at = started_at
            room.task_name = None
            room.progress_percent = None
            room.elapsed_seconds = None
            room.duration_seconds = None
            room.last_error = None
            if output_path is not None:
                room.output_path = output_path
            if quality:
                room.spec = replace(room.spec, quality=_quality_from_label(quality, room.spec.quality))

    def mark_recording_finished(self, room_id: str, *, at: datetime | None = None) -> None:
        with self._lock:
            room = self._room(room_id)
            room.recording_name = None
            room.recording_started_at = None
            room.output_path = None
            if room.status is not RoomDisplayStatus.CONVERTING:
                room.status = RoomDisplayStatus.MONITORING
                room.status_since = at or datetime.now().astimezone()

    def mark_converting(
        self,
        room_id: str,
        task_name: str,
        percent: float | None,
        elapsed_seconds: float,
        duration_seconds: float | None,
    ) -> None:
        with self._lock:
            room = self._room(room_id)
            room.status = RoomDisplayStatus.CONVERTING
            room.task_name = task_name
            room.progress_percent = None if percent is None else min(100.0, max(0.0, percent))
            room.elapsed_seconds = max(0.0, elapsed_seconds)
            room.duration_seconds = duration_seconds
            room.last_error = None

    def mark_conversion_finished(self, room_id: str, *, at: datetime | None = None) -> None:
        with self._lock:
            room = self._room(room_id)
            room.status = RoomDisplayStatus.MONITORING
            room.status_since = at or datetime.now().astimezone()
            room.task_name = None
            room.progress_percent = None
            room.elapsed_seconds = None
            room.duration_seconds = None

    def mark_retrying(self, room_id: str, error: str, *, at: datetime | None = None) -> None:
        with self._lock:
            room = self._room(room_id)
            room.last_error = _normalize_message(error)
            if _STATUS_PRIORITY[room.status] <= _STATUS_PRIORITY[RoomDisplayStatus.RETRYING]:
                room.status = RoomDisplayStatus.RETRYING
                room.status_since = at or datetime.now().astimezone()

    def mark_disabled(self, room_id: str, *, at: datetime | None = None) -> None:
        with self._lock:
            room = self._room(room_id)
            room.status = RoomDisplayStatus.DISABLED
            room.status_since = at or datetime.now().astimezone()

    def report_incident(
        self,
        room_id: str,
        incident_id: str,
        message: str,
        *,
        disposition: AttentionDisposition,
        at: datetime | None = None,
        retry_attempt: int | None = None,
        retry_limit: int | None = None,
        next_retry_at: datetime | None = None,
    ) -> DashboardIncident:
        timestamp = at or datetime.now().astimezone()
        key = (room_id, incident_id)
        normalized = _normalize_message(message)
        with self._lock:
            current = self._incidents.get(key)
            incident = DashboardIncident(
                room_id=room_id,
                incident_id=incident_id,
                message=normalized,
                disposition=disposition,
                started_at=current.started_at if current is not None else timestamp,
                updated_at=timestamp,
                occurrences=(current.occurrences + 1) if current is not None else 1,
                retry_attempt=retry_attempt,
                retry_limit=retry_limit,
                next_retry_at=next_retry_at,
            )
            self._incidents[key] = incident
            return incident

    def clear_incident(
        self,
        room_id: str,
        incident_id: str,
        *,
        at: datetime | None = None,
        recovery_message: str | None = None,
    ) -> DashboardIncident | None:
        with self._lock:
            incident = self._incidents.pop((room_id, incident_id), None)
            if incident is not None and recovery_message:
                self.add_event(
                    room_id,
                    "incident_recovered",
                    recovery_message,
                    at=at,
                    correlation_id=f"incident:{room_id}:{incident_id}",
                )
            return incident

    def clear_room_incidents(
        self,
        room_id: str,
        *,
        incident_ids: tuple[str, ...] | None = None,
        at: datetime | None = None,
    ) -> tuple[DashboardIncident, ...]:
        del at
        with self._lock:
            keys = [
                key
                for key in self._incidents
                if key[0] == room_id and (incident_ids is None or key[1] in incident_ids)
            ]
            return tuple(self._incidents.pop(key) for key in keys)

    def add_event(
        self,
        room_id: str,
        event_type: str,
        message: str,
        *,
        at: datetime | None = None,
        correlation_id: str | None = None,
        details: dict[str, str] | tuple[tuple[str, str], ...] | None = None,
    ) -> None:
        normalized = _normalize_message(message)
        timestamp = at or datetime.now().astimezone()
        key = (room_id, event_type, normalized)
        if isinstance(details, dict):
            normalized_details = tuple(sorted((str(name), str(value)) for name, value in details.items()))
        else:
            normalized_details = tuple(sorted(details or ()))
        with self._lock:
            if correlation_id is not None:
                for index, event in enumerate(self._events):
                    if event.correlation_id == correlation_id:
                        self._events.pop(index)
                        self._events.append(
                            DashboardEvent(
                                room_id=room_id,
                                event_type=event_type,
                                message=normalized,
                                at=timestamp,
                                occurrences=event.occurrences,
                                correlation_id=correlation_id,
                                details=normalized_details,
                            )
                        )
                        break
                else:
                    self._events.append(
                        DashboardEvent(
                            room_id=room_id,
                            event_type=event_type,
                            message=normalized,
                            at=timestamp,
                            correlation_id=correlation_id,
                            details=normalized_details,
                        )
                    )
                self._events = self._events[-50:]
                return
            for index, event in enumerate(self._events):
                if (event.room_id, event.event_type, event.message) == key:
                    self._events.pop(index)
                    self._events.append(replace(event, at=timestamp, occurrences=event.occurrences + 1))
                    break
            else:
                self._events.append(
                    DashboardEvent(
                        room_id=room_id,
                        event_type=event_type,
                        message=normalized,
                        at=timestamp,
                        correlation_id=correlation_id,
                        details=normalized_details,
                    )
                )
            self._events = self._events[-50:]

    def snapshot(self, *, now: datetime | None = None) -> DashboardSnapshot:
        current_time = now or datetime.now().astimezone()
        with self._lock:
            rooms = tuple(self._snapshot_room(room, current_time) for room in self._rooms.values())
            incidents = tuple(
                sorted(
                    self._incidents.values(),
                    key=lambda incident: (
                        incident.disposition is not AttentionDisposition.ACTION_REQUIRED,
                        -incident.updated_at.timestamp(),
                    ),
                )
            )
            return DashboardSnapshot(
                config=self._config,
                rooms=rooms,
                events=tuple(reversed(self._events)),
                current_time=current_time,
                incidents=incidents,
                started_at=self._started_at,
                phase=self._phase,
                error_count=self._error_count,
                ffmpeg_ready=self._ffmpeg_ready,
                first_sweep_total=len(self._first_sweep_room_ids),
                first_sweep_started=sum(
                    self._rooms[room_id].initial_probe_started
                    for room_id in self._first_sweep_room_ids
                    if room_id in self._rooms
                ),
                first_sweep_completed=sum(
                    self._rooms[room_id].initial_probe_completed
                    for room_id in self._first_sweep_room_ids
                    if room_id in self._rooms
                ),
                first_sweep_started_at=self._first_sweep_started_at,
                first_sweep_completed_at=self._first_sweep_completed_at,
            )

    def _complete_first_sweep_if_ready(self, at: datetime | None = None) -> None:
        if self._first_sweep_completed_at is not None or not self._first_sweep_room_ids:
            return
        if all(
            room_id in self._rooms and self._rooms[room_id].initial_probe_completed
            for room_id in self._first_sweep_room_ids
        ):
            self._first_sweep_completed_at = at or self._last_initial_probe_finished_at or datetime.now().astimezone()

    def _room(self, room_id: str) -> _MutableRoom:
        try:
            return self._rooms[room_id]
        except KeyError:
            raise KeyError(f"unknown dashboard room: {room_id}") from None

    @staticmethod
    def _snapshot_room(room: _MutableRoom, now: datetime) -> DashboardRoom:
        elapsed = room.elapsed_seconds
        if room.status is RoomDisplayStatus.RECORDING and room.recording_started_at is not None:
            elapsed = max(0.0, (now - room.recording_started_at).total_seconds())
        return DashboardRoom(
            room_id=room.spec.room_id,
            index=room.index,
            name=room.spec.name or f"直播间 {room.index}",
            platform=_platform_name(room.spec.url),
            quality=room.spec.quality.value,
            status=room.status,
            status_since=room.status_since,
            recording_name=room.recording_name,
            recording_started_at=room.recording_started_at,
            task_name=room.task_name,
            progress_percent=room.progress_percent,
            elapsed_seconds=elapsed,
            duration_seconds=room.duration_seconds,
            last_error=room.last_error,
            last_checked_at=room.last_checked_at,
            output_path=room.output_path,
        )


def _normalize_message(message: str) -> str:
    return re.sub(r"\s+", " ", str(message)).strip()


def _platform_name(url: str) -> str:
    host = urlsplit(url).netloc.lower()
    labels = {
        "douyin.com": "抖音",
        "bilibili.com": "B站",
        "huya.com": "虎牙",
        "douyu.com": "斗鱼",
        "kuaishou.com": "快手",
        "tiktok.com": "TikTok",
        "twitch.tv": "Twitch",
        "youtube.com": "YouTube",
        "youtu.be": "YouTube",
    }
    for suffix, label in labels.items():
        if host == suffix or host.endswith(f".{suffix}"):
            return label
    return host.removeprefix("www.") or "未知平台"


def _quality_from_label(label: str, fallback):
    quality_type = type(fallback)
    from_raw = getattr(quality_type, "from_raw", None)
    return from_raw(label, fallback) if from_raw is not None else fallback
