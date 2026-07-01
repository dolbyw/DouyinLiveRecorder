
"""
Author: Hmily
GitHub: https://github.com/ihmily
Date: 2023-07-17 23:52:05
Update: 2025-10-23 19:48:05
Copyright (c) 2023-2025 by Hmily, All Rights Reserved.
Function: Record live stream video.
"""
import builtins
import datetime
import json
import os
import random
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
import urllib.request
import uuid
from pathlib import Path
from urllib.error import HTTPError, URLError

import httpx

from ffmpeg_install import check_ffmpeg, current_env_path, ffmpeg_path
from msg_push import bark, dingtalk, ntfy, pushplus, send_email, tg_bot, xizhi
from src import spider, stream, utils
from src.cli_ui import (
    RichDashboard,
    build_plain_dashboard,
    supports_rich_dashboard,
)
from src.config_loader import load_app_config, normalize_url_config_entry, parse_url_config_entry
from src.dashboard_disk_usage import RecordingDirectorySizeCache
from src.dashboard_input import DashboardInputController, DashboardKeyReader
from src.dashboard_state import (
    AppDisplayPhase,
    AttentionDisposition,
    DashboardConfig,
    DashboardSnapshot,
    DashboardStateStore,
    DashboardUploadRecord,
    DashboardUploadStatus,
)
from src.dashboard_view import RoomListMode, build_dashboard_view
from src.http_clients.client_pool import close_async_clients_for_current_loop
from src.http_clients.runner import run_async, run_async_batch
from src.logger import disable_console_logging
from src.models import UploadConfig, normalize_stream_info
from src.platforms import DispatchResult, default_registry, try_resolve
from src.proxy import ProxyDetector
from src.recorder import (
    EndReason,
    FFmpegConverter,
    PostProcessor,
    RecordingPipeline,
    RecordRequest,
    SaveFormat,
)
from src.runtime import (
    AdjustableLimiter,
    PlatformProbeSettings,
    RecordingExecutor,
    RegisteredPlatformProbe,
    RequestPacer,
    RoomMonitor,
    RuntimeApp,
    RuntimeConfig,
    RuntimeCoordinator,
    RuntimeRunner,
    RuntimeScheduler,
    ShutdownControl,
    StateStore,
    StopToken,
    ThreadedRuntimeHost,
    calculate_legacy_first_start_spacing,
    parse_room_config_lines,
)
from src.uploader import (
    RcloneRcUploadProgress,
    create_upload_service,
    prepare_upload_config_for_run,
    resolve_upload_source,
    seconds_until_next_daily_run,
)
from src.utils import logger

overseas_platform_host = (
    "www.tiktok.com/",
    "sooplive.co.kr/",
    "sooplive.com/",
    "www.pandalive.co.kr/",
    "www.winktv.co.kr/",
    "www.flextv.co.kr/",
    "www.ttinglive.com/",
    "www.popkontv.com/",
    "www.twitch.tv/",
    "www.liveme.com/",
    "showroom-live.com/",
    "chzzk.naver.com/",
    "live.shopee",
    "shp.ee/",
    "www.youtube.com/",
    "youtu.be/",
    "faceit.com/",
    "www.picarto.tv",
)

recording = set()
error_count = 0
pre_max_request = 10
max_request_lock = threading.Lock()
error_window = []
error_window_size = 10
error_threshold = 5
monitoring = 0
running_list = []
url_tuples_list = []
url_comments = []
text_no_repeat_url = []
create_var = locals()
first_start = True
exit_recording = False
shutdown_control = ShutdownControl()
async_runtime_host: ThreadedRuntimeHost | None = None
async_runtime_state_store: StateStore | None = None
need_update_line_list = []
first_run = True
not_record_list = []
start_display_time = datetime.datetime.now().astimezone()
global_proxy = False
recording_time_list = {}
script_path = os.path.split(os.path.realpath(sys.argv[0]))[0]
config_file = f'{script_path}/config/config.ini'
url_config_file = f'{script_path}/config/URL_config.ini'
ini_URL_content = ''
backup_dir = f'{script_path}/backup_config'
text_encoding = 'utf-8-sig'
rstr = r"[\/\\\:\*\？?\"\<\>\|&#.。,， ~！· ]"
default_path = f'{script_path}/downloads'
os.makedirs(default_path, exist_ok=True)
upload_record_log_file = Path(script_path) / "logs" / "upload_records.jsonl"
file_update_lock = threading.Lock()
conversion_progress_lock = threading.Lock()
dashboard_refresh_event = threading.Event()
conversion_success_count = 0
conversion_failure_count = 0
dashboard_store = DashboardStateStore(started_at=start_display_time)
dashboard_input = DashboardInputController(on_change=dashboard_refresh_event.set)
dashboard_key_reader: DashboardKeyReader | None = None
recording_size_cache = RecordingDirectorySizeCache()
upload_service_lock = threading.Lock()
upload_status_lock = threading.Lock()
upload_recording_finished_event = threading.Event()
upload_shutdown_event = threading.Event()
upload_dashboard_status = DashboardUploadStatus()
upload_service_generation = 0
upload_service_signature: tuple | None = None
os_type = os.name
clear_command = "cls" if os_type == 'nt' else "clear"
os.environ['PATH'] = ffmpeg_path + os.pathsep + current_env_path
ffmpeg_converter = FFmpegConverter()


# #region debug-point shared:report
def _debug_report(hypothesis_id: str, location: str, msg: str, data: dict | None = None) -> None:
    _env_path = '.dbg/recording-stalls-on-open.env'
    _url = 'http://127.0.0.1:7777/event'
    _session = 'recording-stalls-on-open'
    try:
        with open(_env_path, encoding='utf-8') as _f:
            _env = _f.read().splitlines()
        for _line in _env:
            if _line.startswith('DEBUG_SERVER_URL='):
                _url = _line.split('=', 1)[1] or _url
            elif _line.startswith('DEBUG_SESSION_ID='):
                _session = _line.split('=', 1)[1] or _session
        urllib.request.urlopen(
            urllib.request.Request(
                _url,
                data=json.dumps(
                    {
                        "sessionId": _session,
                        "runId": "pre-fix",
                        "hypothesisId": hypothesis_id,
                        "location": location,
                        "msg": msg,
                        "data": data or {},
                        "ts": int(time.time() * 1000),
                    }
                ).encode(),
                headers={"Content-Type": "application/json"},
            ),
            timeout=0.8,
        ).read()
    except Exception:
        pass


# #endregion


def signal_handler(_signal, _frame):
    global exit_recording
    if shutdown_control.requested:
        request_upload_shutdown()
        dashboard_store.set_phase(AppDisplayPhase.COMPLETE)
        dashboard_refresh_event.set()
        return
    if not shutdown_control.request():
        return
    dashboard_store.set_phase(AppDisplayPhase.STOPPING)
    dashboard_input.disable()
    if dashboard_key_reader is not None:
        dashboard_key_reader.stop()
    exit_recording = True
    logger.warning("正在停止录制并完成TS转MP4；再次按 Ctrl+C 将强制退出")
    if async_runtime_host is not None:
        async_runtime_host.request_shutdown()
        async_runtime_host.join()
    while recording:
        time.sleep(0.1)
    dashboard_store.add_event(
        "__app__",
        "shutdown_complete",
        f"收尾完成：转码成功 {conversion_success_count}，失败 {conversion_failure_count}",
    )
    dashboard_store.set_phase(AppDisplayPhase.COMPLETE)
    dashboard_refresh_event.set()


def make_conversion_progress_callback(index: int, total: int, room_id: str):
    last_emitted_at = 0.0

    def report(progress):
        global conversion_success_count
        nonlocal last_emitted_at
        now = time.monotonic()
        if progress.elapsed > 0 and not progress.finished and now - last_emitted_at < 1.0:
            return
        last_emitted_at = now
        with conversion_progress_lock:
            if exit_recording:
                dashboard_store.set_phase(AppDisplayPhase.FINALIZING)
            dashboard_store.mark_converting(
                room_id,
                f"{index}/{total} · {progress.source.name}",
                progress.percent,
                progress.elapsed,
                progress.duration,
            )
            if progress.finished:
                conversion_success_count += 1
                dashboard_store.add_event(
                    room_id,
                    "conversion_finished",
                    "录制完成并转为 MP4",
                    correlation_id=f"conversion:{room_id}:{progress.source}",
                    details={
                        "duration": f"{progress.duration:.0f} 秒" if progress.duration is not None else "",
                        "format": "MP4",
                    },
                )
                dashboard_store.mark_conversion_finished(room_id)

    return report


def get_current_monitoring_count() -> int:
    current_monitoring = monitoring
    if async_runtime_active() and async_runtime_state_store is not None:
        snapshot = async_runtime_state_store.snapshot()
        runtime_monitoring = sum(
            1
            for status in snapshot.statuses
            if status.monitoring and not status.stop_requested
        )
        current_monitoring = max(current_monitoring, runtime_monitoring)
    return current_monitoring


def describe_upload_trigger(upload_config: UploadConfig) -> str:
    if upload_config.trigger_mode == "间隔":
        return f"间隔{upload_config.interval_seconds}秒"
    if upload_config.trigger_mode == "录制结束":
        return "录制结束"
    return f"定时{upload_config.daily_time}"


def publish_upload_status(upload_status: DashboardUploadStatus) -> None:
    global upload_dashboard_status
    with upload_status_lock:
        if not upload_status.records and upload_dashboard_status.records:
            upload_status = DashboardUploadStatus(
                enabled=upload_status.enabled,
                phase=upload_status.phase,
                trigger=upload_status.trigger,
                target=upload_status.target,
                detail=upload_status.detail,
                attempts=upload_status.attempts,
                retry_limit=upload_status.retry_limit,
                records=upload_dashboard_status.records,
            )
        upload_dashboard_status = upload_status
    dashboard_store.set_upload(upload_status)
    dashboard_refresh_event.set()


def infer_upload_streamer(relative_path: Path) -> str:
    if len(relative_path.parts) > 1:
        return relative_path.parts[0].strip() or "未知主播"
    stem = relative_path.stem.strip()
    for delimiter in ("_", "-", " ", "（", "("):
        if delimiter in stem:
            name = stem.split(delimiter, 1)[0].strip()
            if name:
                return name
    return stem or "未知主播"


def snapshot_upload_files(source_path: str | Path) -> dict[Path, int]:
    source = Path(source_path)
    if not source.is_dir():
        return {}
    files: dict[Path, int] = {}
    for candidate in source.rglob("*"):
        if not candidate.is_file():
            continue
        try:
            relative_path = candidate.relative_to(source)
            if any(part.startswith(".upload") for part in relative_path.parts):
                continue
            files[relative_path] = candidate.stat().st_size
        except OSError:
            continue
    return files


def build_upload_file_records(
    before: dict[Path, int],
    after: dict[Path, int],
    result,
) -> tuple[DashboardUploadRecord, ...]:
    timestamp = datetime.datetime.now().astimezone()
    records: list[DashboardUploadRecord] = []
    uploaded_paths = sorted(set(before) - set(after), key=lambda path: path.as_posix())
    for relative_path in uploaded_paths[:20]:
        records.append(
            DashboardUploadRecord(
                phase="success",
                message="上传完成",
                at=timestamp,
                attempts=result.attempts,
                files_total=1,
                bytes_total=before.get(relative_path, 0),
                streamer=infer_upload_streamer(relative_path),
                file_name=relative_path.name,
                relative_path=relative_path.as_posix(),
            )
        )
    if result.phase in {"partial", "failed", "skipped"} and len(records) < 20:
        remaining_paths = sorted(set(before) & set(after), key=lambda path: path.as_posix())
        for relative_path in remaining_paths[: 20 - len(records)]:
            records.append(
                DashboardUploadRecord(
                    phase=result.phase,
                    message="保留本地，等待下次上传",
                    at=timestamp,
                    attempts=result.attempts,
                    files_total=1,
                    bytes_total=after.get(relative_path, before.get(relative_path, 0)),
                    streamer=infer_upload_streamer(relative_path),
                    file_name=relative_path.name,
                    relative_path=relative_path.as_posix(),
                )
            )
    return tuple(records)


