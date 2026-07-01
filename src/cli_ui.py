from __future__ import annotations

import threading
from typing import Any

from .dashboard_view import DashboardView, RoomListMode, ViewWidth
from .recorder.converter import ConversionProgress

try:
    from rich.console import Console, Group
    from rich.live import Live
    from rich.panel import Panel
    from rich.table import Table
    from rich.text import Text
except ImportError:  # pragma: no cover - exercised via fallback path
    Console = None  # type: ignore[assignment]
    Group = None  # type: ignore[assignment]
    Live = None  # type: ignore[assignment]
    Panel = None  # type: ignore[assignment]
    Table = None  # type: ignore[assignment]
    Text = None  # type: ignore[assignment]


_KIND_STYLES = {
    "normal": "white",
    "dim": "dim",
    "info": "cyan",
    "success": "green",
    "warning": "yellow",
    "danger": "bold red",
}


def supports_rich_dashboard() -> bool:
    return all(component is not None for component in (Console, Group, Live, Panel, Table, Text))


def _make_console(console: Console | None = None) -> Console | None:
    if not supports_rich_dashboard():
        return None
    return console if console is not None else Console()


def print_startup_banner(version: str, platforms: str, console: Console | None = None) -> bool:
    rich_console = _make_console(console)
    if rich_console is None:
        return False
    meta = Table.grid(expand=True)
    meta.add_row(Text("DouyinLiveRecorder", style="bold cyan"))
    meta.add_row(Text(f"版本号: {version}", style="bold white"))
    meta.add_row(Text("GitHub: https://github.com/ihmily/DouyinLiveRecorder", style="cyan"))
    meta.add_row(Text(platforms.strip(), style="white"))
    rich_console.print(Panel(meta, title="直播录制控制台", border_style="cyan", padding=(1, 2)))
    return True


def print_ffmpeg_summary(version_line: str, built_line: str, console: Console | None = None) -> bool:
    rich_console = _make_console(console)
    if rich_console is None:
        return False
    summary = Table.grid(expand=True)
    summary.add_row(Text(version_line, style="bold green"))
    summary.add_row(Text(built_line, style="dim"))
    rich_console.print(Panel(summary, title="FFmpeg", border_style="green"))
    return True


def _format_media_time(seconds: float) -> str:
    total_seconds = max(0, int(seconds))
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


def format_conversion_progress(progress: ConversionProgress, index: int, total: int) -> str:
    percent = f"{progress.percent:.1f}%" if progress.percent is not None else "--.-%"
    duration = _format_media_time(progress.duration) if progress.duration is not None else "--:--:--"
    elapsed = _format_media_time(progress.elapsed)
    return f"[转MP4 {index}/{total}] {progress.source.name} {percent}  {elapsed} / {duration}"


def build_dashboard_renderable(view: DashboardView) -> Any:
    if not supports_rich_dashboard():
        return ""
    items: list[Any] = [_render_header(view), _render_config(view), _render_rooms(view), _render_activity(view)]
    if view.upload_detail or view.upload_summary:
        items.insert(3, _render_upload(view))
    if view.complete_prompt:
        items.append(
            Panel(
                Text(view.complete_prompt, style="bold green", justify="center"),
                border_style="green",
                title_align="left",
                padding=(0, 1),
            )
        )
    return Group(*items)


def _render_upload(view: DashboardView) -> Any:
    expanded = bool(view.upload_detail)
    return Panel(
        Text(view.upload_detail or view.upload_summary or "", style="cyan"),
        title=Text(f"自动上传 · [U] {'收起' if expanded else '展开'}", style="bold white"),
        border_style="bright_black",
        title_align="left",
        padding=(0, 1),
    )


def _render_header(view: DashboardView) -> Any:
    header = Table.grid(expand=True)
    header.add_column(ratio=2)
    header.add_column(justify="right", ratio=2)
    title = Text(view.title, style="bold white")
    title.append(f"  ● {view.phase}", style=_phase_style(view.phase))
    header.add_row(title, Text(f"{view.current_time}   已运行 {view.uptime}", style="dim"))

    core_health = tuple(item for item in view.health if item.label != "上传")
    header.add_row(_metrics_text(view), _health_text(core_health))
    if view.first_sweep:
        header.add_row(Text(view.first_sweep, style="cyan"), Text(""))
    return Panel(header, border_style="bright_black", title_align="left", padding=(0, 1))


