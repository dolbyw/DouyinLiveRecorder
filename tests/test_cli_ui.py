from dataclasses import replace
from datetime import UTC, datetime, timedelta
from io import StringIO
from pathlib import Path

from rich.console import Console

import src.cli_ui as cli_ui
from src.cli_ui import (
    RichDashboard,
    build_dashboard_renderable,
    build_plain_dashboard,
    format_conversion_progress,
    print_ffmpeg_summary,
    print_startup_banner,
    supports_rich_dashboard,
)
from src.dashboard_state import (
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
from src.dashboard_view import RoomListMode, build_dashboard_view
from src.recorder import ConversionProgress


def test_print_startup_banner_renders_version_and_platforms():
    buffer = StringIO()
    console = Console(file=buffer, force_terminal=False, width=120)

    rendered = print_startup_banner("v4.0.8", "国内站点：抖音", console=console)

    assert rendered is True
    assert "v4.0.8" in buffer.getvalue()
    assert "国内站点：抖音" in buffer.getvalue()


def test_print_ffmpeg_summary_renders_detected_version():
    buffer = StringIO()
    console = Console(file=buffer, force_terminal=False, width=120)

    rendered = print_ffmpeg_summary("ffmpeg version 8.1.1", "built with gcc", console=console)

    assert rendered is True
    assert "ffmpeg version 8.1.1" in buffer.getvalue()
    assert "built with gcc" in buffer.getvalue()


def test_format_conversion_progress_includes_file_position_percent_and_times():
    progress = ConversionProgress(Path("主播_001.ts"), 72, 152)

    assert format_conversion_progress(progress, 2, 3) == (
        "[转MP4 2/3] 主播_001.ts 47.4%  00:01:12 / 00:02:32"
    )


def test_format_conversion_progress_handles_unknown_duration():
    progress = ConversionProgress(Path("a.ts"), 4, None)

    assert format_conversion_progress(progress, 1, 1) == (
        "[转MP4 1/1] a.ts --.-%  00:00:04 / --:--:--"
    )


def dashboard_snapshot() -> DashboardSnapshot:
    now = datetime(2026, 6, 23, 8, 16, 24, tzinfo=UTC)
    rooms = (
        DashboardRoom(
            "room-1",
            1,
            "招财",
            "抖音",
            "原画",
            RoomDisplayStatus.MONITORING,
            last_checked_at=now - timedelta(seconds=42),
        ),
        DashboardRoom(
            "room-2",
            2,
            "嘉嘉",
            "抖音",
            "原画",
            RoomDisplayStatus.RECORDING,
            elapsed_seconds=493,
        ),
        DashboardRoom(
            "room-3",
            3,
            "小鹿",
            "B站",
            "高清",
            RoomDisplayStatus.CONVERTING,
            task_name="小鹿_000.ts",
            progress_percent=47.4,
            elapsed_seconds=72,
            duration_seconds=152,
        ),
    )
    return DashboardSnapshot(
        config=DashboardConfig(
            save_format="TS",
            quality="原画",
            split_seconds=1800,
            poll_seconds=300,
            max_requests=3,
            use_proxy=True,
            convert_to_mp4=True,
            save_path="D:/downloads",
            disk_free_gb=463.9,
            recordings_size_bytes=128_600_000_000,
        ),
        rooms=rooms,
        events=(DashboardEvent("room-2", "recording_started", "开始录制", now),),
        incidents=(
            DashboardIncident(
                "room-1",
                "permission",
                "保存目录没有写入权限",
                AttentionDisposition.ACTION_REQUIRED,
                now - timedelta(seconds=16),
                now,
            ),
        ),
        current_time=now,
        started_at=datetime(2026, 6, 23, 8, 0, tzinfo=UTC),
    )


def dashboard_view(width=140, height=42, mode=RoomListMode.COMPACT):
    return build_dashboard_view(dashboard_snapshot(), width=width, height=height, room_mode=mode)


def render(view, *, width):
    buffer = StringIO()
    console = Console(file=buffer, force_terminal=False, width=width)
    console.print(build_dashboard_renderable(view))
    return buffer.getvalue()


def panel_text(output: str, title: str) -> str:
    lines = output.splitlines()
    start = next(index for index, line in enumerate(lines) if title in line)
    end = next(
        (index for index in range(start + 1, len(lines)) if lines[index].startswith("└")),
        len(lines),
    )
    return "\n".join(lines[start:end])


def test_wide_dashboard_matches_approved_full_width_hierarchy():
    assert supports_rich_dashboard() is True

    output = render(dashboard_view(), width=140)

    for text in (
        "DouyinLiveRecorder",
        "运行正常",
        "直播间",
        "录制中",
        "等待开播",
        "需处理",
        "录制目录",
        "磁盘剩余",
        "TS → MP4",
        "[R] 展开",
        "最近动态",
        "技术日志",
        "保存目录没有写入权限",
    ):
        assert text in output
    assert "最近事件" not in output


def test_wide_dashboard_uses_left_aligned_section_titles_and_labeled_config():
    snapshot = replace(
        dashboard_snapshot(),
        config=replace(
            dashboard_snapshot().config,
            save_path="D:/Projects/DouyinLiveRecorder-main/dist/DouyinLiveRecorder/downloads",
        ),
        upload=DashboardUploadStatus(
            enabled=True,
            phase="idle",
            trigger="录制结束",
            target="123pan:/LiveBackup/",
        ),
    )
    view = build_dashboard_view(snapshot, width=140, height=42, room_mode=RoomListMode.COMPACT)

    output = render(view, width=140)

    assert "┤ 直播间" not in output
    assert "┤ 最近动态" not in output
    assert "配置" in output
    assert "本地保存" in output
    assert "自动上传 · [U] 展开" in output
    assert "计划：文件完成后上传到 123pan:/LiveBackup/" in output
    config_panel = panel_text(output, "配置")
    assert "上传 文件完成后" in config_panel
    assert "远端 123pan" in config_panel
    assert "远端目录 /LiveBackup" in config_panel
    assert "本地保存" in config_panel
    assert "D:/Projects/DouyinLiveRecorder-main/dist/DouyinLiveRecorder/downloads" in config_panel
    assert "..." not in config_panel


def test_collapsed_upload_status_has_discoverable_u_hint_without_header_wrap():
    snapshot = replace(
        dashboard_snapshot(),
        upload=DashboardUploadStatus(
            enabled=True,
            phase="idle",
            trigger="录制结束",
            target="123pan:/LiveBackup/",
            detail="等待新的已完成文件",
        ),
    )
    view = build_dashboard_view(snapshot, width=140, height=42, room_mode=RoomListMode.COMPACT)

    output = render(view, width=140)

    assert "自动上传 · [U] 展开" in output
    assert "计划：文件完成后上传到 123pan:/LiveBackup/" in output
    assert "状态：等待新的已完成文件" in output
    assert "✓ 上传" not in panel_text(output, "DouyinLiveRecorder")


def test_medium_dashboard_merges_quality_into_detail():
    output = render(dashboard_view(width=100), width=100)

    assert "名称 / 平台" in output
    assert "状态" in output
    assert "等待开播" in output
    assert "质量" not in output
    assert "原画" in output


def test_narrow_dashboard_keeps_full_actionable_message():
    output = render(dashboard_view(width=72, height=24), width=72)

    assert "需要处理" in output
    assert "保存目录没有写入权限" in output
    assert "最近动态" in output


def test_expanded_room_title_changes_toggle_hint():
    output = render(dashboard_view(mode=RoomListMode.EXPANDED), width=140)

    assert "[R] 收起" in output


def test_expanded_upload_detail_renders_system_upload_panel():
    snapshot = replace(
        dashboard_snapshot(),
        upload=DashboardUploadStatus(
            enabled=True,
            phase="running",
            trigger="定时03:00",
            target="123pan:/LiveBackup/",
            detail="第 1/4 次上传",
        ),
    )
    view = build_dashboard_view(
        snapshot,
        width=140,
        height=42,
        room_mode=RoomListMode.COMPACT,
        upload_detail_expanded=True,
    )

    output = render(view, width=140)

    assert "自动上传" in output
    assert "[U] 收起" in output
    assert "123pan:/LiveBackup/" in output


def test_plain_dashboard_uses_same_view_without_sensitive_fields():
    output = build_plain_dashboard(dashboard_view(width=100))

    assert "招财" in output
    assert "需要处理" in output
    assert "最近动态" in output
    for secret in ("cookie", "token", "密码"):
        assert secret not in output.lower()


def test_first_sweep_and_complete_prompt_are_preserved():
    base = dashboard_snapshot()
    snapshot = replace(
        base,
        phase=AppDisplayPhase.COMPLETE,
        first_sweep_total=15,
        first_sweep_started=7,
        first_sweep_completed=6,
    )
    view = build_dashboard_view(snapshot, width=140, height=42, room_mode=RoomListMode.COMPACT)
    output = render(view, width=140)

    assert "首次巡检 6/15" in output
    assert "上传仍会继续" in output
    assert "再次按 Ctrl+C 停止上传并退出" in output


def test_dashboard_updates_one_live_instance_without_redirecting_streams(monkeypatch):
    created = []

    class FakeLive:
        def __init__(self, _renderable, **kwargs):
            self.redirect_stdout = kwargs["redirect_stdout"]
            self.redirect_stderr = kwargs["redirect_stderr"]
            self.screen = kwargs["screen"]
            self.update_count = 0
            created.append(self)

        def start(self, *, refresh):
            assert refresh is True

        def update(self, _renderable, *, refresh):
            assert refresh is True
            self.update_count += 1

        def stop(self):
            pass

    monkeypatch.setattr(cli_ui, "Live", FakeLive)
    dashboard = RichDashboard(console=Console(file=StringIO(), force_terminal=False, width=120))
    view = dashboard_view(width=120)

    dashboard.start()
    dashboard.update(view)
    dashboard.update(view)
    dashboard.stop()

    assert len(created) == 1
    assert created[0].redirect_stdout is False
    assert created[0].redirect_stderr is False
    assert created[0].screen is True
    assert created[0].update_count == 2