def write_upload_file_records(
    records: tuple[DashboardUploadRecord, ...],
    upload_status: DashboardUploadStatus,
) -> None:
    if not records:
        return
    try:
        upload_record_log_file.parent.mkdir(parents=True, exist_ok=True)
        with upload_record_log_file.open("a", encoding="utf-8") as log_file:
            for record in records:
                payload = {
                    "time": record.at.isoformat(timespec="seconds"),
                    "phase": record.phase,
                    "streamer": record.streamer,
                    "file_name": record.file_name,
                    "relative_path": record.relative_path,
                    "message": record.message,
                    "bytes_total": record.bytes_total,
                    "attempts": record.attempts,
                    "trigger": upload_status.trigger,
                    "target": upload_status.target,
                }
                log_file.write(json.dumps(payload, ensure_ascii=False) + "\n")
    except OSError as err:
        logger.warning(f"上传记录写入失败: {err}")


def append_upload_record(
    upload_status: DashboardUploadStatus,
    result,
    file_records: tuple[DashboardUploadRecord, ...] = (),
) -> DashboardUploadStatus:
    message = result.message or result.stderr or result.stdout or "上传任务结束"
    record = DashboardUploadRecord(
        phase=result.phase,
        message=message,
        at=datetime.datetime.now().astimezone(),
        attempts=result.attempts,
        files_total=result.files_total,
        bytes_total=result.bytes_total,
        files_remaining=result.files_remaining,
        bytes_remaining=result.bytes_remaining,
    )
    return DashboardUploadStatus(
        enabled=upload_status.enabled,
        phase=upload_status.phase,
        trigger=upload_status.trigger,
        target=upload_status.target,
        detail=upload_status.detail,
        attempts=upload_status.attempts,
        retry_limit=upload_status.retry_limit,
        records=(record, *file_records, *upload_status.records)[:30],
    )


def format_upload_progress(progress: RcloneRcUploadProgress) -> str:
    parts: list[str] = []
    if progress.percent is not None:
        parts.append(f"{progress.percent:.1f}%")
    if progress.speed_bytes_per_second is not None:
        parts.append(f"{format_upload_bytes(progress.speed_bytes_per_second)}/s")
    if progress.bytes_transferred is not None and progress.total_bytes is not None:
        parts.append(f"{format_upload_bytes(progress.bytes_transferred)} / {format_upload_bytes(progress.total_bytes)}")
    elif progress.bytes_transferred is not None:
        parts.append(format_upload_bytes(progress.bytes_transferred))
    if progress.current_file:
        parts.append(progress.current_file)
    return " · ".join(parts) or "上传中"


def format_upload_bytes(size: float) -> str:
    if size < 1_000_000:
        return f"{size / 1_000:.1f} KB"
    if size < 1_000_000_000:
        return f"{size / 1_000_000:.1f} MB"
    return f"{size / 1_000_000_000:.1f} GB"


def publish_upload_progress(progress: RcloneRcUploadProgress) -> None:
    with upload_status_lock:
        current_status = upload_dashboard_status
    if not current_status.enabled:
        return
    publish_upload_status(
        DashboardUploadStatus(
            enabled=True,
            phase="running",
            trigger=current_status.trigger,
            target=current_status.target,
            detail=format_upload_progress(progress),
            attempts=current_status.attempts,
            retry_limit=current_status.retry_limit,
        )
    )


def refresh_upload_dashboard_status(upload_config: UploadConfig) -> None:
    with upload_status_lock:
        current_status = upload_dashboard_status
    if not upload_config.enabled:
        publish_upload_status(DashboardUploadStatus(enabled=False, phase="disabled"))
        return

    trigger = describe_upload_trigger(upload_config)
    if (
        not current_status.enabled
        or current_status.target != upload_config.remote_path
        or current_status.trigger != trigger
    ):
        publish_upload_status(
            DashboardUploadStatus(
                enabled=True,
                phase="idle",
                trigger=trigger,
                target=upload_config.remote_path,
                detail="等待上传",
            )
        )
    else:
        dashboard_store.set_upload(current_status)


def upload_config_signature(upload_config: UploadConfig, recording_save_path: str) -> tuple:
    return (
        upload_config.enabled,
        upload_config.execution_mode,
        upload_config.trigger_mode,
        upload_config.daily_time,
        upload_config.interval_seconds,
        upload_config.source_path,
        recording_save_path,
        upload_config.remote_path,
        upload_config.rclone_path,
        upload_config.rc_port,
        upload_config.min_age,
        upload_config.transfers,
        upload_config.checkers,
        upload_config.rclone_retries,
        upload_config.app_retries,
        upload_config.retry_sleep_seconds,
        upload_config.webdav_remote_name,
        upload_config.webdav_url,
        upload_config.webdav_username,
        upload_config.webdav_password,
        upload_config.webdav_vendor,
        upload_config.delete_empty_dirs,
        upload_config.dry_run,
    )


def upload_generation_active(generation: int) -> bool:
    with upload_service_lock:
        return generation == upload_service_generation


def notify_recording_finished_upload() -> None:
    upload_recording_finished_event.set()


def request_upload_shutdown() -> bool:
    if upload_shutdown_event.is_set():
        return False
    upload_shutdown_event.set()
    upload_recording_finished_event.set()
    dashboard_store.add_event(
        "__app__",
        "upload_stopped",
        "自动上传停止，未完成文件保留本地，下次启动继续上传",
    )
    with upload_status_lock:
        current_status = upload_dashboard_status
    if current_status.enabled:
        publish_upload_status(
            DashboardUploadStatus(
                enabled=True,
                phase="skipped",
                trigger=current_status.trigger,
                target=current_status.target,
                detail="已停止上传，未完成文件保留本地",
                attempts=current_status.attempts,
                retry_limit=current_status.retry_limit,
                records=current_status.records,
            )
        )
    return True


def upload_shutdown_requested() -> bool:
    return upload_shutdown_event.is_set()


def upload_worker(upload_config: UploadConfig, recording_save_path: str, generation: int) -> None:
    source_path = resolve_upload_source(upload_config, recording_save_path, default_path)
    upload_config_for_run = prepare_upload_config_for_run(upload_config)
    upload_service = create_upload_service(
        upload_config_for_run,
        progress_callback=publish_upload_progress,
        stop_requested=upload_shutdown_requested,
    )
    trigger = describe_upload_trigger(upload_config)
    while not upload_shutdown_requested() and upload_generation_active(generation):
        if upload_config.trigger_mode == "录制结束":
            publish_upload_status(
                DashboardUploadStatus(
                    enabled=True,
                    phase="idle",
                    trigger=trigger,
                    target=upload_config.remote_path,
                    detail="等待录制结束",
                )
            )
            while not upload_shutdown_requested() and upload_generation_active(generation):
                if upload_recording_finished_event.wait(1):
                    upload_recording_finished_event.clear()
                    break
            if upload_shutdown_requested() or not upload_generation_active(generation):
                return
        elif upload_config.trigger_mode != "间隔":
            wait_seconds = seconds_until_next_daily_run(upload_config.daily_time)
            publish_upload_status(
                DashboardUploadStatus(
                    enabled=True,
                    phase="idle",
                    trigger=trigger,
                    target=upload_config.remote_path,
                    detail=f"下次上传约 {wait_seconds // 60} 分钟后",
                )
            )
            for _ in range(max(1, wait_seconds)):
                if upload_shutdown_requested() or not upload_generation_active(generation):
                    return
                time.sleep(1)
        if not upload_generation_active(generation):
            return
        retry_limit = upload_config.app_retries + 1
        publish_upload_status(
            DashboardUploadStatus(
                enabled=True,
                phase="running",
                trigger=trigger,
                target=upload_config.remote_path,
                detail=f"正在上传 {source_path}",
                retry_limit=retry_limit,
            )
        )
        dashboard_store.add_event("system", "upload_started", f"开始上传 {source_path}")
        upload_snapshot_before = snapshot_upload_files(source_path)
        result = upload_service.run_once(source_path)
        upload_snapshot_after = snapshot_upload_files(source_path)
        if not upload_generation_active(generation):
            return
        file_records = build_upload_file_records(upload_snapshot_before, upload_snapshot_after, result)
        phase = result.phase
        event_type = {
            "success": "upload_finished",
            "partial": "upload_partial",
            "failed": "upload_failed",
            "skipped": "upload_skipped",
        }.get(phase, "upload_finished")
        message = result.message if phase == "partial" else result.stderr or result.stdout or result.message
        dashboard_store.add_event("system", event_type, message or "上传任务结束")
        next_status = DashboardUploadStatus(
            enabled=True,
            phase=phase,
            trigger=trigger,
            target=upload_config.remote_path,
            detail=message or result.message,
            attempts=result.attempts,
            retry_limit=retry_limit,
        )
        write_upload_file_records(file_records, next_status)
        publish_upload_status(append_upload_record(next_status, result, file_records))
        if phase == "failed":
            dashboard_store.report_incident(
                "system",
                "auto-upload",
                message or "自动上传失败",
                disposition=AttentionDisposition.AUTOMATIC,
                retry_attempt=result.attempts,
                retry_limit=retry_limit,
            )
        else:
            dashboard_store.clear_incident("system", "auto-upload", recovery_message="自动上传恢复")
        if upload_config.trigger_mode == "间隔":
            for _ in range(max(1, upload_config.interval_seconds)):
                if upload_shutdown_requested() or not upload_generation_active(generation):
                    return
                time.sleep(1)


def start_upload_service(upload_config: UploadConfig, recording_save_path: str) -> None:
    global upload_service_generation, upload_service_signature
    refresh_upload_dashboard_status(upload_config)
    signature = upload_config_signature(upload_config, recording_save_path)
    if not upload_config.enabled:
        with upload_service_lock:
            if upload_service_signature != signature:
                upload_service_generation += 1
                upload_service_signature = signature
        return
    with upload_service_lock:
        if upload_service_signature == signature:
            return
        upload_service_generation += 1
        upload_service_signature = signature
        threading.Thread(
            target=upload_worker,
            args=(upload_config, recording_save_path, upload_service_generation),
            daemon=True,
        ).start()


def refresh_dashboard_configuration() -> None:
    current_config = load_app_config(config_file, encoding=text_encoding)
    try:
        with open(url_config_file, encoding=text_encoding, errors="ignore") as room_file:
            room_snapshot = parse_room_config_lines(room_file, current_config.recording.default_quality)
    except FileNotFoundError:
        room_snapshot = parse_room_config_lines((), current_config.recording.default_quality)
    dashboard_store.reconcile_rooms(room_snapshot.desired_rooms)

    recording_config = current_config.recording
    upload_config = current_config.upload
    save_path = recording_config.save_path or default_path
    recordings_size_bytes = recording_size_cache.get(save_path)
    try:
        disk_free_gb = shutil.disk_usage(save_path).free / (1024**3)
    except OSError:
        disk_free_gb = None
    try:
        split_seconds = int(recording_config.split_time_seconds) if recording_config.split_video_by_time else None
    except ValueError:
        split_seconds = None
    dashboard_store.set_config(
        DashboardConfig(
            save_format=recording_config.save_type.value,
            quality=recording_config.default_quality.value,
            split_seconds=split_seconds,
            poll_seconds=recording_config.loop_delay_seconds,
            max_requests=recording_config.max_request,
            use_proxy=recording_config.use_proxy,
            convert_to_mp4=recording_config.converts_to_mp4,
            save_path=save_path,
            disk_free_gb=disk_free_gb,
            recordings_size_bytes=recordings_size_bytes,
        )
    )
    refresh_upload_dashboard_status(upload_config)


def build_dashboard_snapshot() -> DashboardSnapshot:
    if not exit_recording:
        refresh_dashboard_configuration()
    if not exit_recording and async_runtime_state_store is not None:
        runtime_snapshot = async_runtime_state_store.snapshot()
        for status in runtime_snapshot.statuses:
            try:
                if status.stop_requested:
                    dashboard_store.mark_disabled(status.room_id)
                elif status.recording_name and status.recording_started_at and status.recording_quality:
                    dashboard_store.mark_recording(
                        status.room_id,
                        status.recording_name,
                        status.recording_quality.value,
                        status.recording_started_at,
                    )
                elif status.last_error:
                    dashboard_store.mark_retrying(status.room_id, status.last_error)
                    dashboard_store.report_incident(
                        status.room_id,
                        "probe",
                        status.last_error,
                        disposition=AttentionDisposition.AUTOMATIC,
                    )
                elif status.monitoring:
                    dashboard_store.mark_monitoring(status.room_id, checked=False)
                    dashboard_store.clear_incident(
                        status.room_id,
                        "probe",
                        recovery_message="连接已恢复",
                    )
            except KeyError:
                continue
    dashboard_store.set_health(error_count=error_count)
    return dashboard_store.snapshot()