def _render_config(view: DashboardView) -> Any:
    content = Table.grid(expand=True)
    content.add_column(no_wrap=True, overflow="ellipsis")
    summary = Text(" · ".join(view.config_items), style="dim", no_wrap=True, overflow="ellipsis")
    save_path = Text()
    save_path.append("本地保存 ", style="dim")
    save_path.append(view.save_path, style="white")
    content.add_row(summary)
    content.add_row(save_path)
    return Panel(
        content,
        title=Text("配置", style="bold white"),
        border_style="bright_black",
        title_align="left",
        padding=(0, 1),
    )


def _render_rooms(view: DashboardView) -> Any:
    toggle = "收起" if view.room_mode is RoomListMode.EXPANDED else "展开"
    title = Text(f"直播间  已显示 {len(view.rooms)}/{view.total_room_count} · [R] {toggle}", style="bold white")
    if view.width_mode is ViewWidth.NARROW:
        content = Table.grid(expand=True, padding=(0, 1))
        content.add_column(ratio=1)
        for room in view.rooms:
            line = Text()
            line.append(f"{room.index:>2}  {room.name} · {room.platform}  ")
            line.append(room.status, style=_KIND_STYLES[room.status_kind])
            line.append(f"  {room.progress}  {room.detail}", style="dim")
            content.add_row(line)
    else:
        content = Table(expand=True, show_header=True, header_style="dim", box=None, padding=(0, 1))
        content.add_column("#", width=3, justify="right")
        content.add_column(
            "名称 / 平台",
            width=38 if view.width_mode is ViewWidth.WIDE else 28,
            overflow="ellipsis",
            no_wrap=True,
        )
        content.add_column("状态", width=12)
        if view.width_mode is ViewWidth.WIDE:
            content.add_column("质量", width=6)
        content.add_column("时长 / 进度", width=14, overflow="ellipsis", no_wrap=True)
        content.add_column("当前信息", ratio=3, overflow="ellipsis", no_wrap=True)
        for room in view.rooms:
            detail = room.detail
            row: list[Any] = [
                str(room.index),
                f"{room.name} · {room.platform}",
                Text(f"● {room.status}", style=_KIND_STYLES[room.status_kind]),
            ]
            if view.width_mode is ViewWidth.WIDE:
                row.append(room.quality)
            else:
                detail = f"{room.quality} · {detail}"
            row.extend((room.progress, detail))
            content.add_row(*row)
    footer = Text()
    if view.hidden_room_count:
        footer.append(f"还有 {view.hidden_room_count} 个房间未显示", style="dim")
    return Panel(Group(content, footer), title=title, border_style="bright_black", title_align="left", padding=(0, 1))


def _render_activity(view: DashboardView) -> Any:
    blocks: list[Any] = []
    if view.incidents:
        incident_table = Table.grid(expand=True, padding=(0, 1))
        if view.width_mode is ViewWidth.NARROW:
            incident_table.add_column(ratio=1)
            for incident in view.incidents:
                line = Text()
                line.append(f"■ {incident.disposition}  ", style=_KIND_STYLES[incident.kind])
                line.append(f"{incident.room_name}  {incident.message}\n")
                line.append(incident.detail, style="dim")
                incident_table.add_row(line)
        else:
            incident_table.add_column(width=12)
            incident_table.add_column(ratio=1)
            incident_table.add_column(ratio=2)
            incident_table.add_column(justify="right", ratio=1)
            for incident in view.incidents:
                incident_table.add_row(
                    Text(f"■ {incident.disposition}", style=_KIND_STYLES[incident.kind]),
                    incident.room_name,
                    incident.message,
                    Text(incident.detail, style="dim"),
                )
        blocks.append(incident_table)

    event_table = Table(expand=True, show_header=True, header_style="dim", box=None, padding=(0, 1))
    if view.width_mode is ViewWidth.NARROW:
        event_table.add_column("说明", ratio=1)
        for event in view.events:
            line = Text(f"{event.time}  ", style="dim")
            line.append(event.label, style=_KIND_STYLES[event.kind])
            line.append(f"  {event.room_name}  {event.detail}")
            event_table.add_row(line)
    else:
        event_table.add_column("时间", width=9)
        event_table.add_column("阶段", width=12)
        event_table.add_column("对象", ratio=1, overflow="ellipsis", no_wrap=True)
        event_table.add_column("说明", ratio=2, overflow="ellipsis", no_wrap=True)
        for event in view.events:
            event_table.add_row(
                Text(event.time, style="dim"),
                Text(f"● {event.label}", style=_KIND_STYLES[event.kind]),
                event.room_name,
                event.detail,
            )
    if not view.events:
        event_table.add_row(Text("暂无状态变化", style="dim"))
    blocks.append(event_table)

    footer = Text("技术日志：logs/streamget.log", style="dim")
    if view.hidden_event_count:
        footer.append(f"   较早 {view.hidden_event_count} 条已收起", style="dim")
    blocks.append(footer)
    actionable = sum(incident.kind == "danger" for incident in view.incidents)
    automatic = sum(incident.kind == "warning" for incident in view.incidents)
    title = Text(f"最近动态  需处理 {actionable} · 自动重试 {automatic}", style="bold white")
    return Panel(Group(*blocks), title=title, border_style="bright_black", title_align="left", padding=(0, 1))


