from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from .dashboard_state import (
    AppDisplayPhase,
    AttentionDisposition,
    DashboardConfig,
    DashboardEvent,
    DashboardIncident,
    DashboardRoom,
    DashboardSnapshot,
    DashboardUploadStatus,
    RoomDisplayStatus,
)


class ViewWidth(StrEnum):
    NARROW = "narrow"
    MEDIUM = "medium"
    WIDE = "wide"


class RoomListMode(StrEnum):
    COMPACT = "compact"
    EXPANDED = "expanded"


@dataclass(frozen=True, slots=True)
class MetricView:
    value: str
    label: str
    kind: str = "normal"


@dataclass(frozen=True, slots=True)
class HealthView:
    label: str
    value: str
    healthy: bool = True


@dataclass(frozen=True, slots=True)
class RoomRowView:
    index: int
    room_id: str
    name: str
    platform: str
    status: str
    status_kind: str
    quality: str
    progress: str
    detail: str


@dataclass(frozen=True, slots=True)
class IncidentRowView:
    disposition: str
    kind: str
    room_name: str
    message: str
    detail: str


@dataclass(frozen=True, slots=True)
class EventRowView:
    time: str
    label: str
    kind: str
    room_name: str
    detail: str


@dataclass(frozen=True, slots=True)
class RowBudget:
    incident_rows: int
    room_rows: int
    event_rows: int


@dataclass(frozen=True, slots=True)
class RecordingStats:
    size_bytes: int
    bitrate_mbps: float


@dataclass(frozen=True, slots=True)
class DashboardView:
    width_mode: ViewWidth
    title: str
    phase: str
    current_time: str
    uptime: str
    metrics: tuple[MetricView, ...]
    health: tuple[HealthView, ...]
    config_items: tuple[str, ...]
    save_path: str
    rooms: tuple[RoomRowView, ...]
    hidden_room_count: int
    total_room_count: int
    room_mode: RoomListMode
    incidents: tuple[IncidentRowView, ...]
    events: tuple[EventRowView, ...]
    hidden_event_count: int
    first_sweep: str | None
    complete_prompt: str | None
    upload_detail: str | None = None


RecordingStatsReader = Callable[[DashboardRoom], RecordingStats | None]

_STATUS_PRIORITY = {
    RoomDisplayStatus.RECORDING: 2,
    RoomDisplayStatus.CONVERTING: 3,
    RoomDisplayStatus.PROBING: 4,
    RoomDisplayStatus.RETRYING: 5,
    RoomDisplayStatus.MONITORING: 6,
    RoomDisplayStatus.WAITING: 7,
    RoomDisplayStatus.DISABLED: 8,
}

_STATUS_VIEW = {
    RoomDisplayStatus.WAITING: ("等待", "dim"),
    RoomDisplayStatus.PROBING: ("首检", "info"),
    RoomDisplayStatus.MONITORING: ("监控", "info"),
    RoomDisplayStatus.RECORDING: ("录制", "success"),
    RoomDisplayStatus.CONVERTING: ("转码", "warning"),
    RoomDisplayStatus.RETRYING: ("恢复中", "warning"),
    RoomDisplayStatus.DISABLED: ("停用", "dim"),
}

_EVENT_VIEW = {
    "recording_started": ("开始录制", "success"),
    "recording_finished": ("录制结束", "dim"),
    "conversion_started": ("开始转码", "warning"),
    "conversion_finished": ("处理完成", "info"),
    "conversion_failed": ("处理失败", "danger"),
    "recording_error": ("录制异常", "danger"),
    "upload_started": ("上传开始", "info"),
    "upload_finished": ("上传完成", "success"),
    "upload_partial": ("部分上传", "warning"),
    "upload_failed": ("上传失败", "danger"),
    "upload_skipped": ("上传跳过", "dim"),
    "incident_recovered": ("已恢复", "success"),
    "room_added": ("加入监控", "info"),
    "disabled": ("已停用", "dim"),
    "first_sweep_completed": ("巡检完成", "info"),
}


def classify_width(width: int) -> ViewWidth:
    if width < 80:
        return ViewWidth.NARROW
    if width < 120:
        return ViewWidth.MEDIUM
    return ViewWidth.WIDE