def _display_info_plain() -> None:
    while not upload_shutdown_requested():
        try:
            dashboard_refresh_event.wait(1)
            dashboard_refresh_event.clear()
            if Path(sys.executable).name != 'pythonw.exe':
                os.system(clear_command)
            size = shutil.get_terminal_size(fallback=(100, 32))
            view = build_dashboard_view(
                build_dashboard_snapshot(),
                width=size.columns,
                height=size.lines,
                room_mode=RoomListMode.COMPACT,
                upload_detail_expanded=dashboard_input.upload_detail_expanded,
            )
            print(build_plain_dashboard(view), flush=True)
        except Exception as e:
            logger.error(f"错误信息: {e} 发生错误的行数: {e.__traceback__.tb_lineno}")


def display_info() -> None:
    global dashboard_key_reader
    time.sleep(3)
    disable_console_logging()
    if Path(sys.executable).name == 'pythonw.exe' or not supports_rich_dashboard():
        _display_info_plain()
        return

    dashboard = RichDashboard()
    dashboard.console.clear()
    dashboard_key_reader = DashboardKeyReader(
        dashboard_input,
        on_error=lambda error: logger.warning(f"面板键盘控制已停用: {error}"),
    )
    dashboard_key_reader.start()
    use_plain_fallback = False
    try:
        view = build_dashboard_view(
            build_dashboard_snapshot(),
            width=dashboard.console.size.width,
            height=dashboard.console.size.height,
            room_mode=dashboard_input.room_mode,
            upload_detail_expanded=dashboard_input.upload_detail_expanded,
        )
        dashboard.update(view)
        while True:
            dashboard_refresh_event.wait(1)
            dashboard_refresh_event.clear()
            view = build_dashboard_view(
                build_dashboard_snapshot(),
                width=dashboard.console.size.width,
                height=dashboard.console.size.height,
                room_mode=dashboard_input.room_mode,
                upload_detail_expanded=dashboard_input.upload_detail_expanded,
            )
            dashboard.update(view)
    except Exception as e:
        logger.error(f"错误信息: {e} 发生错误的行数: {e.__traceback__.tb_lineno}")
        use_plain_fallback = True
    finally:
        dashboard_key_reader.stop()
        dashboard_key_reader = None
        dashboard.stop()
    if use_plain_fallback:
        _display_info_plain()


def update_file(file_path: str, old_str: str, new_str: str, start_str: str = None) -> str | None:
    if old_str == new_str and start_str is None:
        return old_str
    with file_update_lock:
        file_data = []
        with open(file_path, encoding=text_encoding) as f:
            try:
                for text_line in f:
                    if old_str in text_line:
                        text_line = text_line.replace(old_str, new_str)
                        if start_str:
                            text_line = f'{start_str}{text_line}'
                    if text_line not in file_data:
                        file_data.append(text_line)
            except RuntimeError as e:
                logger.error(f"错误信息: {e} 发生错误的行数: {e.__traceback__.tb_lineno}")
                if ini_URL_content:
                    with open(file_path, "w", encoding=text_encoding) as f2:
                        f2.write(ini_URL_content)
                    return old_str
        if file_data:
            with open(file_path, "w", encoding=text_encoding) as f:
                f.write(''.join(file_data))
        return new_str


def delete_line(file_path: str, del_line: str, delete_all: bool = False) -> None:
    with file_update_lock:
        with open(file_path, 'r+', encoding=text_encoding) as f:
            lines = f.readlines()
            f.seek(0)
            f.truncate()
            skip_line = False
            for txt_line in lines:
                if del_line in txt_line:
                    if delete_all or not skip_line:
                        skip_line = True
                        continue
                else:
                    skip_line = False
                f.write(txt_line)


def get_startup_info(system_type: str):
    if system_type == 'nt':
        startup_info = subprocess.STARTUPINFO()
        startup_info.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    else:
        startup_info = None
    return startup_info


def segment_video(converts_file_path: str, segment_save_file_path: str, segment_format: str, segment_time: str,
                  is_original_delete: bool = True) -> None:
    try:
        if os.path.exists(converts_file_path) and os.path.getsize(converts_file_path) > 0:
            ffmpeg_command = [
                "ffmpeg",
                "-i", converts_file_path,
                "-c:v", "copy",
                "-c:a", "copy",
                "-map", "0",
                "-f", "segment",
                "-segment_time", segment_time,
                "-segment_format", segment_format,
                "-reset_timestamps", "1",
                "-movflags", "+frag_keyframe+empty_moov",
                segment_save_file_path,
            ]
            _output = subprocess.check_output(
                ffmpeg_command, stderr=subprocess.STDOUT, startupinfo=get_startup_info(os_type)
            )
            if is_original_delete:
                time.sleep(1)
                if os.path.exists(converts_file_path):
                    os.remove(converts_file_path)
    except subprocess.CalledProcessError as e:
        logger.error(f'Error occurred during conversion: {e}')
    except Exception as e:
        logger.error(f'An unknown error occurred: {e}')


def converts_mp4(converts_file_path: str, is_original_delete: bool = True) -> None:
    try:
        if os.path.exists(converts_file_path) and os.path.getsize(converts_file_path) > 0:
            if converts_to_h264:
                logger.info("正在转码为MP4格式并重新编码为h264")
                ffmpeg_command = [
                    "ffmpeg", "-i", converts_file_path,
                    "-c:v", "libx264",
                    "-preset", "veryfast",
                    "-crf", "23",
                    "-vf", "format=yuv420p",
                    "-c:a", "copy",
                    "-f", "mp4", converts_file_path.rsplit('.', maxsplit=1)[0] + ".mp4",
                ]
            else:
                logger.info("正在转码为MP4格式")
                ffmpeg_command = [
                    "ffmpeg", "-i", converts_file_path,
                    "-c:v", "copy",
                    "-c:a", "copy",
                    "-f", "mp4", converts_file_path.rsplit('.', maxsplit=1)[0] + ".mp4",
                ]
            _output = subprocess.check_output(
                ffmpeg_command, stderr=subprocess.STDOUT, startupinfo=get_startup_info(os_type)
            )
            if is_original_delete:
                time.sleep(1)
                if os.path.exists(converts_file_path):
                    os.remove(converts_file_path)
    except subprocess.CalledProcessError as e:
        logger.error(f'Error occurred during conversion: {e}')
    except Exception as e:
        logger.error(f'An unknown error occurred: {e}')


def converts_m4a(converts_file_path: str, is_original_delete: bool = True) -> None:
    try:
        if os.path.exists(converts_file_path) and os.path.getsize(converts_file_path) > 0:
            _output = subprocess.check_output([
                "ffmpeg", "-i", converts_file_path,
                "-n", "-vn",
                "-c:a", "aac", "-bsf:a", "aac_adtstoasc", "-ab", "320k",
                converts_file_path.rsplit('.', maxsplit=1)[0] + ".m4a",
            ], stderr=subprocess.STDOUT, startupinfo=get_startup_info(os_type))
            if is_original_delete:
                time.sleep(1)
                if os.path.exists(converts_file_path):
                    os.remove(converts_file_path)
    except subprocess.CalledProcessError as e:
        logger.error(f'Error occurred during conversion: {e}')
    except Exception as e:
        logger.error(f'An unknown error occurred: {e}')


def generate_subtitles(record_name: str, ass_filename: str, sub_format: str = 'srt') -> None:
    index_time = 0
    today = datetime.datetime.now()
    re_datatime = today.strftime('%Y-%m-%d %H:%M:%S')

    def transform_int_to_time(seconds: int) -> str:
        m, s = divmod(seconds, 60)
        h, m = divmod(m, 60)
        return f"{h:02d}:{m:02d}:{s:02d}"

    while True:
        index_time += 1
        txt = str(index_time) + "\n" + transform_int_to_time(index_time) + ',000 --> ' + transform_int_to_time(
            index_time + 1) + ',000' + "\n" + str(re_datatime) + "\n\n"

        with open(f"{ass_filename}.{sub_format.lower()}", 'a', encoding=text_encoding) as f:
            f.write(txt)

        if record_name not in recording:
            return
        time.sleep(1)
        today = datetime.datetime.now()
        re_datatime = today.strftime('%Y-%m-%d %H:%M:%S')


def adjust_max_request() -> None:
    global max_request, error_count, pre_max_request, error_window
    preset = max_request

    while True:
        time.sleep(5)
        with max_request_lock:
            if error_window:
                error_rate = sum(error_window) / len(error_window)
            else:
                error_rate = 0

            if error_rate > error_threshold:
                max_request = max(1, max_request - 1)
            elif error_rate < error_threshold / 2 and max_request < preset:
                max_request += 1
            else:
                pass

            if pre_max_request != max_request:
                pre_max_request = max_request
                logger.info(f"同一时间访问网络的线程数动态改为 {max_request}")

        error_window.append(error_count)
        if len(error_window) > error_window_size:
            error_window.pop(0)
        error_count = 0


def push_message(record_name: str, live_url: str, content: str) -> None:
    msg_title = push_message_title.strip() or "直播间状态更新通知"
    push_functions = {
        '微信': lambda: xizhi(xizhi_api_url, msg_title, content),
        '钉钉': lambda: dingtalk(dingtalk_api_url, content, dingtalk_phone_num, dingtalk_is_atall),
        '邮箱': lambda: send_email(
            email_host, login_email, email_password, sender_email, sender_name,
            to_email, msg_title, content, smtp_port, open_smtp_ssl
        ),
        'TG': lambda: tg_bot(tg_chat_id, tg_token, content),
        'BARK': lambda: bark(
            bark_msg_api, title=msg_title, content=content, level=bark_msg_level, sound=bark_msg_ring
        ),
        'NTFY': lambda: ntfy(
            ntfy_api, title=msg_title, content=content, tags=ntfy_tags, action_url=live_url, email=ntfy_email
        ),
        'PUSHPLUS': lambda: pushplus(pushplus_token, msg_title, content),
    }

    for platform, func in push_functions.items():
        if platform in live_status_push.upper():
            try:
                result = func()
                logger.info(
                    f'已经将[{record_name}]直播状态消息推送至你的{platform}, '
                    f'成功{len(result["success"])}, 失败{len(result["error"])}'
                )
            except Exception as e:
                logger.error(f"直播消息推送到{platform}失败: {e}")


def run_script(command: str) -> None:
    try:
        process = subprocess.Popen(
            command, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, startupinfo=get_startup_info(os_type)
        )
        stdout, stderr = process.communicate()
        stdout_decoded = stdout.decode('utf-8')
        stderr_decoded = stderr.decode('utf-8')
        if stdout_decoded.strip():
            logger.info(stdout_decoded.strip())
        if stderr_decoded.strip():
            logger.warning(stderr_decoded.strip())
    except PermissionError as e:
        logger.error(e)
        logger.error('脚本无执行权限!, 若是Linux环境, 请先执行:chmod +x your_script.sh 授予脚本可执行权限')
    except OSError as e:
        logger.error(e)
        logger.error('Please add `#!/bin/bash` at the beginning of your bash script file.')


def clear_record_info(record_name: str, record_url: str) -> None:
    global monitoring
    recording.discard(record_name)
    if record_url in url_comments and record_url in running_list:
        running_list.remove(record_url)
        monitoring -= 1
        logger.info(f"[{record_name}]已经从录制列表中移除")


def direct_download_stream(source_url: str, save_path: str, record_name: str, live_url: str, platform: str) -> bool:
    try:
        with open(save_path, 'wb') as f:
            headers = {}
            header_params = get_record_headers(platform, live_url)
            if header_params:
                key, value = header_params.split(":", 1)
                headers[key] = value

            with httpx.Client(timeout=None) as client, client.stream(
                'GET', source_url, headers=headers, follow_redirects=True
            ) as response:
                if response.status_code != 200:
                    logger.error(f"请求直播流失败，状态码: {response.status_code}")
                    return False

                downloaded = 0
                chunk_size = 1024 * 16

                for chunk in response.iter_bytes(chunk_size):
                    if live_url in url_comments or exit_recording:
                        logger.warning(f"[{record_name}]录制时已被注释或请求停止,下载中断")
                        clear_record_info(record_name, live_url)
                        return False

                    if chunk:
                        f.write(chunk)
                        downloaded += len(chunk)
                return True
    except Exception as e:
        logger.error(f"FLV下载错误: {e} 发生错误的行数: {e.__traceback__.tb_lineno}")
        return False


def clean_name(input_text):
    cleaned_name = re.sub(rstr, "_", input_text.strip()).strip('_')
    cleaned_name = cleaned_name.replace("（", "(").replace("）", ")")
    if clean_emoji:
        cleaned_name = utils.remove_emojis(cleaned_name, '_').strip('_')
    return cleaned_name or '空白昵称'


