from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from src.dashboard_state import (
    AppDisplayPhase,
    AttentionDisposition,
    DashboardConfig,
    DashboardEvent,
    DashboardIncident,
    DashboardRoom,
    DashboardSnapshot,
    DashboardUploadRecord,
    DashboardUploadStatus,
    RoomDisplayStatus,
)
from src.dashboard_view import RoomListMode, ViewWidth, allocate_rows, build_dashboard_view

NOW = datetime(2026, 6, 24, 21, 39, 26, tzinfo=UTC)


def make_room(index: int, status: RoomDisplayStatus = RoomDisplayStatus.MONITORING) -> DashboardRoom:
    return DashboardRoom(
        room_id=f"room-{index}",
        index=index,
        name=f"主播{index}",
        platform="抖音",
        quality="原画",
        status=status,
        last_checked_at=NOW - timedelta(seconds=index * 5),
    )


@pytest.fixture
def snapshot() -> DashboardSnapshot:
    rooms = tuple(make_room(index) for index in range(1, 9))
    rooms = (
        replace(rooms[0], status=RoomDisplayStatus.RECORDING, elapsed_seconds=12),
        replace(rooms[1], status=RoomDisplayStatus.RETRYING, last_error="自动重试中"),
        *rooms[2:],
    )
    incidents = (
        DashboardIncident(
            "room-3",
            "permission",
            "保存目录没有写入权限",
            AttentionDisposition.ACTION_REQUIRED,
            NOW - timedelta(minutes=2),
            NOW,
        ),
        DashboardIncident(
            "room-2",
            "probe",
            "连接中断",
            AttentionDisposition.AUTOMATIC,
            NOW - timedelta(seconds=16),
            NOW,
            retry_attempt=2,
            retry_limit=5,
            next_retry_at=NOW + timedelta(seconds=14),
        ),
    )
    events = tuple(
        DashboardEvent(
            room_id=f"room-{index}",
            event_type="recording_started",
            message="开始录制",
            at=NOW - timedelta(seconds=index),
        )
        for index in range(1, 9)
    )
    return DashboardSnapshot(
        config=DashboardConfig(
            save_format="TS",
            quality="原画",
            split_seconds=3600,
            poll_seconds=300,
            max_requests=5,
            use_proxy=True,
            convert_to_mp4=True,
            save_path="D:/downloads",
            disk_free_gb=424.3,
        ),
        rooms=rooms,
        events=events,
        incidents=incidents,
        current_time=NOW,
        started_at=NOW - timedelta(hours=4, minutes=38, seconds=26),
    )


@pytest.mark.parametrize(
    ("width", "expected"),
    [(79, ViewWidth.NARROW), (80, ViewWidth.MEDIUM), (119, ViewWidth.MEDIUM), (120, ViewWidth.WIDE)],
)
def test_width_boundaries(snapshot, width, expected):
    view = build_dashboard_view(snapshot, width=width, height=40, room_mode=RoomListMode.COMPACT)

    assert view.width_mode is expected


def test_compact_rooms_prioritize_attention_then_active_statuses(snapshot):
    view = build_dashboard_view(snapshot, width=140, height=28, room_mode=RoomListMode.COMPACT)

    assert [(row.name, row.status) for row in view.rooms[:3]] == [
        ("主播3", "需要处理"),
        ("主播2", "自动恢复"),
        ("主播1", "录制"),
    ]


def test_expanded_mode_shows_more_rooms_without_hiding_minimum_events(snapshot):
    snapshot = replace(
        snapshot,
        rooms=(*snapshot.rooms, *(make_room(index) for index in range(9, 16))),
    )
    compact = build_dashboard_view(snapshot, width=140, height=30, room_mode=RoomListMode.COMPACT)
    expanded = build_dashboard_view(snapshot, width=140, height=30, room_mode=RoomListMode.EXPANDED)

    assert len(expanded.rooms) > len(compact.rooms)
    assert len(expanded.events) >= 3
    assert expanded.hidden_room_count == len(snapshot.rooms) - len(expanded.rooms)