def allocate_rows(
    *,
    height: int,
    incident_count: int,
    room_count: int,
    event_count: int,
    room_mode: RoomListMode,
) -> RowBudget:
    incident_rows = max(0, incident_count)
    available = max(0, height - 12 - incident_rows)
    minimum_events = min(3, event_count)
    room_capacity = max(0, available - minimum_events)
    if room_mode is RoomListMode.EXPANDED:
        room_rows = min(room_count, room_capacity)
    else:
        room_rows = min(room_count, room_capacity, 10)
    event_rows = min(event_count, max(minimum_events, available - room_rows), 10)
    return RowBudget(incident_rows=incident_rows, room_rows=room_rows, event_rows=event_rows)


def build_dashboard_view(
    snapshot: DashboardSnapshot,
    *,
    width: int,
    height: int,
    room_mode: RoomListMode,
    upload_detail_expanded: bool = False,
    recording_stats: RecordingStatsReader | None = None,
) -> DashboardView:
    reader = recording_stats or read_recording_stats
    budget = allocate_rows(
        height=height,
        incident_count=len(snapshot.incidents),
        room_count=len(snapshot.rooms),
        event_count=len(snapshot.events),
        room_mode=room_mode,
    )
    incident_map = {(incident.room_id, incident.disposition): incident for incident in snapshot.incidents}
    action_room_ids = {
        incident.room_id
        for incident in snapshot.incidents
        if incident.disposition is AttentionDisposition.ACTION_REQUIRED
    }
    automatic_room_ids = {
        incident.room_id for incident in snapshot.incidents if incident.disposition is AttentionDisposition.AUTOMATIC
    }
    ordered_rooms = sorted(
        snapshot.rooms,
        key=lambda room: (
            0
            if room.room_id in action_room_ids
            else 1
            if room.room_id in automatic_room_ids
            else _STATUS_PRIORITY[room.status],
            room.index,
        ),
    )
    room_rows = tuple(
        _build_room_row(room, snapshot, reader, incident_map) for room in ordered_rooms[: budget.room_rows]
    )
    incidents = tuple(_build_incident_row(incident, snapshot) for incident in snapshot.incidents)
    events = tuple(_build_event_row(event, snapshot) for event in snapshot.events[: budget.event_rows])
    actionable_count = sum(
        incident.disposition is AttentionDisposition.ACTION_REQUIRED for incident in snapshot.incidents
    )
    automatic_count = len(snapshot.incidents) - actionable_count
    metrics = (
        MetricView(str(len(snapshot.rooms)), "直播间"),
        MetricView(str(snapshot.recording_count), "录制", "success"),
        MetricView(str(snapshot.monitoring_count), "监控", "info"),
        MetricView(str(snapshot.converting_count), "转码", "warning"),
        MetricView(str(actionable_count), "需处理", "danger" if actionable_count else "success"),
    )
    health = (
        HealthView("FFmpeg", "正常" if snapshot.ffmpeg_ready else "异常", snapshot.ffmpeg_ready),
        HealthView(
            "已占用",
            _format_bytes(snapshot.config.recordings_size_bytes)
            if snapshot.config.recordings_size_bytes is not None
            else "未知",
            True,
        ),
        HealthView(
            "剩余",
            f"{snapshot.config.disk_free_gb:.1f} GB" if snapshot.config.disk_free_gb is not None else "未知",
            snapshot.config.disk_free_gb is None or snapshot.config.disk_free_gb > 1,
        ),
        HealthView("自动恢复", str(automatic_count), True),
        _upload_health(snapshot.upload),
    )
    return DashboardView(
        width_mode=classify_width(width),
        title="DouyinLiveRecorder",
        phase=snapshot.phase.value,
        current_time=f"{snapshot.current_time:%Y-%m-%d %H:%M:%S}",
        uptime=_format_duration(
            (snapshot.current_time - (snapshot.started_at or snapshot.current_time)).total_seconds()
        ),
        metrics=metrics,
        health=health,
        config_items=_config_items(snapshot.config, snapshot.upload),
        save_path=snapshot.config.save_path,
        rooms=room_rows,
        hidden_room_count=len(snapshot.rooms) - len(room_rows),
        total_room_count=len(snapshot.rooms),
        room_mode=room_mode,
        incidents=incidents,
        events=events,
        hidden_event_count=len(snapshot.events) - len(events),
        first_sweep=_first_sweep(snapshot),
        complete_prompt=(
            "按任意键退出 | Ctrl+C 强制退出" if snapshot.phase is AppDisplayPhase.COMPLETE else None
        ),
        upload_detail=_upload_detail(snapshot.upload) if upload_detail_expanded and snapshot.upload.enabled else None,
    )