def get_quality_code(qn):
    QUALITY_MAPPING = {
        "原画": "OD",
        "蓝光": "BD",
        "超清": "UHD",
        "高清": "HD",
        "标清": "SD",
        "流畅": "LD"
    }
    return QUALITY_MAPPING.get(qn)


def get_record_headers(platform, live_url):
    live_domain = '/'.join(live_url.split('/')[0:3])
    record_headers = {
        'PandaTV': 'origin:https://www.pandalive.co.kr',
        'WinkTV': 'origin:https://www.winktv.co.kr',
        'PopkonTV': 'origin:https://www.popkontv.com',
        'FlexTV': 'origin:https://www.flextv.co.kr',
        '千度热播': 'referer:https://qiandurebo.com',
        '17Live': 'referer:https://17.live/en/live/6302408',
        '浪Live': 'referer:https://www.lang.live',
        'shopee': f'origin:{live_domain}',
        'Blued直播': 'referer:https://app.blued.cn'
    }
    return record_headers.get(platform)


def is_flv_preferred_platform(link):
    return any(i in link for i in ["douyin", "tiktok"])


def select_source_url(link, stream_info):
    if is_flv_preferred_platform(link):
        codec = utils.get_query_params(stream_info.get('flv_url'), "codec")
        if codec and codec[0] == 'h265':
            logger.warning("FLV is not supported for h265 codec, use HLS source instead")
        else:
            return stream_info.get('flv_url')

    return stream_info.get('record_url')


def resolve_registered_platform_once(record_url: str, record_quality: str, proxy_address: str | None) -> DispatchResult:
    if default_registry.find(record_url) is None:
        return DispatchResult(handled=False)

    cookies_by_platform = {
        "douyin": globals().get("dy_cookie"),
        "tiktok": globals().get("tiktok_cookie"),
        "bilibili": globals().get("bili_cookie"),
        "huya": globals().get("hy_cookie"),
    }
    with semaphore:
        (result,) = run_async_batch(
            lambda: try_resolve(
                default_registry,
                record_url,
                record_quality,
                proxy_addr=proxy_address,
                cookies_by_platform=cookies_by_platform,
                network_available=bool(global_proxy or proxy_address),
            )
        )
        return result