def test_row_budget_keeps_all_incidents_and_three_events():
    budget = allocate_rows(
        height=32,
        incident_count=2,
        room_count=15,
        event_count=8,
        room_mode=RoomListMode.COMPACT,
    )

    assert budget.incident_rows == 2
    assert budget.event_rows >= 3


def test_incident_rows_explain_actionability_and_retry(snapshot):
    view = build_dashboard_view(snapshot, width=140, height=40, room_mode=RoomListMode.COMPACT)

    actionable, automatic = view.incidents
    assert actionable.disposition == "需要处理"
    assert actionable.room_name == "主播3"
    assert automatic.disposition == "自动恢复"
    assert "2/5" in automatic.detail
    assert "下次 00:14" in automatic.detail
    assert "持续 16 秒" in automatic.detail


def test_correlated_event_formats_final_result(snapshot):
    event = DashboardEvent(
        "room-1",
        "conversion_finished",
        "录制完成并转为 MP4",
        NOW,
        correlation_id="recording-42",
        details=(("duration", "00:35:26"), ("format", "MP4"), ("size", "1.2 GB")),
    )
    snapshot = replace(snapshot, events=(event,), phase=AppDisplayPhase.RUNNING)

    view = build_dashboard_view(snapshot, width=140, height=40, room_mode=RoomListMode.COMPACT)

    assert view.events[0].label == "处理完成"
    assert view.events[0].room_name == "主播1"
    assert view.events[0].detail == "录制完成并转为 MP4 · 1.2 GB · 00:35:26"


def test_complete_phase_exposes_existing_exit_prompt(snapshot):
    snapshot = replace(snapshot, phase=AppDisplayPhase.COMPLETE)

    view = build_dashboard_view(snapshot, width=140, height=40, room_mode=RoomListMode.COMPACT)

    assert view.complete_prompt == "按任意键退出 | Ctrl+C 强制退出"


def test_recording_detail_sums_segments_and_calculates_bitrate(snapshot, tmp_path):
    first = tmp_path / "主播_000.ts"
    second = tmp_path / "主播_001.ts"
    first.write_bytes(b"x" * 1_000_000)
    second.write_bytes(b"x" * 1_000_000)
    recording = replace(
        snapshot.rooms[0],
        status=RoomDisplayStatus.RECORDING,
        output_path=str(tmp_path / "主播_%03d.ts"),
        elapsed_seconds=4,
    )
    snapshot = replace(snapshot, rooms=(recording, *snapshot.rooms[1:]), incidents=())

    view = build_dashboard_view(snapshot, width=140, height=40, room_mode=RoomListMode.COMPACT)

    assert view.rooms[0].detail == "2.0 MB · 4.0 Mbps"


def test_dashboard_health_shows_used_and_remaining_disk(snapshot):
    snapshot = replace(
        snapshot,
        config=replace(
            snapshot.config,
            recordings_size_bytes=128_600_000_000,
            disk_free_gb=424.3,
        ),
    )

    view = build_dashboard_view(snapshot, width=140, height=40, room_mode=RoomListMode.COMPACT)

    assert [(item.label, item.value) for item in view.health[:3]] == [
        ("FFmpeg", "正常"),
        ("已占用", "128.6 GB"),
        ("剩余", "424.3 GB"),
    ]


def test_dashboard_health_shows_unknown_recording_size(snapshot):
    snapshot = replace(
        snapshot,
        config=replace(snapshot.config, recordings_size_bytes=None),
    )

    view = build_dashboard_view(snapshot, width=140, height=40, room_mode=RoomListMode.COMPACT)

    used = next(item for item in view.health if item.label == "已占用")
    assert used.value == "未知"


