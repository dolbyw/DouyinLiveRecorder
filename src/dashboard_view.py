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
    upload_summary: str | None = None


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
    RoomDisplayStatus.WAITING: ("待检测", "dim"),
    RoomDisplayStatus.PROBING: ("首次检测", "info"),
    RoomDisplayStatus.MONITORING: ("等待开播", "info"),
    RoomDisplayStatus.RECORDING: ("录制中", "success"),
    RoomDisplayStatus.CONVERTING: ("转码中", "warning"),
    RoomDisplayStatus.RETRYING: ("自动重试", "warning"),
    RoomDisplayStatus.DISABLED: ("已停用", "dim"),
}

_EVENT_VIEW = {
    "recording_started": ("录制开始", "success"),
    "recording_finished": ("录制文件完成", "dim"),
    "conversion_started": ("转码开始", "warning"),
    "segment_conversion_watch_started": ("分段监控", "info"),
    "conversion_finished": ("转码完成", "success"),
    "conversion_failed": ("转码失败", "danger"),
    "recording_error": ("录制异常", "danger"),
    "upload_started": ("上传开始", "info"),
    "upload_finished": ("上传完成", "success"),
    "upload_partial": ("上传部分完成", "warning"),
    "upload_failed": ("上传失败", "danger"),
    "upload_skipped": ("没有可上传文件", "dim"),
    "startup_recovery_upload": ("启动补传", "info"),
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
        MetricView(str(snapshot.recording_count), "录制中", "success"),
        MetricView(str(snapshot.monitoring_count), "等待开播", "info"),
        MetricView(str(snapshot.converting_count), "转码中", "warning"),
        MetricView(str(actionable_count), "需处理", "danger" if actionable_count else "success"),
    )
    health = (
        HealthView("FFmpeg", "正常" if snapshot.ffmpeg_ready else "异常", snapshot.ffmpeg_ready),
        HealthView(
            "录制目录",
            _format_bytes(snapshot.config.recordings_size_bytes)
            if snapshot.config.recordings_size_bytes is not None
            else "未知",
            True,
        ),
        HealthView(
            "磁盘剩余",
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
            "上传仍会继续；再次按 Ctrl+C 停止上传并退出"
            if snapshot.phase is AppDisplayPhase.COMPLETE
            else None
        ),
        upload_detail=_upload_detail(snapshot.upload) if upload_detail_expanded and snapshot.upload.enabled else None,
        upload_summary=_upload_summary(snapshot.upload) if snapshot.upload.enabled else None,
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
    detail = " · ".join((_event_detail_text(event), *suffix))
    if event.occurrences > 1:
        detail = f"{detail}，重复 {event.occurrences} 次"
    return EventRowView(
        time=f"{event.at:%H:%M:%S}",
        label=label,
        kind=kind,
        room_name=room_name,
        detail=detail,
    )


def _event_detail_text(event: DashboardEvent) -> str:
    if event.event_type == "recording_started":
        return "已打开直播流，正在写入文件"
    if event.event_type == "recording_finished":
        return "录制文件写入完成"
    if event.event_type == "conversion_started":
        return "分段文件已完成，正在生成 MP4"
    if event.event_type == "segment_conversion_watch_started":
        return event.message
    if event.event_type == "conversion_finished":
        return "录制文件已转为 MP4"
    if event.event_type == "upload_started":
        return "正在上传已完成文件"
    if event.event_type == "startup_recovery_upload":
        return "启动后扫描可补传文件"
    return event.message


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
        return f"{remaining // 60:02d}:{remaining % 60:02d} 后再次检测"
    if room.status is RoomDisplayStatus.RECORDING:
        try:
            stats = reader(room)
        except (OSError, ValueError):
            stats = None
        if stats is not None:
            return f"已写入 {_format_bytes(stats.size_bytes)} · 平均 {stats.bitrate_mbps:.1f} Mbps"
        filename = Path(room.output_path).name if room.output_path else ""
        return f"正在写入 {filename}" if filename else "正在写入文件"
    if room.status is RoomDisplayStatus.CONVERTING:
        return f"正在生成 MP4：{room.task_name}" if room.task_name else "正在生成 MP4"
    if room.status is RoomDisplayStatus.RETRYING:
        return room.last_error or "等待自动重试"
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
        f"检测间隔 {config.poll_seconds} 秒",
        f"并发 {config.max_requests}",
        f"代理 {'开' if config.use_proxy else '关'}",
    ]
    if upload is not None and upload.enabled:
        items.extend(_upload_config_items(upload))
    return tuple(items)


def _upload_config_items(upload: DashboardUploadStatus) -> tuple[str, ...]:
    items = [f"上传 {_short_upload_trigger(upload.trigger)}"]
    remote = _upload_remote_name(upload.target)
    if remote:
        items.append(f"远端 {remote}")
    target = _upload_target_path(upload.target)
    if target:
        items.append(f"远端目录 {target}")
    return tuple(items)


def _short_upload_trigger(trigger: str) -> str:
    if trigger == "录制结束":
        return "文件完成后"
    if trigger.startswith("间隔"):
        return trigger.replace("秒", "s")
    if trigger.startswith("定时"):
        return trigger.replace("定时", "")
    return trigger or "-"


def _upload_remote_name(target: str) -> str:
    return target.split(":", maxsplit=1)[0].strip() if ":" in target else ""