def start_record(
        url_data: tuple,
        count_variable: int = -1,
        resolved_once: dict | None = None,
        single_cycle: bool = False,
        stop_token: StopToken | None = None,
        session_state: dict | None = None,
) -> None:
    global conversion_failure_count, error_count

    while True:
        if exit_recording or bool(stop_token and stop_token.shutdown_requested):
            return
        try:
            record_finished = False
            session_state = session_state if session_state is not None else {}
            run_once = bool(session_state.get("run_once", False))
            start_pushed = bool(session_state.get("start_pushed", False))
            new_record_url = str(session_state.get("new_record_url", ""))
            count_time = float(session_state.get("count_time", time.time()))
            retry = 0
            record_quality_zh, record_url, anchor_name = url_data
            record_quality = get_quality_code(record_quality_zh)
            proxy_address = proxy_addr
            platform = '未知平台'

            if proxy_addr:
                proxy_address = None
                for platform in enable_proxy_platform_list:
                    if platform and platform.strip() in record_url:
                        proxy_address = proxy_addr
                        break

            if not proxy_address:
                if extra_enable_proxy_platform_list:
                    for pt in extra_enable_proxy_platform_list:
                        if pt and pt.strip() in record_url:
                            proxy_address = proxy_addr_bak or None

            while True:
                if exit_recording or bool(stop_token and stop_token.shutdown_requested):
                    return
                try:
                    port_info = []
                    if resolved_once is not None:
                        resolved_payload = dict(resolved_once)
                        resolved_platform_name = resolved_payload.pop("platform_name", None)
                        resolved_display_name = resolved_payload.pop("display_name", None)
                        dispatch_result = DispatchResult(
                            handled=True,
                            platform_name=resolved_platform_name,
                            display_name=resolved_display_name,
                            stream_info=resolved_payload,
                        )
                        resolved_once = None
                    else:
                        dispatch_result = resolve_registered_platform_once(record_url, record_quality, proxy_address)

                    if dispatch_result.error is not None:
                        logger.warning(
                            f"平台注册表路径失败，将回退旧分发: {dispatch_result.display_name} | "
                            f"{record_url} | {dispatch_result.error}"
                        )

                    if dispatch_result.handled:
                        platform = dispatch_result.display_name or "未知平台"
                        port_info = dispatch_result.stream_info or {}
                    elif record_url.find("douyin.com/") > -1:
                        platform = '抖音直播'
                        with semaphore:
                            if 'v.douyin.com' not in record_url and '/user/' not in record_url:
                                json_data = run_async(spider.get_douyin_web_stream_data(
                                    url=record_url,
                                    proxy_addr=proxy_address,
                                    cookies=dy_cookie))
                            else:
                                json_data = run_async(spider.get_douyin_app_stream_data(
                                    url=record_url,
                                    proxy_addr=proxy_address,
                                    cookies=dy_cookie))
                            port_info = run_async(
                                stream.get_douyin_stream_url(json_data, record_quality, proxy_address))

                    elif record_url.find("https://www.tiktok.com/") > -1:
                        platform = 'TikTok直播'
                        with semaphore:
                            if global_proxy or proxy_address:
                                json_data = run_async(spider.get_tiktok_stream_data(
                                    url=record_url,
                                    proxy_addr=proxy_address,
                                    cookies=tiktok_cookie))
                                port_info = run_async(
                                    stream.get_tiktok_stream_url(json_data, record_quality, proxy_address))
                            else:
                                logger.error("错误信息: 网络异常，请检查网络是否能正常访问TikTok平台")

                    elif record_url.find("https://live.kuaishou.com/") > -1:
                        platform = '快手直播'
                        with semaphore:
                            json_data = run_async(spider.get_kuaishou_stream_data(
                                url=record_url,
                                proxy_addr=proxy_address,
                                cookies=ks_cookie))
                            port_info = run_async(stream.get_kuaishou_stream_url(json_data, record_quality))

                    elif record_url.find("https://www.huya.com/") > -1:
                        platform = '虎牙直播'
                        with semaphore:
                            if record_quality not in ['OD', 'BD', 'UHD']:
                                json_data = run_async(spider.get_huya_stream_data(
                                    url=record_url,
                                    proxy_addr=proxy_address,
                                    cookies=hy_cookie))
                                port_info = run_async(stream.get_huya_stream_url(json_data, record_quality))
                            else:
                                port_info = run_async(spider.get_huya_app_stream_url(
                                    url=record_url,
                                    proxy_addr=proxy_address,
                                    cookies=hy_cookie
                                ))

                    elif record_url.find("https://www.douyu.com/") > -1:
                        platform = '斗鱼直播'
                        with semaphore:
                            json_data = run_async(spider.get_douyu_info_data(
                                url=record_url, proxy_addr=proxy_address, cookies=douyu_cookie))
                            port_info = run_async(stream.get_douyu_stream_url(
                                json_data, video_quality=record_quality, cookies=douyu_cookie, proxy_addr=proxy_address
                            ))

                    elif record_url.find("https://www.yy.com/") > -1:
                        platform = 'YY直播'
                        with semaphore:
                            json_data = run_async(spider.get_yy_stream_data(
                                url=record_url, proxy_addr=proxy_address, cookies=yy_cookie))
                            port_info = run_async(stream.get_yy_stream_url(json_data))

                    elif record_url.find("https://live.bilibili.com/") > -1:
                        platform = 'B站直播'
                        with semaphore:
                            json_data = run_async(spider.get_bilibili_room_info(
                                url=record_url, proxy_addr=proxy_address, cookies=bili_cookie))
                            port_info = run_async(stream.get_bilibili_stream_url(
                                json_data, video_quality=record_quality, cookies=bili_cookie, proxy_addr=proxy_address))

                    elif record_url.find("http://xhslink.com/") > -1 or \
                            record_url.find("https://www.xiaohongshu.com/") > -1:
                        platform = '小红书直播'
                        with semaphore:
                            port_info = run_async(spider.get_xhs_stream_url(
                                record_url, proxy_addr=proxy_address, cookies=xhs_cookie))
                            retry += 1

                    elif record_url.find("www.bigo.tv/") > -1 or record_url.find("slink.bigovideo.tv/") > -1:
                        platform = 'Bigo直播'
                        with semaphore:
                            port_info = run_async(spider.get_bigo_stream_url(
                                record_url, proxy_addr=proxy_address, cookies=bigo_cookie))

                    elif record_url.find("https://app.blued.cn/") > -1:
                        platform = 'Blued直播'
                        with semaphore:
                            port_info = run_async(spider.get_blued_stream_url(
                                record_url, proxy_addr=proxy_address, cookies=blued_cookie))

                    elif record_url.find("sooplive.co.kr/") > -1 or record_url.find("sooplive.com/") > -1:
                        platform = 'SOOP'
                        with semaphore:
                            if global_proxy or proxy_address:
                                json_data = run_async(spider.get_sooplive_stream_data(
                                    url=record_url, proxy_addr=proxy_address,
                                    cookies=sooplive_cookie,
                                    username=sooplive_username,
                                    password=sooplive_password
                                ))
                                if json_data and json_data.get('new_cookies'):
                                    utils.update_config(
                                        config_file, 'Cookie', 'sooplive_cookie', json_data['new_cookies']
                                    )
                                port_info = run_async(stream.get_stream_url(json_data, record_quality, spec=True))
                            else:
                                logger.error("错误信息: 网络异常，请检查本网络是否能正常访问SOOP平台")

                    elif record_url.find("cc.163.com/") > -1:
                        platform = '网易CC直播'
                        with semaphore:
                            json_data = run_async(spider.get_netease_stream_data(
                                url=record_url, cookies=netease_cookie))
                            port_info = run_async(stream.get_netease_stream_url(json_data, record_quality))

                    elif record_url.find("qiandurebo.com/") > -1:
                        platform = '千度热播'
                        with semaphore:
                            port_info = run_async(spider.get_qiandurebo_stream_data(
                                url=record_url, proxy_addr=proxy_address, cookies=qiandurebo_cookie))

                    elif record_url.find("www.pandalive.co.kr/") > -1:
                        platform = 'PandaTV'
                        with semaphore:
                            if global_proxy or proxy_address:
                                json_data = run_async(spider.get_pandatv_stream_data(
                                    url=record_url,
                                    proxy_addr=proxy_address,
                                    cookies=pandatv_cookie
                                ))
                                port_info = run_async(stream.get_stream_url(json_data, record_quality, spec=True))
                            else:
                                logger.error("错误信息: 网络异常，请检查本网络是否能正常访问PandaTV直播平台")

                    elif record_url.find("fm.missevan.com/") > -1:
                        platform = '猫耳FM直播'
                        with semaphore:
                            port_info = run_async(spider.get_maoerfm_stream_url(
                                url=record_url, proxy_addr=proxy_address, cookies=maoerfm_cookie))

                    elif record_url.find("www.winktv.co.kr/") > -1:
                        platform = 'WinkTV'
                        with semaphore:
                            if global_proxy or proxy_address:
                                json_data = run_async(spider.get_winktv_stream_data(
                                    url=record_url,
                                    proxy_addr=proxy_address,
                                    cookies=winktv_cookie))
                                port_info = run_async(stream.get_stream_url(json_data, record_quality, spec=True))
                            else:
                                logger.error("错误信息: 网络异常，请检查本网络是否能正常访问WinkTV直播平台")

                    elif record_url.find("www.flextv.co.kr/") > -1 or record_url.find("www.ttinglive.com/") > -1:
                        platform = 'FlexTV'
                        with semaphore:
                            if global_proxy or proxy_address:
                                json_data = run_async(spider.get_flextv_stream_data(
                                    url=record_url,
                                    proxy_addr=proxy_address,
                                    cookies=flextv_cookie,
                                    username=flextv_username,
                                    password=flextv_password
                                ))
                                if json_data and json_data.get('new_cookies'):
                                    utils.update_config(
                                        config_file, 'Cookie', 'flextv_cookie', json_data['new_cookies']
                                    )
                                if 'play_url_list' in json_data:
                                    port_info = run_async(stream.get_stream_url(json_data, record_quality, spec=True))
                                else:
                                    port_info = json_data
                            else:
                                logger.error("错误信息: 网络异常，请检查本网络是否能正常访问FlexTV直播平台")

                    elif record_url.find("look.163.com/") > -1:
                        platform = 'Look直播'
                        with semaphore:
                            port_info = run_async(spider.get_looklive_stream_url(
                                url=record_url, proxy_addr=proxy_address, cookies=look_cookie
                            ))

                    elif record_url.find("www.popkontv.com/") > -1:
                        platform = 'PopkonTV'
                        with semaphore:
                            if global_proxy or proxy_address:
                                port_info = run_async(spider.get_popkontv_stream_url(
                                    url=record_url,
                                    proxy_addr=proxy_address,
                                    access_token=popkontv_access_token,
                                    username=popkontv_username,
                                    password=popkontv_password,
                                    partner_code=popkontv_partner_code
                                ))
                                if port_info and port_info.get('new_token'):
                                    utils.update_config(
                                        file_path=config_file, section='Authorization', key='popkontv_token',
                                        new_value=port_info['new_token']
                                    )

                            else:
                                logger.error("错误信息: 网络异常，请检查本网络是否能正常访问PopkonTV直播平台")

                    elif record_url.find("twitcasting.tv/") > -1:
                        platform = 'TwitCasting'
                        with semaphore:
                            json_data = run_async(spider.get_twitcasting_stream_url(
                                url=record_url,
                                proxy_addr=proxy_address,
                                cookies=twitcasting_cookie,
                                account_type=twitcasting_account_type,
                                username=twitcasting_username,
                                password=twitcasting_password
                            ))
                            port_info = run_async(stream.get_stream_url(json_data, record_quality, spec=False))

                            if port_info and port_info.get('new_cookies'):
                                utils.update_config(
                                    file_path=config_file, section='Cookie', key='twitcasting_cookie',
                                    new_value=port_info['new_cookies']
                                )

                    elif record_url.find("live.baidu.com/") > -1:
                        platform = '百度直播'
                        with semaphore:
                            json_data = run_async(spider.get_baidu_stream_data(
                                url=record_url,
                                proxy_addr=proxy_address,
                                cookies=baidu_cookie))
                            port_info = run_async(stream.get_stream_url(json_data, record_quality))

                    elif record_url.find("weibo.com/") > -1:
                        platform = '微博直播'
                        with semaphore:
                            json_data = run_async(spider.get_weibo_stream_data(
                                url=record_url, proxy_addr=proxy_address, cookies=weibo_cookie))
                            port_info = run_async(stream.get_stream_url(
                                json_data, record_quality, hls_extra_key='m3u8_url'))

                    elif record_url.find("kugou.com/") > -1:
                        platform = '酷狗直播'
                        with semaphore:
                            port_info = run_async(spider.get_kugou_stream_url(
                                url=record_url, proxy_addr=proxy_address, cookies=kugou_cookie))

                    elif record_url.find("www.twitch.tv/") > -1:
                        platform = 'TwitchTV'
                        with semaphore:
                            if global_proxy or proxy_address:
                                json_data = run_async(spider.get_twitchtv_stream_data(
                                    url=record_url,
                                    proxy_addr=proxy_address,
                                    cookies=twitch_cookie
                                ))
                                port_info = run_async(stream.get_stream_url(json_data, record_quality, spec=True))
                            else:
                                logger.error("错误信息: 网络异常，请检查本网络是否能正常访问TwitchTV直播平台")

                    elif record_url.find("www.liveme.com/") > -1:
                        if global_proxy or proxy_address:
                            platform = 'LiveMe'
                            with semaphore:
                                port_info = run_async(spider.get_liveme_stream_url(
                                    url=record_url, proxy_addr=proxy_address, cookies=liveme_cookie))
                        else:
                            logger.error("错误信息: 网络异常，请检查本网络是否能正常访问LiveMe直播平台")

                    elif record_url.find("www.huajiao.com/") > -1:
                        platform = '花椒直播'
                        with semaphore:
                            port_info = run_async(spider.get_huajiao_stream_url(
                                url=record_url, proxy_addr=proxy_address, cookies=huajiao_cookie))

                    elif record_url.find("7u66.com/") > -1:
                        platform = '流星直播'
                        with semaphore:
                            port_info = run_async(spider.get_liuxing_stream_url(
                                url=record_url, proxy_addr=proxy_address, cookies=liuxing_cookie))

                    elif record_url.find("showroom-live.com/") > -1:
                        platform = 'ShowRoom'
                        with semaphore:
                            json_data = run_async(spider.get_showroom_stream_data(
                                url=record_url, proxy_addr=proxy_address, cookies=showroom_cookie))
                            port_info = run_async(stream.get_stream_url(json_data, record_quality, spec=True))

                    elif record_url.find("live.acfun.cn/") > -1 or record_url.find("m.acfun.cn/") > -1:
                        platform = 'Acfun'
                        with semaphore:
                            json_data = run_async(spider.get_acfun_stream_data(
                                url=record_url, proxy_addr=proxy_address, cookies=acfun_cookie))
                            port_info = run_async(stream.get_stream_url(
                                json_data, record_quality, url_type='flv', flv_extra_key='url'))

                    elif record_url.find("live.tlclw.com/") > -1:
                        platform = '畅聊直播'
                        with semaphore:
                            port_info = run_async(spider.get_changliao_stream_url(
                                url=record_url, proxy_addr=proxy_address, cookies=changliao_cookie))

                    elif record_url.find("ybw1666.com/") > -1:
                        platform = '音播直播'
                        with semaphore:
                            port_info = run_async(spider.get_yinbo_stream_url(
                                url=record_url, proxy_addr=proxy_address, cookies=yinbo_cookie))

                    elif record_url.find("www.inke.cn/") > -1:
                        platform = '映客直播'
                        with semaphore:
                            port_info = run_async(spider.get_yingke_stream_url(
                                url=record_url, proxy_addr=proxy_address, cookies=yingke_cookie))

                    elif record_url.find("www.zhihu.com/") > -1:
                        platform = '知乎直播'
                        with semaphore:
                            port_info = run_async(spider.get_zhihu_stream_url(
                                url=record_url, proxy_addr=proxy_address, cookies=zhihu_cookie))

                    elif record_url.find("chzzk.naver.com/") > -1:
                        platform = 'CHZZK'
                        with semaphore:
                            json_data = run_async(spider.get_chzzk_stream_data(
                                url=record_url, proxy_addr=proxy_address, cookies=chzzk_cookie))
                            port_info = run_async(stream.get_stream_url(json_data, record_quality, spec=True))

                    elif record_url.find("www.haixiutv.com/") > -1:
                        platform = '嗨秀直播'
                        with semaphore:
                            port_info = run_async(spider.get_haixiu_stream_url(
                                url=record_url, proxy_addr=proxy_address, cookies=haixiu_cookie))

                    elif record_url.find("vvxqiu.com/") > -1:
                        platform = 'VV星球'
                        with semaphore:
                            port_info = run_async(spider.get_vvxqiu_stream_url(
                                url=record_url, proxy_addr=proxy_address, cookies=vvxqiu_cookie))

                    elif record_url.find("17.live/") > -1:
                        platform = '17Live'
                        with semaphore:
                            port_info = run_async(spider.get_17live_stream_url(
                                url=record_url, proxy_addr=proxy_address, cookies=yiqilive_cookie))

                    elif record_url.find("www.lang.live/") > -1:
                        platform = '浪Live'
                        with semaphore:
                            port_info = run_async(spider.get_langlive_stream_url(
                                url=record_url, proxy_addr=proxy_address, cookies=langlive_cookie))

                    elif record_url.find("m.pp.weimipopo.com/") > -1:
                        platform = '漂漂直播'
                        with semaphore:
                            port_info = run_async(spider.get_pplive_stream_url(
                                url=record_url, proxy_addr=proxy_address, cookies=pplive_cookie))

                    elif record_url.find(".6.cn/") > -1:
                        platform = '六间房直播'
                        with semaphore:
                            port_info = run_async(spider.get_6room_stream_url(
                                url=record_url, proxy_addr=proxy_address, cookies=six_room_cookie))

                    elif record_url.find("lehaitv.com/") > -1:
                        platform = '乐嗨直播'
                        with semaphore:
                            port_info = run_async(spider.get_haixiu_stream_url(
                                url=record_url, proxy_addr=proxy_address, cookies=lehaitv_cookie))

                    elif record_url.find("h.catshow168.com/") > -1:
                        platform = '花猫直播'
                        with semaphore:
                            port_info = run_async(spider.get_pplive_stream_url(
                                url=record_url, proxy_addr=proxy_address, cookies=huamao_cookie))

                    elif record_url.find("live.shopee") > -1 or record_url.find("shp.ee/") > -1:
                        platform = 'shopee'
                        with semaphore:
                            port_info = run_async(spider.get_shopee_stream_url(
                                url=record_url, proxy_addr=proxy_address, cookies=shopee_cookie))
                            if port_info.get('uid'):
                                new_record_url = record_url.split('?')[0] + '?' + str(port_info['uid'])

                    elif record_url.find("www.youtube.com/") > -1 or record_url.find("youtu.be/") > -1:
                        platform = 'Youtube'
                        with semaphore:
                            json_data = run_async(spider.get_youtube_stream_url(
                                url=record_url, proxy_addr=proxy_address, cookies=youtube_cookie))
                            port_info = run_async(stream.get_stream_url(json_data, record_quality, spec=True))

                    elif record_url.find("tb.cn") > -1:
                        platform = '淘宝直播'
                        with semaphore:
                            json_data = run_async(spider.get_taobao_stream_url(
                                url=record_url, proxy_addr=proxy_address, cookies=taobao_cookie))
                            port_info = run_async(stream.get_stream_url(
                                json_data, record_quality,
                                url_type='all', hls_extra_key='hlsUrl', flv_extra_key='flvUrl'
                            ))

                    elif record_url.find("3.cn") > -1 or record_url.find("m.jd.com") > -1:
                        platform = '京东直播'
                        with semaphore:
                            port_info = run_async(spider.get_jd_stream_url(
                                url=record_url, proxy_addr=proxy_address, cookies=jd_cookie))

                    elif record_url.find("faceit.com/") > -1:
                        platform = 'faceit'
                        with semaphore:
                            if global_proxy or proxy_address:
                                with semaphore:
                                    json_data = run_async(spider.get_faceit_stream_data(
                                        url=record_url, proxy_addr=proxy_address, cookies=faceit_cookie))
                                    port_info = run_async(stream.get_stream_url(json_data, record_quality, spec=True))
                            else:
                                logger.error("错误信息: 网络异常，请检查本网络是否能正常访问faceit直播平台")

                    elif record_url.find("www.miguvideo.com") > -1 or record_url.find("m.miguvideo.com") > -1:
                        platform = '咪咕直播'
                        with semaphore:
                            port_info = run_async(spider.get_migu_stream_url(
                                url=record_url, proxy_addr=proxy_address, cookies=migu_cookie))

                    elif record_url.find("show.lailianjie.com") > -1:
                        platform = '连接直播'
                        with semaphore:
                            port_info = run_async(spider.get_lianjie_stream_url(
                                url=record_url, proxy_addr=proxy_address, cookies=lianjie_cookie))

                    elif record_url.find("www.imkktv.com") > -1:
                        platform = '来秀直播'
                        with semaphore:
                            port_info = run_async(spider.get_laixiu_stream_url(
                                url=record_url, proxy_addr=proxy_address, cookies=laixiu_cookie))

                    elif record_url.find("www.picarto.tv") > -1:
                        platform = 'Picarto'
                        with semaphore:
                            port_info = run_async(spider.get_picarto_stream_url(
                                url=record_url, proxy_addr=proxy_address, cookies=picarto_cookie))

                    elif record_url.find(".m3u8") > -1 or record_url.find(".flv") > -1:
                        platform = '自定义录制直播'
                        port_info = {
                            "anchor_name": platform + '_' + str(uuid.uuid4())[:8],
                            "is_live": True,
                            "record_url": record_url,
                        }
                        if '.flv' in record_url:
                            port_info['flv_url'] = record_url
                        else:
                            port_info['m3u8_url'] = record_url

                    else:
                        logger.error(f'{record_url} {platform}直播地址')
                        return

                    port_info = normalize_stream_info(port_info)

                    if anchor_name:
                        if '主播:' in anchor_name:
                            anchor_split: list = anchor_name.split('主播:')
                            if len(anchor_split) > 1 and anchor_split[1].strip():
                                anchor_name = anchor_split[1].strip()
                            else:
                                anchor_name = port_info.get("anchor_name", '')
                    else:
                        anchor_name = port_info.get("anchor_name", '')

                    if not port_info.get("anchor_name", ''):
                        dashboard_store.mark_retrying(record_url, "网址内容获取失败，等待重试")
                        dashboard_store.report_incident(
                            record_url,
                            "probe",
                            "网址内容获取失败，等待重试",
                            disposition=AttentionDisposition.AUTOMATIC,
                        )
                        with max_request_lock:
                            error_count += 1
                            error_window.append(1)
                    else:
                        dashboard_store.clear_incident(
                            record_url,
                            "probe",
                            recovery_message="连接已恢复",
                        )
                        anchor_name = clean_name(anchor_name)
                        record_name = f'序号{count_variable} {anchor_name}'

                        if record_url in url_comments:
                            dashboard_store.mark_disabled(record_url)
                            dashboard_store.add_event(record_url, "disabled", f"{anchor_name} 已停用")
                            clear_record_info(record_name, record_url)
                            return

                        if not url_data[-1] and run_once is False:
                            if new_record_url:
                                need_update_line_list.append(
                                    f'{record_url}|{new_record_url},主播: {anchor_name.strip()}')
                                not_record_list.append(new_record_url)
                            else:
                                need_update_line_list.append(f'{record_url}|{record_url},主播: {anchor_name.strip()}')
                            run_once = True

                        push_at = datetime.datetime.today().strftime('%Y-%m-%d %H:%M:%S')
                        if port_info['is_live'] is False:
                            dashboard_store.mark_monitoring(record_url)

                            if start_pushed:
                                if over_show_push:
                                    push_content = "直播间状态更新：[直播间名称] 直播已结束！时间：[时间]"
                                    if over_push_message_text:
                                        push_content = over_push_message_text

                                    push_content = (push_content.replace('[直播间名称]', record_name).
                                                    replace('[时间]', push_at))
                                    threading.Thread(
                                        target=push_message,
                                        args=(record_name, record_url, push_content.replace(r'\n', '\n')),
                                        daemon=True
                                    ).start()
                                start_pushed = False

                        else:
                            content = f"\r{record_name} 正在直播中..."
                            logger.debug(content.strip())

                            if live_status_push and not start_pushed:
                                if begin_show_push:
                                    push_content = "直播间状态更新：[直播间名称] 正在直播中，时间：[时间]"
                                    if begin_push_message_text:
                                        push_content = begin_push_message_text

                                    push_content = (push_content.replace('[直播间名称]', record_name).
                                                    replace('[时间]', push_at))
                                    threading.Thread(
                                        target=push_message,
                                        args=(record_name, record_url, push_content.replace(r'\n', '\n')),
                                        daemon=True
                                    ).start()
                                start_pushed = True

                            if disable_record:
                                if single_cycle:
                                    session_state["start_pushed"] = start_pushed
                                    session_state["run_once"] = run_once
                                    return
                                time.sleep(push_check_seconds)
                                continue

                            real_url = select_source_url(record_url, port_info)
                            if real_url:
                                if platform != "自定义录制直播":
                                    if enable_https_recording and real_url.startswith("http://"):
                                        real_url = real_url.replace("http://", "https://", 1)
                                    if platform in {"shopee", "migu"}:
                                        real_url = real_url.replace("https://", "http://", 1)

                                direct_flv = platform in {"shopee", "花椒直播"}
                                audio_only = platform in {"猫耳FM直播", "Look直播"}
                                record_save_type = video_save_type
                                if is_flv_preferred_platform(record_url) and port_info.get("flv_url"):
                                    codec = utils.get_query_params(port_info["flv_url"], "codec")
                                    if codec and codec[0] == "h265":
                                        logger.warning("FLV is not supported for h265 codec, use TS format instead")
                                        record_save_type = "TS"

                                source_url = port_info.get("flv_url") if direct_flv else real_url
                                if not source_url:
                                    logger.debug("未找到可录制的直播流，跳过录制")
                                    if single_cycle:
                                        session_state["start_pushed"] = start_pushed
                                        session_state["run_once"] = run_once
                                        return
                                    continue

                                output_root = Path(video_save_path) if video_save_path else Path(default_path)
                                save_format = SaveFormat.parse(record_save_type)
                                overseas = any(host in record_url for host in overseas_platform_host)
                                pipeline_output = {}

                                def on_pipeline_start(
                                    plan,
                                    pipeline_output=pipeline_output,
                                    record_name=record_name,
                                    record_quality_zh=record_quality_zh,
                                    anchor_name=anchor_name,
                                    record_url=record_url,
                                ):
                                    pipeline_output["path"] = str(plan.output_path)
                                    pipeline_output["save_format"] = plan.save_format.value
                                    recording.add(record_name)
                                    recording_time_list[record_name] = [
                                        datetime.datetime.now(),
                                        record_quality_zh,
                                    ]
                                    started_at = datetime.datetime.now().astimezone()
                                    dashboard_store.mark_recording(
                                        record_url,
                                        record_name,
                                        record_quality_zh,
                                        started_at,
                                        output_path=str(plan.output_path),
                                    )
                                    dashboard_store.add_event(
                                        record_url,
                                        "recording_started",
                                        f"{anchor_name} 开始录制",
                                        at=started_at,
                                        correlation_id=f"recording:{record_url}:{plan.output_path}",
                                    )
                                    dashboard_store.clear_incident(
                                        record_url,
                                        "recording-connection",
                                        recovery_message="录制连接已恢复",
                                    )
                                    logger.info(f"{anchor_name} 开始录制: {plan.output_path}")
                                    if create_time_file and not plan.segmented and plan.save_format not in {
                                        SaveFormat.MP3,
                                        SaveFormat.M4A,
                                    }:
                                        subs_file_path = str(plan.output_path.with_suffix(""))
                                        subs_thread_name = f"subs_{plan.output_path.stem}"
                                        create_var[subs_thread_name] = threading.Thread(
                                            target=generate_subtitles,
                                            args=(record_name, subs_file_path),
                                            daemon=True,
                                        )
                                        create_var[subs_thread_name].start()

                                def run_record_script(
                                    command,
                                    pipeline_output=pipeline_output,
                                    record_name=record_name,
                                    save_format=save_format,
                                ):
                                    save_file_path = pipeline_output.get("path", "")
                                    actual_save_format = pipeline_output.get("save_format", save_format.value)
                                    if "python" in command:
                                        params = [
                                            f'--record_name "{record_name}"',
                                            f'--save_file_path "{save_file_path}"',
                                            f"--save_type {actual_save_format}",
                                            f"--split_video_by_time {split_video_by_time}",
                                            f"--converts_to_mp4 {converts_to_mp4}",
                                        ]
                                    else:
                                        params = [
                                            f'"{record_name.split(" ", maxsplit=1)[-1]}"',
                                            f'"{save_file_path}"',
                                            actual_save_format,
                                            f"split_video_by_time:{split_video_by_time}",
                                            f"converts_to_mp4:{converts_to_mp4}",
                                        ]
                                    run_script(command.strip() + " " + " ".join(params))

                                def download_direct(
                                    source,
                                    output,
                                    record_name=record_name,
                                    record_url=record_url,
                                    platform=platform,
                                ):
                                    return direct_download_stream(
                                        source,
                                        str(output),
                                        record_name,
                                        record_url,
                                        platform,
                                    )

                                request = RecordRequest(
                                    anchor_name=anchor_name,
                                    platform=platform,
                                    room_url=record_url,
                                    source_url=source_url,
                                    title=port_info.get("title"),
                                    output_root=output_root,
                                    save_format=save_format,
                                    folder_by_author=folder_by_author,
                                    folder_by_date=folder_by_time,
                                    folder_by_title=folder_by_title,
                                    filename_by_title=filename_by_title,
                                    clean_emojis=clean_emoji,
                                    split=split_video_by_time,
                                    segment_seconds=int(split_time),
                                    proxy=proxy_address or None,
                                    headers=get_record_headers(platform, record_url),
                                    overseas=overseas,
                                    audio_only=audio_only,
                                    direct_flv=direct_flv,
                                    convert_to_mp4=converts_to_mp4,
                                    convert_to_h264=converts_to_h264,
                                    custom_script=custom_script or None,
                                )

                                def convert_recording_file(
                                    path,
                                    transcode_h264,
                                    index,
                                    total,
                                    record_url=record_url,
                                ):
                                    return ffmpeg_converter.convert(
                                        path,
                                        transcode_h264=transcode_h264,
                                        delete_source=delete_origin_file,
                                        on_progress=make_conversion_progress_callback(index, total, record_url),
                                        startupinfo=get_startup_info(os_type),
                                    )

                                pipeline = RecordingPipeline(
                                    postprocessor=PostProcessor(
                                        converter=convert_recording_file,
                                        script_runner=run_record_script,
                                    ),
                                    direct_downloader=download_direct,
                                )
                                result = pipeline.run(
                                    request,
                                    should_comment_stop=lambda record_url=record_url: (
                                        record_url in url_comments
                                        or bool(stop_token and stop_token.room_stop_requested)
                                    ),
                                    should_exit=lambda: (
                                        exit_recording
                                        or bool(stop_token and stop_token.shutdown_requested)
                                    ),
                                    on_start=on_pipeline_start,
                                    on_finish=lambda record_name=record_name, record_url=record_url: (
                                        recording.discard(record_name),
                                        dashboard_store.mark_recording_finished(record_url),
                                    ),
                                    startupinfo=get_startup_info(os_type),
                                )
                                recording_started_at = recording_time_list.get(
                                    record_name,
                                    [datetime.datetime.now()],
                                )[0]
                                recording_elapsed = max(
                                    0.0,
                                    (datetime.datetime.now() - recording_started_at).total_seconds(),
                                )
                                if result.process.reason.is_success and recording_elapsed < 30:
                                    tail_text = " | ".join(result.process.output_tail[-10:]) or "无 FFmpeg 输出"
                                    logger.warning(
                                        f"录制进程在 {recording_elapsed:.1f} 秒后结束，"
                                        f"返回码 {result.process.return_code}；FFmpeg 尾部: {tail_text}"
                                    )

                                if show_url:
                                    logger.info(f"{platform} | {anchor_name} | 直播源地址: {source_url}")
                                if result.process.reason.is_success:
                                    record_finished = True
                                    notify_recording_finished_upload()
                                    dashboard_store.add_event(
                                        record_url,
                                        "recording_finished",
                                        "录制完成",
                                        correlation_id=f"recording:{record_url}:{result.output.output_path}",
                                        details={"format": result.output.save_format.value},
                                    )
                                    dashboard_store.clear_incident(
                                        record_url,
                                        "recording-connection",
                                        recovery_message="录制连接已恢复",
                                    )
                                else:
                                    error = result.process.error or f"返回码: {result.process.return_code}"
                                    tail_text = " | ".join(result.process.output_tail[-10:]) or "无 FFmpeg 输出"
                                    dashboard_store.mark_retrying(record_url, str(error))
                                    dashboard_store.report_incident(
                                        record_url,
                                        "recording-connection",
                                        f"{error}；FFmpeg 尾部: {tail_text}",
                                        disposition=AttentionDisposition.AUTOMATIC,
                                    )
                                    dashboard_store.add_event(record_url, "recording_error", f"{anchor_name} 录制出错")
                                    logger.error(f"{record_name} 直播录制出错: {error}；FFmpeg 尾部: {tail_text}")
                                    with max_request_lock:
                                        error_count += 1
                                        error_window.append(1)

                                if result.postprocess.errors:
                                    for postprocess_error in result.postprocess.errors:
                                        with conversion_progress_lock:
                                            conversion_failure_count += 1
                                        logger.error(f"录制后处理失败: {postprocess_error}")

                                if result.process.reason in {EndReason.COMMENT_STOPPED, EndReason.EXIT_STOPPED}:
                                    clear_record_info(record_name, record_url)
                                    return

                                count_time = time.time()
                                break

                except Exception as e:
                    logger.error(f"错误信息: {e} 发生错误的行数: {e.__traceback__.tb_lineno}")
                    with max_request_lock:
                        error_count += 1
                        error_window.append(1)

                if single_cycle:
                    session_state["start_pushed"] = start_pushed
                    session_state["run_once"] = run_once
                    session_state["new_record_url"] = new_record_url
                    session_state["count_time"] = count_time
                    return

                num = random.randint(-5, 5) + delay_default
                if num < 0:
                    num = 0
                x = num

                if error_count > 20:
                    x = x + 60
                    logger.warning("瞬时错误太多,延迟加60秒")

                # 这里是.如果录制结束后,循环时间会暂时变成30s后检测一遍. 这样一定程度上防止主播卡顿造成少录
                # 当30秒过后检测一遍后. 会回归正常设置的循环秒数
                if record_finished:
                    count_time_end = time.time() - count_time
                    if count_time_end < 60:
                        x = 30
                    record_finished = False

                else:
                    x = num

                # 这里是正常循环
                while x:
                    x = x - 1
                    if loop_time:
                        logger.debug(f'{anchor_name}循环等待{x}秒')
                    time.sleep(1)
                if loop_time:
                    logger.debug('检测直播间中')
        except Exception as e:
            logger.error(f"错误信息: {e} 发生错误的行数: {e.__traceback__.tb_lineno}")
            with max_request_lock:
                error_count += 1
                error_window.append(1)
            if single_cycle:
                return
            time.sleep(2)