def test_dashboard_health_and_config_include_auto_upload(snapshot):
    upload = DashboardUploadStatus(
        enabled=True,
        phase="running",
        trigger="定时03:00",
        target="123pan:/LiveBackup/",
        detail="第 1/4 次上传",
    )
    snapshot = replace(snapshot, upload=upload)

    view = build_dashboard_view(snapshot, width=140, height=40, room_mode=RoomListMode.COMPACT)

    upload_health = next(item for item in view.health if item.label == "上传")
    assert upload_health.value == "运行中"
    assert upload_health.healthy is True
    assert "上传 运行中 定时03:00 → 123pan:/LiveBackup/" in view.config_items


def test_dashboard_upload_detail_is_available_when_expanded(snapshot):
    upload = DashboardUploadStatus(
        enabled=True,
        phase="failed",
        trigger="间隔300秒",
        target="123pan:/LiveBackup/",
        detail="webdav timeout",
        attempts=3,
        retry_limit=3,
    )
    snapshot = replace(snapshot, upload=upload)

    view = build_dashboard_view(
        snapshot,
        width=140,
        height=40,
        room_mode=RoomListMode.COMPACT,
        upload_detail_expanded=True,
    )

    assert view.upload_detail == "间隔300秒 · 123pan:/LiveBackup/ · webdav timeout · 重试 3/3"


def test_dashboard_upload_detail_includes_recent_records(snapshot):
    upload = DashboardUploadStatus(
        enabled=True,
        phase="partial",
        trigger="录制结束",
        target="123pan:/LiveBackup/",
        detail="仍有文件等待冷却",
        records=(
            DashboardUploadRecord(
                phase="partial",
                message="部分上传：仍有 1 个文件待上传",
                at=NOW,
                files_total=3,
                files_remaining=1,
                bytes_total=3_000_000,
                bytes_remaining=1_000_000,
            ),
        ),
    )
    snapshot = replace(snapshot, upload=upload)

    view = build_dashboard_view(
        snapshot,
        width=140,
        height=40,
        room_mode=RoomListMode.COMPACT,
        upload_detail_expanded=True,
    )

    assert "最近记录" in view.upload_detail
    assert "部分完成" in view.upload_detail
    assert "3 个文件 / 3.0 MB，剩余 1 个 / 1.0 MB" in view.upload_detail


def test_upload_events_have_specific_labels(snapshot):
    snapshot = replace(snapshot, events=(DashboardEvent("system", "upload_finished", "上传完成", NOW),))

    view = build_dashboard_view(snapshot, width=140, height=40, room_mode=RoomListMode.COMPACT)

    assert view.events[0].label == "上传完成"
    assert view.events[0].room_name == "系统"


def test_recording_detail_survives_missing_output_file(snapshot):
    recording = replace(
        snapshot.rooms[0],
        status=RoomDisplayStatus.RECORDING,
        output_path="Z:/missing/主播.ts",
    )
    snapshot = replace(snapshot, rooms=(recording, *snapshot.rooms[1:]), incidents=())

    view = build_dashboard_view(snapshot, width=140, height=40, room_mode=RoomListMode.COMPACT)

    assert view.rooms[0].detail == "主播.ts · 正在写入"


def test_recording_finished_event_does_not_claim_the_stream_ended(snapshot):
    snapshot = replace(
        snapshot,
        events=(DashboardEvent("room-1", "recording_finished", "录制完成", NOW),),
    )

    view = build_dashboard_view(snapshot, width=140, height=40, room_mode=RoomListMode.COMPACT)

    assert view.events[0].label == "录制结束"
    assert view.events[0].label != "直播结束"


def test_compact_mode_shows_ten_rooms_when_height_allows(snapshot):
    rooms = tuple(make_room(index) for index in range(1, 16))
    snapshot = replace(snapshot, rooms=rooms, incidents=())

    view = build_dashboard_view(snapshot, width=140, height=50, room_mode=RoomListMode.COMPACT)

    assert len(view.rooms) == 10
    assert view.hidden_room_count == 5