def _upload_target_path(target: str) -> str:
    if ":" not in target:
        return target.strip()
    path = target.split(":", maxsplit=1)[1].strip()
    return f"/{path.strip('/')}" if path.strip("/") else "/"


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
    lines = [_upload_plan_text(upload), _upload_status_text(upload)]
    overall = _upload_overall_text(upload)
    if overall:
        lines.append(overall)
    if upload.active_transfers:
        lines.append("正在上传：")
        lines.extend(_upload_transfer_line(transfer) for transfer in upload.active_transfers[:4])
    if upload.records:
        lines.append("最近上传：")
        lines.extend(_upload_record_line(record) for record in upload.records[:8])
    return "\n".join(lines)


def _upload_summary(upload: DashboardUploadStatus) -> str:
    return "\n".join((_upload_plan_text(upload), _upload_status_text(upload)))


def _upload_phase_label(phase: str) -> str:
    labels = {
        "idle": "等待文件",
        "running": "上传中",
        "success": "上传完成",
        "partial": "上传部分完成，待重试",
        "skipped": "没有可上传文件",
        "failed": "上传失败",
        "disabled": "已关闭",
    }
    return labels.get(phase, phase or "未知状态")


def _upload_plan_text(upload: DashboardUploadStatus) -> str:
    trigger = upload.trigger
    if trigger == "录制结束":
        return f"计划：文件完成后上传到 {upload.target}"
    if trigger.startswith("间隔"):
        seconds = trigger.removeprefix("间隔").removesuffix("秒")
        return f"计划：每 {seconds} 秒检查并上传到 {upload.target}"
    if trigger.startswith("定时"):
        time_text = trigger.removeprefix("定时")
        return f"计划：每天 {time_text} 上传到 {upload.target}"
    return f"计划：上传到 {upload.target}" if upload.target else "计划：自动上传"


def _upload_status_text(upload: DashboardUploadStatus) -> str:
    if upload.phase == "idle" and upload.detail in {"等待录制结束", "等待新的已完成文件", ""}:
        return "状态：等待新的已完成文件"
    label = _upload_phase_label(upload.phase)
    parts = [label]
    detail = _upload_status_detail(upload)
    if detail and detail != label:
        parts.append(detail)
    if upload.retry_limit:
        parts.append(f"重试 {upload.attempts}/{upload.retry_limit}")
    return f"状态：{'，'.join(parts)}"


def _upload_status_detail(upload: DashboardUploadStatus) -> str:
    detail = _friendly_upload_message(upload.detail)
    if upload.phase == "running" and (
        upload.files_total
        or upload.bytes_transferred is not None
        or upload.bytes_total is not None
        or upload.speed_bytes_per_second is not None
        or upload.active_transfers
    ):
        return ""
    return detail


def _upload_overall_text(upload: DashboardUploadStatus) -> str:
    parts: list[str] = []
    if upload.files_total:
        files_done = min(upload.files_total, max(0, upload.files_done))
        parts.append(f"{files_done}/{upload.files_total} 文件")
    if upload.bytes_transferred is not None and upload.bytes_total is not None:
        parts.append(f"{_format_bytes(upload.bytes_transferred)} / {_format_bytes(upload.bytes_total)}")
    elif upload.bytes_transferred is not None:
        parts.append(_format_bytes(upload.bytes_transferred))
    if upload.speed_bytes_per_second is not None:
        parts.append(f"{_format_bytes(upload.speed_bytes_per_second)}/s")
    if upload.files_waiting:
        parts.append(f"等待 {upload.files_waiting} 个")
    return f"总体：{' · '.join(parts)}" if parts else ""


def _upload_transfer_line(transfer) -> str:
    parts: list[str] = []
    if getattr(transfer, "streamer", ""):
        parts.append(transfer.streamer)
    if getattr(transfer, "file_name", ""):
        parts.append(transfer.file_name)
    elif getattr(transfer, "relative_path", ""):
        parts.append(Path(transfer.relative_path).name)
    if transfer.percent is not None:
        parts.append(f"{transfer.percent:.1f}%")
    if transfer.speed_bytes_per_second is not None:
        parts.append(f"{_format_bytes(transfer.speed_bytes_per_second)}/s")
    if transfer.bytes_transferred is not None and transfer.total_bytes is not None:
        parts.append(f"{_format_bytes(transfer.bytes_transferred)} / {_format_bytes(transfer.total_bytes)}")
    elif transfer.bytes_transferred is not None:
        parts.append(_format_bytes(transfer.bytes_transferred))
    return " · ".join(parts) or "上传中"


def _upload_record_line(record) -> str:
    parts = [f"{record.at:%H:%M:%S} {_upload_phase_label(record.phase)}"]
    if getattr(record, "streamer", ""):
        parts.append(record.streamer)
    if getattr(record, "file_name", ""):
        parts.append(record.file_name)
    stats = _upload_record_stats(record).strip("，")
    if stats:
        parts.append(stats)
    message = _normalized_upload_record_message(record)
    if message:
        parts.append(message)
    return " · ".join(parts)


def _normalized_upload_record_message(record) -> str:
    message = _friendly_upload_message(record.message)
    if not message or message.lower() == "upload completed":
        return ""
    if message == _upload_phase_label(record.phase):
        return ""
    return message


def _friendly_upload_message(message: str) -> str:
    message = str(message or "").strip()
    prefix = "source has no files:"
    if message.lower().startswith(prefix):
        source = message[len(prefix):].strip()
        source_name = _last_path_name(source)
        return f"没有找到可上传文件：{source_name}" if source_name else "没有找到可上传文件"
    return message


def _last_path_name(path_text: str) -> str:
    stripped = path_text.strip().strip('"').strip("'").rstrip("\\/")
    if not stripped:
        return ""
    normalized = stripped.replace("\\", "/")
    return normalized.rsplit("/", maxsplit=1)[-1] or stripped


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