def async_runtime_enabled() -> bool:
    return os.getenv("DLR_ASYNC_RUNTIME", "1").strip().lower() not in {"0", "false", "off"}


def async_runtime_active() -> bool:
    return bool(
        async_runtime_enabled()
        and async_runtime_host is not None
        and async_runtime_host.is_alive
        and async_runtime_host.failure is None
    )


def load_async_runtime_config() -> RuntimeConfig:
    current_config = load_app_config(config_file, encoding=text_encoding)
    try:
        with open(url_config_file, encoding=text_encoding, errors="ignore") as runtime_url_file:
            snapshot = parse_room_config_lines(
                runtime_url_file,
                current_config.recording.default_quality,
            )
    except FileNotFoundError:
        snapshot = parse_room_config_lines((), current_config.recording.default_quality)
    dashboard_store.reconcile_rooms(snapshot.desired_rooms)
    registered_rooms = tuple(room for room in snapshot.desired_rooms if default_registry.find(room.url) is not None)
    return RuntimeConfig(
        rooms=registered_rooms,
        max_requests=max(1, current_config.recording.max_request),
    )


def registered_platform_settings(_room) -> PlatformProbeSettings:
    configured_proxy = globals().get("proxy_addr")
    proxy_address = None
    if configured_proxy:
        for platform_host in globals().get("enable_proxy_platform_list") or ():
            if platform_host and platform_host.strip() in _room.url:
                proxy_address = configured_proxy
                break
    if not proxy_address:
        for platform_host in globals().get("extra_enable_proxy_platform_list") or ():
            if platform_host and platform_host.strip() in _room.url:
                proxy_address = globals().get("proxy_addr_bak") or None
                break
    cookies_by_platform = {
        "douyin": globals().get("dy_cookie"),
        "tiktok": globals().get("tiktok_cookie"),
        "bilibili": globals().get("bili_cookie"),
        "huya": globals().get("hy_cookie"),
    }
    return PlatformProbeSettings(
        proxy_addr=proxy_address,
        cookies_by_platform=cookies_by_platform,
        network_available=bool(global_proxy or proxy_address),
    )


