from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.models import UploadConfig

from .rclone_rc import UPLOAD_JOB_GROUP, RcloneRcClient, RcloneRcDaemon, RcloneRcError
from .service import (
    Sleeper,
    StopRequested,
    UploadRunResult,
    UploadStatus,
    _source_file_stats,
    _source_has_files,
    accept_failed_upload_if_remote_verified,
    current_app_root,
    upload_result_from_stop_request,
    upload_result_from_success,
)


@dataclass(frozen=True, slots=True)
class RcloneRcTransferProgress:
    name: str = ""
    percent: float | None = None
    speed_bytes_per_second: float | None = None
    bytes_transferred: int | None = None
    total_bytes: int | None = None


@dataclass(frozen=True, slots=True)
class RcloneRcUploadProgress:
    percent: float | None = None
    speed_bytes_per_second: float | None = None
    bytes_transferred: int | None = None
    total_bytes: int | None = None
    current_file: str = ""
    files_total: int = 0
    files_done: int = 0
    files_waiting: int = 0
    active_transfers: tuple[RcloneRcTransferProgress, ...] = ()


ProgressCallback = Callable[[RcloneRcUploadProgress], None]


class RcloneRcUploadService:
    def __init__(
        self,
        config: UploadConfig,
        *,
        daemon: RcloneRcDaemon | Any | None = None,
        client: RcloneRcClient | Any | None = None,
        sleeper: Sleeper = time.sleep,
        poll_interval_seconds: float = 5.0,
        progress_callback: ProgressCallback | None = None,
        stop_requested: StopRequested | None = None,
    ) -> None:
        self.config = config
        self._client = client or RcloneRcClient(base_url=f"http://127.0.0.1:{config.rc_port}")
        self._daemon = daemon or RcloneRcDaemon(config, client=self._client)
        self._sleeper = sleeper
        self._poll_interval_seconds = max(0.0, poll_interval_seconds)
        self._progress_callback = progress_callback
        self._stop_requested = stop_requested or (lambda: False)
        self._app_root = current_app_root()
        self.status = UploadStatus()

    @property
    def progress_callback(self) -> ProgressCallback | None:
        return self._progress_callback

    @property
    def stop_requested(self) -> StopRequested:
        return self._stop_requested

    def run_once(self, source_path: str | Path) -> UploadRunResult:
        source = Path(source_path)
        files_total, bytes_total = _source_file_stats(source, self.config.exclude_patterns)
        if not _source_has_files(source, self.config.exclude_patterns):
            result = UploadRunResult(
                phase="skipped",
                attempts=0,
                exit_code=0,
                message=f"source has no files: {source}",
            )
            self.status = UploadStatus(phase=result.phase, exit_code=result.exit_code, message=result.message)
            return result
        if self._stop_requested():
            result = upload_result_from_stop_request()
            self.status = UploadStatus(phase=result.phase, exit_code=result.exit_code, message=result.message)
            return result

        max_attempts = max(0, self.config.app_retries) + 1
        last_error = ""
        for attempt in range(1, max_attempts + 1):
            upload_group = f"{UPLOAD_JOB_GROUP}-{time.monotonic_ns()}"
            self.status = UploadStatus(phase="running", attempts=attempt, message=f"attempt {attempt}/{max_attempts}")
            try:
                prepare_remote = getattr(self._daemon, "prepare_remote", None)
                if prepare_remote is not None:
                    prepare_remote()
                self._daemon.start()
                job_id = self._client.start_move(self.config, source, group=upload_group)
                result = self._wait_for_job(
                    job_id,
                    attempt,
                    group=upload_group,
                    files_total=files_total,
                    bytes_total=bytes_total,
                )
            except Exception as error:
                last_error = str(error)
                result = UploadRunResult(
                    phase="failed",
                    attempts=attempt,
                    exit_code=1,
                    stderr=last_error,
                    message="upload failed",
                )
                if isinstance(error, RcloneRcError) and "找不到 rclone" in last_error:
                    self.status = UploadStatus(
                        phase=result.phase,
                        attempts=result.attempts,
                        exit_code=result.exit_code,
                        message=result.message,
                        stderr=result.stderr,
                    )
                    return result
            if result.phase == "skipped":
                self.status = UploadStatus(
                    phase=result.phase,
                    attempts=result.attempts,
                    exit_code=result.exit_code,
                    message=result.message,
                )
                return result
            if result.phase == "success":
                result = upload_result_from_success(
                    source_path=source,
                    attempts=result.attempts,
                    stdout=result.stdout,
                    stderr=result.stderr,
                    message=result.message,
                    files_total=files_total,
                    bytes_total=bytes_total,
                    exclude_patterns=self.config.exclude_patterns,
                )
                self.status = UploadStatus(
                    phase=result.phase,
                    attempts=result.attempts,
                    exit_code=result.exit_code,
                    message=result.message,
                    stdout=result.stdout,
                    stderr=result.stderr,
                )
                return result
            if accept_failed_upload_if_remote_verified(
                self.config,
                source,
                result.stderr or result.message,
                app_root=self._app_root,
            ):
                result = UploadRunResult(
                    phase="success",
                    attempts=attempt,
                    exit_code=0,
                    stdout=result.stderr or result.stdout,
                    message="upload completed after remote verification",
                )
                self.status = UploadStatus(
                    phase=result.phase,
                    attempts=result.attempts,
                    exit_code=result.exit_code,
                    message=result.message,
                    stdout=result.stdout,
                )
                return result
            if not _source_has_files(source, self.config.exclude_patterns):
                result = UploadRunResult(
                    phase="success",
                    attempts=attempt,
                    exit_code=0,
                    stdout=result.stderr or result.stdout,
                    message="上传文件成功，空目录清理警告",
                )
                self.status = UploadStatus(
                    phase=result.phase,
                    attempts=result.attempts,
                    exit_code=result.exit_code,
                    message=result.message,
                    stdout=result.stdout,
                )
                return result
            last_error = result.stderr or result.message
            if attempt < max_attempts:
                self._sleeper(self.config.retry_sleep_seconds)

        result = UploadRunResult(
            phase="failed",
            attempts=max_attempts,
            exit_code=1,
            stderr=last_error,
            message="upload failed",
        )
        self.status = UploadStatus(
            phase=result.phase,
            attempts=result.attempts,
            exit_code=result.exit_code,
            message=result.message,
            stderr=result.stderr,
        )
        return result

    def _wait_for_job(
        self,
        job_id: int,
        attempt: int,
        *,
        group: str = UPLOAD_JOB_GROUP,
        files_total: int = 0,
        bytes_total: int = 0,
    ) -> UploadRunResult:
        while True:
            status = self._client.job_status(job_id)
            if status.get("finished"):
                if status.get("success"):
                    return UploadRunResult(
                        phase="success",
                        attempts=attempt,
                        exit_code=0,
                        stdout=str(status.get("output") or ""),
                        message="upload completed",
                    )
                error = str(status.get("error") or "rclone rc job failed")
                return UploadRunResult(
                    phase="failed",
                    attempts=attempt,
                    exit_code=1,
                    stderr=error,
                    message="upload failed",
                )
            self.status = UploadStatus(
                phase="running",
                attempts=attempt,
                message=self._job_progress_message(status),
            )
            progress = self._progress_from_status(
                status,
                group=group,
                files_total=files_total,
                bytes_total=bytes_total,
            )
            if progress is not None and self._progress_callback is not None:
                self._progress_callback(progress)
            self._sleeper(self._poll_interval_seconds)
            if self._stop_requested():
                stop = getattr(self._daemon, "stop", None)
                if stop is not None:
                    stop()
                return upload_result_from_stop_request(attempts=attempt)

    @staticmethod
    def _job_progress_message(status: dict[str, Any]) -> str:
        progress = status.get("progress")
        if isinstance(progress, dict) and "percentage" in progress:
            return f"{float(progress['percentage']):.1f}%"
        return "running"

    def _progress_from_status(
        self,
        status: dict[str, Any],
        *,
        group: str = UPLOAD_JOB_GROUP,
        files_total: int = 0,
        bytes_total: int = 0,
    ) -> RcloneRcUploadProgress | None:
        try:
            stats = self._client.core_stats(group)
        except Exception:
            stats = None
        if isinstance(stats, dict):
            progress_from_stats = self._progress_from_core_stats(
                stats,
                files_total=files_total,
                bytes_total=bytes_total,
            )
            if progress_from_stats is not None:
                return progress_from_stats

        progress = status.get("progress")
        if not isinstance(progress, dict):
            return None
        return RcloneRcUploadProgress(
            percent=_optional_float(progress.get("percentage")),
            speed_bytes_per_second=_optional_float(progress.get("speed")),
            bytes_transferred=_optional_int(progress.get("bytes")),
            total_bytes=_optional_int(progress.get("totalBytes")),
            current_file=str(progress.get("name") or ""),
            files_total=files_total,
        )

    @staticmethod
    def _progress_from_core_stats(
        stats: dict[str, Any],
        *,
        files_total: int = 0,
        bytes_total: int = 0,
    ) -> RcloneRcUploadProgress | None:
        raw_transferring = stats.get("transferring")
        transferring = raw_transferring if isinstance(raw_transferring, list) else []
        active_transfers: list[RcloneRcTransferProgress] = []
        for transfer in transferring:
            if not isinstance(transfer, dict):
                continue
            active_transfers.append(
                RcloneRcTransferProgress(
                    name=str(transfer.get("name") or ""),
                    percent=_optional_float(transfer.get("percentage")),
                    speed_bytes_per_second=_optional_float(transfer.get("speed")),
                    bytes_transferred=_optional_int(transfer.get("bytes")),
                    total_bytes=_optional_int(transfer.get("size") or transfer.get("totalBytes")),
                )
            )
        bytes_transferred = _optional_int(stats.get("bytes"))
        total_bytes = _optional_int(stats.get("totalBytes")) or (bytes_total or None)
        speed = _optional_float(stats.get("speed"))
        percent = _optional_float(stats.get("percentage"))
        if percent is None and bytes_transferred is not None and total_bytes:
            percent = min(100.0, max(0.0, bytes_transferred / total_bytes * 100))
        files_done = _optional_int(stats.get("transfers")) or 0
        if files_total:
            files_done = min(files_total, max(0, files_done))
        files_waiting = max(0, files_total - files_done - len(active_transfers)) if files_total else 0
        has_progress_data = any(value is not None for value in (percent, speed, bytes_transferred, total_bytes))
        if not has_progress_data and not active_transfers:
            return None
        return RcloneRcUploadProgress(
            percent=percent,
            speed_bytes_per_second=speed,
            bytes_transferred=bytes_transferred,
            total_bytes=total_bytes,
            current_file=active_transfers[0].name if active_transfers else "",
            files_total=files_total,
            files_done=files_done,
            files_waiting=files_waiting,
            active_transfers=tuple(active_transfers),
        )


def _optional_float(value: Any) -> float | None:
    try:
        return None if value is None else float(value)
    except (TypeError, ValueError):
        return None


def _optional_int(value: Any) -> int | None:
    try:
        return None if value is None else int(value)
    except (TypeError, ValueError):
        return None