def _build_room_row(
    room: DashboardRoom,
    snapshot: DashboardSnapshot,
    reader: RecordingStatsReader,
    incident_map: dict[tuple[str, AttentionDisposition], DashboardIncident],
) -> RoomRowView:
    action = incident_map.get((room.room_id, AttentionDisposition.ACTION_REQUIRED))
    automatic = incident_map.get((room.room_id, AttentionDisposition.AUTOMATIC))
    if action is not None:
        status, status_kind = "需要处理", "danger"
        detail = action.message
    elif automatic is not None:
        status, status_kind = "自动恢复", "warning"
        detail = automatic.message
    else:
        status, status_kind = _STATUS_VIEW[room.status]
        detail = _room_detail(room, snapshot, reader)
    return RoomRowView(
        index=room.index,
        room_id=room.room_id,
        name=room.name,
        platform=room.platform,
        status=status,
        status_kind=status_kind,
        quality=room.quality,
        progress=_room_progress(room),
        detail=detail,
    )


def _build_incident_row(incident: DashboardIncident, snapshot: DashboardSnapshot) -> IncidentRowView:
    room_name = next((room.name for room in snapshot.rooms if room.room_id == incident.room_id), "系统")
    detail_parts: list[str] = []
    if incident.retry_attempt is not None:
        retry = str(incident.retry_attempt)
        if incident.retry_limit is not None:
            retry = f"{retry}/{incident.retry_limit}"
        detail_parts.append(f"重试 {retry}")
    if incident.next_retry_at is not None:
        remaining = max(0, int((incident.next_retry_at - snapshot.current_time).total_seconds()))
        detail_parts.append(f"下次 {remaining // 60:02d}:{remaining % 60:02d}")
    duration = max(0, int((snapshot.current_time - incident.started_at).total_seconds()))
    detail_parts.append(f"持续 {_human_duration(duration)}")
    return IncidentRowView(
        disposition=incident.disposition.value,
        kind="danger" if incident.disposition is AttentionDisposition.ACTION_REQUIRED else "warning",
        room_name=room_name,
        message=incident.message,
        detail=" · ".join(detail_parts),
    )


def _build_event_row(event: DashboardEvent, snapshot: DashboardSnapshot) -> EventRowView:
    room_name = next((room.name for room in snapshot.rooms if room.room_id == event.room_id), "系统")
    label, kind = _EVENT_VIEW.get(event.event_type, ("状态变化", "normal"))
    details = dict(event.details)
    suffix = [details[key] for key in ("size", "duration") if details.get(key)]
    detail = " · ".join((event.message, *suffix))
    if event.occurrences > 1:
        detail = f"{detail} ×{event.occurrences}"
    return EventRowView(
        time=f"{event.at:%H:%M:%S}",
        label=label,
        kind=kind,
        room_name=room_name,
        detail=detail,
    )


def _room_progress(room: DashboardRoom) -> str:
    if room.status is RoomDisplayStatus.RECORDING:
        return _format_duration(room.elapsed_seconds or 0)
    if room.status is RoomDisplayStatus.CONVERTING:
        percent = f"{room.progress_percent:.1f}%" if room.progress_percent is not None else "--.-%"
        return f"{percent} {_format_duration(room.elapsed_seconds or 0)}"
    return "—"


def _room_detail(room: DashboardRoom, snapshot: DashboardSnapshot, reader: RecordingStatsReader) -> str:
    if room.status is RoomDisplayStatus.WAITING:
        return "等待首次检测"
    if room.status is RoomDisplayStatus.PROBING:
        return "正在首次检测"
    if room.status is RoomDisplayStatus.MONITORING:
        if room.last_checked_at is None:
            return "等待首次检测"
        elapsed = max(0, int((snapshot.current_time - room.last_checked_at).total_seconds()))
        remaining = max(0, snapshot.config.poll_seconds - elapsed)
        return f"下次检测 {remaining // 60:02d}:{remaining % 60:02d}"
    if room.status is RoomDisplayStatus.RECORDING:
        try:
            stats = reader(room)
        except (OSError, ValueError):
            stats = None
        if stats is not None:
            return f"{_format_bytes(stats.size_bytes)} · {stats.bitrate_mbps:.1f} Mbps"
        filename = Path(room.output_path).name if room.output_path else ""
        return f"{filename} · 正在写入" if filename else "正在写入"
    if room.status is RoomDisplayStatus.CONVERTING:
        return room.task_name or "正在转码"
    if room.status is RoomDisplayStatus.RETRYING:
        return room.last_error or "等待重试"
    return "配置已停用"