def build_async_runtime_runner() -> RuntimeRunner:
    global async_runtime_state_store
    initial_config = load_async_runtime_config()
    state = StateStore()
    async_runtime_state_store = state
    limiter = AdjustableLimiter(initial_config.max_requests)
    pacer = RequestPacer()
    recordings = RecordingExecutor()
    probe = RegisteredPlatformProbe(default_registry, registered_platform_settings)
    room_sessions: dict[str, dict] = {}
    room_numbers: dict[str, int] = {}

    async def record_registered_room(room, result) -> None:
        room_number = room_numbers.setdefault(room.room_id, len(room_numbers) + 1)
        session = room_sessions.setdefault(room.room_id, {})
        await recordings.run(
            room.room_id,
            lambda token: start_record(
                (room.quality.value, room.url, room.name),
                room_number,
                resolved_once=dict(result.payload),
                single_cycle=True,
                stop_token=token,
                session_state=session,
            ),
        )

    async def mark_runtime_success(room, _result) -> None:
        state.mark_room_success(room.room_id)
        try:
            dashboard_store.mark_monitoring(room.room_id)
            dashboard_store.clear_incident(
                room.room_id,
                "probe",
                recovery_message="连接已恢复",
            )
        except KeyError:
            pass

    async def mark_initial_probe_started(room) -> None:
        try:
            dashboard_store.mark_initial_probe_started(room.room_id)
            dashboard_refresh_event.set()
        except KeyError:
            pass

    async def mark_initial_probe_finished(room) -> None:
        try:
            before = dashboard_store.snapshot()
            dashboard_store.mark_initial_probe_finished(room.room_id)
            after = dashboard_store.snapshot()
            if before.first_sweep_completed_at is None and after.first_sweep_completed_at is not None:
                started_at = after.first_sweep_started_at or after.first_sweep_completed_at
                elapsed = max(0.0, (after.first_sweep_completed_at - started_at).total_seconds())
                dashboard_store.add_event(
                    "system",
                    "first_sweep_completed",
                    f"首次巡检完成：{after.first_sweep_total} 个房间，用时 {elapsed:.1f} 秒",
                )
            dashboard_refresh_event.set()
        except KeyError:
            pass

    monitor = RoomMonitor(
        limiter,
        probe,
        record_registered_room,
        pacer=pacer,
        on_success=mark_runtime_success,
        on_probe_started=mark_initial_probe_started,
        on_probe_finished=mark_initial_probe_finished,
        poll_interval=max(1, delay_default),
    )
    scheduler = RuntimeScheduler(state, monitor.run, retry_delay=max(1, delay_default))
    coordinator = RuntimeCoordinator(
        load_async_runtime_config,
        scheduler,
        limiter,
        pacer=pacer,
        poll_interval=max(1, delay_default),
        refresh_interval=3,
    )
    app = RuntimeApp(
        state,
        scheduler,
        recordings,
        close_http=close_async_clients_for_current_loop,
    )
    return RuntimeRunner(
        coordinator,
        app,
        install_signals=lambda _callback: lambda: None,
    )


def start_async_runtime_host() -> None:
    global async_runtime_host
    if not async_runtime_enabled() or async_runtime_host is not None:
        return
    host = ThreadedRuntimeHost(build_async_runtime_runner)
    try:
        host.start(timeout=10)
    except Exception as error:
        logger.error(f"统一异步运行时启动失败，继续使用兼容调度: {error}")
        return
    async_runtime_host = host


def backup_file(file_path: str, backup_dir_path: str, limit_counts: int = 6) -> None:
    try:
        if not os.path.exists(backup_dir_path):
            os.makedirs(backup_dir_path)

        timestamp = datetime.datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
        backup_file_name = os.path.basename(file_path) + '_' + timestamp
        backup_file_path = os.path.join(backup_dir_path, backup_file_name).replace("\\", "/")
        shutil.copy2(file_path, backup_file_path)

        files = os.listdir(backup_dir_path)
        _files = [f for f in files if f.startswith(os.path.basename(file_path))]
        _files.sort(key=lambda x: os.path.getmtime(os.path.join(backup_dir_path, x)))

        while len(_files) > limit_counts:
            oldest_file = _files[0]
            os.remove(os.path.join(backup_dir_path, oldest_file))
            _files = _files[1:]

    except Exception as e:
        logger.error(f'\r备份配置文件 {file_path} 失败：{str(e)}')


def backup_file_start() -> None:
    config_md5 = ''
    url_config_md5 = ''

    while True:
        try:
            if os.path.exists(config_file):
                new_config_md5 = utils.check_md5(config_file)
                if new_config_md5 != config_md5:
                    backup_file(config_file, backup_dir)
                    config_md5 = new_config_md5

            if os.path.exists(url_config_file):
                new_url_config_md5 = utils.check_md5(url_config_file)
                if new_url_config_md5 != url_config_md5:
                    backup_file(url_config_file, backup_dir)
                    url_config_md5 = new_url_config_md5
            time.sleep(600)
        except Exception as e:
            logger.error(f"备份配置文件失败, 错误信息: {e}")


def check_ffmpeg_existence() -> bool:
    try:
        result = subprocess.run(['ffmpeg', '-version'], check=True, capture_output=True, text=True)
        if result.returncode == 0:
            lines = result.stdout.splitlines()
            version_line = lines[0]
            built_line = lines[1]
            logger.debug(f"{version_line} | {built_line}")
    except subprocess.CalledProcessError as e:
        logger.error(e)
    except FileNotFoundError:
        pass
    available = check_ffmpeg()
    if available:
        time.sleep(1)
    return available