def _metrics_text(view: DashboardView) -> Text:
    metrics = Text()
    for index, metric in enumerate(view.metrics):
        if index:
            metrics.append("    ")
        metrics.append(metric.value, style=f"bold {_KIND_STYLES[metric.kind]}")
        metrics.append(f" {metric.label}", style="dim")
    return metrics


def _health_text(items, *, prefix: str = "") -> Text:
    health = Text(justify="right")
    if prefix:
        health.append(prefix, style="dim")
    visible_items = tuple(item for item in items if not (item.label == "自动恢复" and item.value == "0"))
    for index, item in enumerate(visible_items):
        if index:
            health.append("    ")
        health.append("✓ " if item.healthy else "! ", style="green" if item.healthy else "bold red")
        health.append(f"{item.label} {item.value}", style="dim" if item.healthy else "bold red")
    return health


def build_plain_dashboard(view: DashboardView) -> str:
    metrics = " | ".join(f"{metric.label} {metric.value}" for metric in view.metrics)
    lines = [
        f"{view.title} | {view.phase} | {view.current_time} | 已运行 {view.uptime}",
        metrics,
        " | ".join(view.config_items),
        f"直播间 已显示 {len(view.rooms)}/{view.total_room_count}",
    ]
    if view.first_sweep:
        lines.append(view.first_sweep)
    for room in view.rooms:
        lines.append(
            f"{room.index} {room.name}·{room.platform} | {room.status} | "
            f"{room.quality} | {room.progress} | {room.detail}"
        )
    if view.upload_detail:
        lines.append(f"自动上传 | {view.upload_detail}")
    if view.hidden_room_count:
        lines.append(f"还有 {view.hidden_room_count} 个房间未显示")
    lines.append("最近动态")
    for incident in view.incidents:
        lines.append(
            f"{incident.disposition} | {incident.room_name} | {incident.message} | {incident.detail}"
        )
    for event in view.events:
        lines.append(f"{event.time} | {event.label} | {event.room_name} | {event.detail}")
    lines.append("技术日志：logs/streamget.log")
    if view.complete_prompt:
        lines.append(view.complete_prompt)
    return "\n".join(lines)


def _phase_style(phase: str) -> str:
    if phase == "运行正常":
        return "green"
    if phase == "收尾完成":
        return "bold green"
    return "yellow"


def _truncate_path(path: str, width: int) -> str:
    if len(path) <= width:
        return path
    return f"…{path[-(width - 1):]}"


class RichDashboard:
    def __init__(self, console: Console | None = None) -> None:
        rich_console = _make_console(console)
        if rich_console is None or Live is None:
            raise RuntimeError("Rich dashboard support is not available.")
        self.console = rich_console
        self._live = Live(
            Text("正在初始化监控面板…", style="dim"),
            console=self.console,
            screen=True,
            refresh_per_second=2,
            auto_refresh=False,
            redirect_stdout=False,
            redirect_stderr=False,
            transient=False,
        )
        self._started = False
        self._lock = threading.RLock()

    def start(self) -> None:
        with self._lock:
            if not self._started:
                self._live.start(refresh=True)
                self._started = True

    def stop(self) -> None:
        with self._lock:
            if self._started:
                self._live.stop()
                self._started = False

    def update(self, view: DashboardView) -> None:
        with self._lock:
            if not self._started:
                self._live.start(refresh=True)
                self._started = True
            self._live.update(build_dashboard_renderable(view), refresh=True)