def read_recording_stats(room: DashboardRoom) -> RecordingStats | None:
    if not room.output_path:
        return None
    pattern = room.output_path
    path = Path(pattern)
    if "%03d" in pattern:
        glob_path = Path(pattern.replace("%03d", "*"))
        files = tuple(candidate for candidate in glob_path.parent.glob(glob_path.name) if candidate.is_file())
    else:
        files = (path,) if path.is_file() else ()
    if not files:
        return None
    size = sum(candidate.stat().st_size for candidate in files)
    elapsed = max(1.0, room.elapsed_seconds or 0)
    return RecordingStats(size_bytes=size, bitrate_mbps=size * 8 / elapsed / 1_000_000)


def _config_items(config: DashboardConfig, upload: DashboardUploadStatus | None = None) -> tuple[str, ...]:
    save_format = (
        f"{config.save_format} → MP4"
        if config.save_format.upper() == "TS" and config.convert_to_mp4
        else config.save_format
    )
    split = "关闭" if not config.split_seconds else _human_duration(config.split_seconds)
    items = [
        save_format,
        config.quality,
        f"分段 {split}",
        f"检测 {config.poll_seconds} 秒",
        f"并发 {config.max_requests}",
        f"代理 {'开' if config.use_proxy else '关'}",
    ]
    if upload is not None and upload.enabled:
        items.append(f"上传 {_upload_phase_label(upload.phase)} {upload.trigger} → {upload.target}")
    return tuple(items)


def _upload_health(upload: DashboardUploadStatus) -> HealthView:
    if not upload.enabled:
        return HealthView("上传", "关闭", True)
    labels = {
        "idle": "空闲",
        "running": "运行中",
        "success": "完成",
        "partial": "部分完成",
        "skipped": "无文件",
        "failed": "异常",
        "disabled": "关闭",
    }
    return HealthView("上传", labels.get(upload.phase, upload.phase or "未知"), upload.phase != "failed")


def _upload_detail(upload: DashboardUploadStatus) -> str:
    parts = [part for part in (upload.trigger, upload.target, upload.detail) if part]
    if upload.retry_limit:
        parts.append(f"重试 {upload.attempts}/{upload.retry_limit}")
    detail = " · ".join(parts)
    if upload.records:
        rows = [
            "最近记录",
            *(
                f"{record.at:%H:%M:%S} {_upload_phase_label(record.phase)} "
                f"{_upload_record_stats(record)}{record.message}".strip()
                for record in upload.records[:5]
            ),
        ]
        return "\n".join((detail, *rows)) if detail else "\n".join(rows)
    return detail


def _upload_phase_label(phase: str) -> str:
    labels = {
        "idle": "空闲",
        "running": "运行中",
        "success": "完成",
        "partial": "部分完成",
        "skipped": "无文件",
        "failed": "异常",
        "disabled": "关闭",
    }
    return labels.get(phase, phase or "未知")


def _upload_record_stats(record) -> str:
    if record.files_total <= 0:
        return ""
    summary = f"{record.files_total} 个文件 / {_format_bytes(record.bytes_total)}"
    if record.files_remaining:
        summary = (
            f"{summary}，剩余 {record.files_remaining} 个 / "
            f"{_format_bytes(record.bytes_remaining)}"
        )
    return f"{summary}，"


def _first_sweep(snapshot: DashboardSnapshot) -> str | None:
    if (
        snapshot.first_sweep_total > 0
        and snapshot.first_sweep_completed_at is None
        and snapshot.first_sweep_completed < snapshot.first_sweep_total
    ):
        return f"首次巡检 {snapshot.first_sweep_completed}/{snapshot.first_sweep_total}"
    return None


def _format_duration(seconds: float) -> str:
    total = max(0, int(seconds))
    hours, remainder = divmod(total, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


def _human_duration(seconds: int) -> str:
    if seconds >= 3600 and seconds % 3600 == 0:
        return f"{seconds // 3600} 小时"
    if seconds >= 60 and seconds % 60 == 0:
        return f"{seconds // 60} 分钟"
    return f"{seconds} 秒"


def _format_bytes(size: int) -> str:
    if size < 1_000_000:
        return f"{size / 1_000:.1f} KB"
    if size < 1_000_000_000:
        return f"{size / 1_000_000:.1f} MB"
    return f"{size / 1_000_000_000:.1f} GB"