def main() -> int:
    global initial_app_config, language, skip_proxy_check, global_proxy, video_save_path, folder_by_author, folder_by_time, folder_by_title, filename_by_title, clean_emoji, video_save_type, video_record_quality, use_proxy, proxy_addr_bak, proxy_addr, max_request, semaphore, delay_default, local_delay_default, loop_time, show_url, split_video_by_time, enable_https_recording, disk_space_limit, split_time, converts_to_mp4, converts_to_h264, delete_origin_file, create_time_file, is_run_script, custom_script, enable_proxy_platform_list, extra_enable_proxy_platform_list, live_status_push, dingtalk_api_url, xizhi_api_url, bark_msg_api, bark_msg_level, bark_msg_ring, dingtalk_phone_num  # noqa: E501
    global dingtalk_is_atall, tg_token, tg_chat_id, email_host, open_smtp_ssl, smtp_port, login_email, email_password, sender_email, sender_name, to_email, ntfy_api, ntfy_tags, ntfy_email, pushplus_token, push_message_title, begin_push_message_text, over_push_message_text, disable_record, push_check_seconds, begin_show_push, over_show_push, sooplive_username, sooplive_password, flextv_username, flextv_password, popkontv_username, popkontv_partner_code, popkontv_password, twitcasting_account_type, twitcasting_username, twitcasting_password, popkontv_access_token, dy_cookie, ks_cookie, tiktok_cookie, hy_cookie, douyu_cookie, yy_cookie, bili_cookie  # noqa: E501
    global xhs_cookie, bigo_cookie, blued_cookie, sooplive_cookie, netease_cookie, qiandurebo_cookie, pandatv_cookie, maoerfm_cookie, winktv_cookie, flextv_cookie, look_cookie, twitcasting_cookie, baidu_cookie, weibo_cookie, kugou_cookie, twitch_cookie, liveme_cookie, huajiao_cookie, liuxing_cookie, showroom_cookie, acfun_cookie, changliao_cookie, yinbo_cookie, yingke_cookie, zhihu_cookie, chzzk_cookie, haixiu_cookie, vvxqiu_cookie, yiqilive_cookie, langlive_cookie, pplive_cookie, six_room_cookie, lehaitv_cookie, huamao_cookie, shopee_cookie, youtube_cookie, taobao_cookie, jd_cookie, faceit_cookie, migu_cookie  # noqa: E501
    global lianjie_cookie, laixiu_cookie, picarto_cookie, exit_recording, url_comments, text_no_repeat_url, monitoring, url_tuples_list, first_start, first_run, ini_URL_content  # noqa: E501

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # --------------------------初始化程序-------------------------------------
    os.makedirs(os.path.dirname(config_file), exist_ok=True)
    initial_app_config = load_app_config(config_file, encoding=text_encoding)
    if not initial_app_config.push.disable_record and not check_ffmpeg_existence():
        dashboard_store.report_incident(
            "system",
            "ffmpeg",
            "FFmpeg 不可用，无法开始录制",
            disposition=AttentionDisposition.ACTION_REQUIRED,
        )
        logger.error("缺少ffmpeg无法进行录制，程序退出")
        return 1
    t3 = threading.Thread(target=backup_file_start, args=(), daemon=True)
    t3.start()
    utils.remove_duplicate_lines(url_config_file)

    language = initial_app_config.recording.language
    skip_proxy_check = initial_app_config.recording.skip_proxy_check
    if language and 'en' not in language.lower():
        from i18n import translated_print

        builtins.print = translated_print

    try:
        if skip_proxy_check:
            global_proxy = True
        else:
            logger.debug('系统代理检测中，请耐心等待...')
            with urllib.request.urlopen("https://www.google.com/", timeout=15):
                pass
            global_proxy = True
            logger.info('全局/规则网络代理已开启')
            pd = ProxyDetector()
            if pd.is_proxy_enabled():
                proxy_info = pd.get_proxy_info()
                logger.debug(f"System Proxy: http://{proxy_info.ip}:{proxy_info.port}")
    except HTTPError as err:
        logger.warning(f"HTTP error occurred: {err.code} - {err.reason}")
    except URLError:
        logger.info("未检测到全局/规则网络代理，请检查代理配置（若无需录制海外直播请忽略此条提示）")
    except Exception as err:
        logger.warning(f"An unexpected error occurred: {err}")

    while not upload_shutdown_requested():

        try:
            if not os.path.isfile(config_file):
                with open(config_file, 'w', encoding=text_encoding) as file:
                    pass

            ini_URL_content = ''
            if os.path.isfile(url_config_file):
                with open(url_config_file, encoding=text_encoding) as file:
                    ini_URL_content = file.read().strip()

            if not ini_URL_content.strip():
                input_url = input('请输入要录制的主播直播间网址（尽量使用PC网页端的直播间地址）:\n')
                with open(url_config_file, 'w', encoding=text_encoding) as file:
                    file.write(input_url)
        except OSError as err:
            logger.error(f"发生 I/O 错误: {err}")

        app_config = load_app_config(config_file, encoding=text_encoding)
        recording_cfg = app_config.recording
        push_cfg = app_config.push
        account_cfg = app_config.accounts
        auth_cfg = app_config.authorization
        cookie_cfg = app_config.cookies

        video_save_path = recording_cfg.save_path
        start_upload_service(app_config.upload, recording_cfg.save_path)
        folder_by_author = recording_cfg.folder_by_author
        folder_by_time = recording_cfg.folder_by_time
        folder_by_title = recording_cfg.folder_by_title
        filename_by_title = recording_cfg.filename_by_title
        clean_emoji = recording_cfg.clean_emoji
        video_save_type = recording_cfg.save_type.value
        video_record_quality = recording_cfg.default_quality.value
        use_proxy = recording_cfg.use_proxy
        proxy_addr_bak = recording_cfg.proxy_address
        proxy_addr = None if not use_proxy else proxy_addr_bak
        max_request = recording_cfg.max_request
        semaphore = threading.Semaphore(max_request)
        delay_default = recording_cfg.loop_delay_seconds
        local_delay_default = recording_cfg.queue_delay_seconds
        loop_time = recording_cfg.show_loop_time
        show_url = recording_cfg.show_stream_url
        split_video_by_time = recording_cfg.split_video_by_time
        enable_https_recording = recording_cfg.enable_https_recording
        disk_space_limit = recording_cfg.disk_space_limit_gb
        split_time = recording_cfg.split_time_seconds
        converts_to_mp4 = recording_cfg.converts_to_mp4
        converts_to_h264 = recording_cfg.converts_to_h264
        delete_origin_file = recording_cfg.delete_origin_file
        create_time_file = recording_cfg.create_time_file
        is_run_script = recording_cfg.run_script_after_record
        custom_script = recording_cfg.custom_script if is_run_script else None
        enable_proxy_platform_list = list(recording_cfg.proxy_platforms) if recording_cfg.proxy_platforms else None
        extra_enable_proxy_platform_list = (
            list(recording_cfg.extra_proxy_platforms) if recording_cfg.extra_proxy_platforms else None
        )
        live_status_push = push_cfg.channels
        dingtalk_api_url = push_cfg.dingtalk_api_url
        xizhi_api_url = push_cfg.xizhi_api_url
        bark_msg_api = push_cfg.bark_api_url
        bark_msg_level = push_cfg.bark_level
        bark_msg_ring = push_cfg.bark_ring
        dingtalk_phone_num = push_cfg.dingtalk_phone_num
        dingtalk_is_atall = push_cfg.dingtalk_is_atall
        tg_token = push_cfg.tg_token
        tg_chat_id = push_cfg.tg_chat_id
        email_host = push_cfg.email_host
        open_smtp_ssl = push_cfg.open_smtp_ssl
        smtp_port = push_cfg.smtp_port
        login_email = push_cfg.login_email
        email_password = push_cfg.email_password
        sender_email = push_cfg.sender_email
        sender_name = push_cfg.sender_name
        to_email = push_cfg.to_email
        ntfy_api = push_cfg.ntfy_api
        ntfy_tags = push_cfg.ntfy_tags
        ntfy_email = push_cfg.ntfy_email
        pushplus_token = push_cfg.pushplus_token
        push_message_title = push_cfg.push_message_title
        begin_push_message_text = push_cfg.begin_push_message_text
        over_push_message_text = push_cfg.over_push_message_text
        disable_record = push_cfg.disable_record
        push_check_seconds = push_cfg.push_check_seconds
        begin_show_push = push_cfg.begin_show_push
        over_show_push = push_cfg.over_show_push
        sooplive_username = account_cfg.sooplive_username
        sooplive_password = account_cfg.sooplive_password
        flextv_username = account_cfg.flextv_username
        flextv_password = account_cfg.flextv_password
        popkontv_username = account_cfg.popkontv_username
        popkontv_partner_code = account_cfg.popkontv_partner_code
        popkontv_password = account_cfg.popkontv_password
        twitcasting_account_type = account_cfg.twitcasting_account_type
        twitcasting_username = account_cfg.twitcasting_username
        twitcasting_password = account_cfg.twitcasting_password
        popkontv_access_token = auth_cfg.popkontv_token
        dy_cookie = cookie_cfg.get('抖音cookie')
        ks_cookie = cookie_cfg.get('快手cookie')
        tiktok_cookie = cookie_cfg.get('tiktok_cookie')
        hy_cookie = cookie_cfg.get('虎牙cookie')
        douyu_cookie = cookie_cfg.get('斗鱼cookie')
        yy_cookie = cookie_cfg.get('yy_cookie')
        bili_cookie = cookie_cfg.get('B站cookie')
        xhs_cookie = cookie_cfg.get('小红书cookie')
        bigo_cookie = cookie_cfg.get('bigo_cookie')
        blued_cookie = cookie_cfg.get('blued_cookie')
        sooplive_cookie = cookie_cfg.get('sooplive_cookie')
        netease_cookie = cookie_cfg.get('netease_cookie')
        qiandurebo_cookie = cookie_cfg.get('千度热播_cookie')
        pandatv_cookie = cookie_cfg.get('pandatv_cookie')
        maoerfm_cookie = cookie_cfg.get('猫耳fm_cookie')
        winktv_cookie = cookie_cfg.get('winktv_cookie')
        flextv_cookie = cookie_cfg.get('flextv_cookie')
        look_cookie = cookie_cfg.get('look_cookie')
        twitcasting_cookie = cookie_cfg.get('twitcasting_cookie')
        baidu_cookie = cookie_cfg.get('baidu_cookie')
        weibo_cookie = cookie_cfg.get('weibo_cookie')
        kugou_cookie = cookie_cfg.get('kugou_cookie')
        twitch_cookie = cookie_cfg.get('twitch_cookie')
        liveme_cookie = cookie_cfg.get('liveme_cookie')
        huajiao_cookie = cookie_cfg.get('huajiao_cookie')
        liuxing_cookie = cookie_cfg.get('liuxing_cookie')
        showroom_cookie = cookie_cfg.get('showroom_cookie')
        acfun_cookie = cookie_cfg.get('acfun_cookie')
        changliao_cookie = cookie_cfg.get('changliao_cookie')
        yinbo_cookie = cookie_cfg.get('yinbo_cookie')
        yingke_cookie = cookie_cfg.get('yingke_cookie')
        zhihu_cookie = cookie_cfg.get('zhihu_cookie')
        chzzk_cookie = cookie_cfg.get('chzzk_cookie')
        haixiu_cookie = cookie_cfg.get('haixiu_cookie')
        vvxqiu_cookie = cookie_cfg.get('vvxqiu_cookie')
        yiqilive_cookie = cookie_cfg.get('17live_cookie')
        langlive_cookie = cookie_cfg.get('langlive_cookie')
        pplive_cookie = cookie_cfg.get('pplive_cookie')
        six_room_cookie = cookie_cfg.get('6room_cookie')
        lehaitv_cookie = cookie_cfg.get('lehaitv_cookie')
        huamao_cookie = cookie_cfg.get('huamao_cookie')
        shopee_cookie = cookie_cfg.get('shopee_cookie')
        youtube_cookie = cookie_cfg.get('youtube_cookie')
        taobao_cookie = cookie_cfg.get('taobao_cookie')
        jd_cookie = cookie_cfg.get('jd_cookie')
        faceit_cookie = cookie_cfg.get('faceit_cookie')
        migu_cookie = cookie_cfg.get('migu_cookie')
        lianjie_cookie = cookie_cfg.get('lianjie_cookie')
        laixiu_cookie = cookie_cfg.get('laixiu_cookie')
        picarto_cookie = cookie_cfg.get('picarto_cookie')

        video_save_type_list = ("FLV", "MKV", "TS", "MP4", "MP3音频", "M4A音频", "MP3", "M4A")
        if video_save_type and video_save_type.upper() in video_save_type_list:
            video_save_type = video_save_type.upper()
        else:
            video_save_type = "TS"

        check_path = video_save_path or default_path
        if utils.check_disk_capacity(check_path, show=first_run) < disk_space_limit:
            exit_recording = True
            if not recording:
                logger.warning(f"Disk space remaining is below {disk_space_limit} GB. "
                               f"Exiting program due to the disk space limit being reached.")
                return -1

        if first_run:
            start_async_runtime_host()

        try:
            url_comments, line_list, url_line_list = [[] for _ in range(3)]
            with (open(url_config_file, encoding=text_encoding, errors='ignore') as file):
                for origin_line in file:
                    if origin_line in line_list:
                        delete_line(url_config_file, origin_line)
                    line_list.append(origin_line)
                    line = origin_line.strip()
                    if len(line) < 18:
                        continue

                    line_spilt = line.split('主播: ')
                    if len(line_spilt) > 2:
                        line = update_file(url_config_file, line, f'{line_spilt[0]}主播: {line_spilt[-1]}')

                    parsed_entry = parse_url_config_entry(line, default_quality=video_record_quality)
                    if parsed_entry is None:
                        continue

                    normalized_entry = normalize_url_config_entry(parsed_entry)
                    if normalized_entry is None:
                        if not origin_line.startswith('#'):
                            logger.warning(f"{origin_line.strip()} 本行包含未知链接.此条跳过")
                            update_file(url_config_file, old_str=origin_line, new_str=origin_line, start_str='#')
                        continue

                    is_comment_line = normalized_entry.is_comment
                    quality = normalized_entry.quality.value
                    url = normalized_entry.url
                    name = normalized_entry.name

                    if url not in url_line_list:
                        url_line_list.append(url)
                    else:
                        delete_line(url_config_file, origin_line)

                    if parsed_entry.url != url:
                        url = update_file(url_config_file, old_str=parsed_entry.url, new_str=url)

                    url_comments = [i for i in url_comments if url not in i]
                    if is_comment_line:
                        url_comments.append(url)
                    else:
                        new_line = (quality, url, name)
                        url_tuples_list.append(new_line)

            while len(need_update_line_list):
                a = need_update_line_list.pop()
                replace_words = a.split('|')
                if replace_words[0] != replace_words[1]:
                    if replace_words[1].startswith("#"):
                        start_with = '#'
                        new_word = replace_words[1][1:]
                    else:
                        start_with = None
                        new_word = replace_words[1]
                    update_file(url_config_file, old_str=replace_words[0], new_str=new_word, start_str=start_with)

            text_no_repeat_url = list(set(url_tuples_list))
            refresh_dashboard_configuration()

            if len(text_no_repeat_url) > 0:
                compatibility_candidates = [
                    url_tuple
                    for url_tuple in text_no_repeat_url
                    if not (async_runtime_active() and default_registry.find(url_tuple[1]) is not None)
                    and url_tuple[1] not in not_record_list
                    and url_tuple[1] not in running_list
                ]
                compatibility_spacing = calculate_legacy_first_start_spacing(
                    len(compatibility_candidates),
                    local_delay_default,
                )
                for candidate_index, url_tuple in enumerate(compatibility_candidates):
                    if exit_recording:
                        break
                    monitoring = len(running_list)
                    dashboard_store.add_event(url_tuple[1], "room_added", f"{url_tuple[2] or url_tuple[1]} 加入监控")
                    monitoring += 1
                    args = [url_tuple, monitoring]
                    create_var[f'thread_{monitoring}'] = threading.Thread(target=start_record, args=args)
                    create_var[f'thread_{monitoring}'].daemon = True
                    create_var[f'thread_{monitoring}'].start()
                    running_list.append(url_tuple[1])
                    if candidate_index < len(compatibility_candidates) - 1:
                        time.sleep(compatibility_spacing)
            url_tuples_list = []
            first_start = False

        except Exception as err:
            logger.error(f"错误信息: {err} 发生错误的行数: {err.__traceback__.tb_lineno}")

        if first_run:
            t = threading.Thread(target=display_info, args=(), daemon=True)
            t.start()
            t2 = threading.Thread(target=adjust_max_request, args=(), daemon=True)
            t2.start()
            first_run = False

        time.sleep(3)


if __name__ == "__main__":
    raise SystemExit(main())
