from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from src.models import UploadConfig


@dataclass(frozen=True, slots=True)
class RcloneResult:
    exit_code: int
    stdout: str = ""
    stderr: str = ""


@dataclass(frozen=True, slots=True)
class UploadRunResult:
    phase: str
    attempts: int
    exit_code: int
    stdout: str = ""
    stderr: str = ""
    message: str = ""
    files_total: int = 0
    bytes_total: int = 0
    files_remaining: int = 0
    bytes_remaining: int = 0


@dataclass(frozen=True, slots=True)
class UploadStatus:
    phase: str = "idle"
    attempts: int = 0
    exit_code: int | None = None
    message: str = ""
    stdout: str = ""
    stderr: str = ""


RcloneRunner = Callable[[list[str]], RcloneResult]
Sleeper = Callable[[float], None]

_RCLONE_DURATION_PATTERN = re.compile(r"(?P<value>\d+)(?P<unit>ms|s|m|h|d|w|M|y)")
_RCLONE_DURATION_MULTIPLIERS = {
    "ms": 0.001,
    "s": 1,
    "m": 60,
    "h": 60 * 60,
    "d": 24 * 60 * 60,
    "w": 7 * 24 * 60 * 60,
    "M": 30 * 24 * 60 * 60,
    "y": 365 * 24 * 60 * 60,
}


def current_app_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path.cwd()


def resolve_rclone_binary(config: UploadConfig, app_root: str | Path | None = None) -> str:
    if not config.rclone_path:
        return "rclone"
    configured_path = Path(config.rclone_path)
    if configured_path.is_absolute() or app_root is None:
        return str(configured_path)
    return str(Path(app_root) / configured_path)


def resolve_upload_source(config: UploadConfig, recording_save_path: str, default_path: str | Path) -> Path:
    if config.source_path:
        return Path(config.source_path)
    if recording_save_path:
        return Path(recording_save_path)
    return Path(default_path)


def seconds_until_next_daily_run(daily_time: str, now: datetime | None = None) -> int:
    current = now or datetime.now()
    try:
        hour_text, minute_text = daily_time.split(":", maxsplit=1)
        hour = int(hour_text)
        minute = int(minute_text)
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            return 60
    except (ValueError, TypeError):
        return 60

    next_run = current.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if next_run <= current:
        next_run += timedelta(days=1)
    return max(1, int((next_run - current).total_seconds()))


def parse_rclone_duration_seconds(value: str) -> int:
    text = (value or "").strip()
    if not text:
        return 0

    position = 0
    total_seconds = 0.0
    for match in _RCLONE_DURATION_PATTERN.finditer(text):
        if match.start() != position:
            return 0
        position = match.end()
        total_seconds += int(match.group("value")) * _RCLONE_DURATION_MULTIPLIERS[match.group("unit")]
    if position != len(text):
        return 0
    return int(total_seconds)


def build_rclone_move_command(
    config: UploadConfig,
    source_path: str | Path,
    *,
    app_root: str | Path | None = None,
) -> list[str]:
    command = [
        resolve_rclone_binary(config, app_root),
        "move",
        str(Path(source_path)),
        config.remote_path,
        "--min-age",
        config.min_age,
        "--transfers",
        str(config.transfers),
        "--checkers",
        str(config.checkers),
        "--retries",
        str(config.rclone_retries),
        "--stats",
        "1m",
        "-v",
    ]
    if config.delete_empty_dirs:
        command.append("--delete-empty-src-dirs")
    if config.dry_run:
        command.append("--dry-run")
    return command


def build_rclone_config_create_command(
    config: UploadConfig,
    *,
    app_root: str | Path | None = None,
) -> list[str] | None:
    if not (
        config.webdav_remote_name
        and config.webdav_url
        and config.webdav_username
        and config.webdav_password
    ):
        return None
    return [
        resolve_rclone_binary(config, app_root),
        "config",
        "create",
        config.webdav_remote_name,
        "webdav",
        "url",
        config.webdav_url,
        "vendor",
        config.webdav_vendor or "other",
        "user",
        config.webdav_username,
        "pass",
        config.webdav_password,
        "--non-interactive",
        "--obscure",
    ]


def build_rclone_lsjson_command(
    config: UploadConfig,
    *,
    app_root: str | Path | None = None,
) -> list[str]:
    return [
        resolve_rclone_binary(config, app_root),
        "lsjson",
        config.remote_path,
        "--recursive",
    ]


def _source_has_files(source_path: Path) -> bool:
    if not source_path.exists() or not source_path.is_dir():
        return False
    return any(candidate.is_file() for candidate in source_path.rglob("*"))


def _source_file_stats(source_path: Path) -> tuple[int, int]:
    if not source_path.exists() or not source_path.is_dir():
        return 0, 0
    files = [candidate for candidate in source_path.rglob("*") if candidate.is_file()]
    return len(files), sum(candidate.stat().st_size for candidate in files)


def upload_result_from_success(
    *,
    source_path: Path,
    attempts: int,
    stdout: str = "",
    stderr: str = "",
    message: str = "upload completed",
    files_total: int = 0,
    bytes_total: int = 0,
) -> UploadRunResult:
    files_remaining, bytes_remaining = _source_file_stats(source_path)
    if files_remaining:
        return UploadRunResult(
            phase="partial",
            attempts=attempts,
            exit_code=0,
            stdout=stdout,
            stderr=stderr,
            message=f"{message}; 仍有 {files_remaining} 个文件待上传",
            files_total=files_total,
            bytes_total=bytes_total,
            files_remaining=files_remaining,
            bytes_remaining=bytes_remaining,
        )
    return UploadRunResult(
        phase="success",
        attempts=attempts,
        exit_code=0,
        stdout=stdout,
        stderr=stderr,
        message=message,
        files_total=files_total,
        bytes_total=bytes_total,
    )


def accept_failed_upload_if_remote_verified(
    config: UploadConfig,
    source_path: str | Path,
    failure_text: str,
    *,
    app_root: str | Path | None = None,
    runner: RcloneRunner | None = None,
) -> bool:
    if "object not found" not in failure_text.lower():
        return False

    source = Path(source_path)
    local_files = [candidate for candidate in source.rglob("*") if candidate.is_file()]
    if not local_files:
        return False

    lsjson_runner = runner or run_rclone_subprocess
    result = lsjson_runner(build_rclone_lsjson_command(config, app_root=app_root))
    if result.exit_code != 0:
        return False
    try:
        remote_entries = json.loads(result.stdout or "[]")
    except ValueError:
        return False
    if not isinstance(remote_entries, list):
        return False

    remote_sizes = {
        str(entry.get("Path", "")).replace("\\", "/"): int(entry.get("Size", -1))
        for entry in remote_entries
        if isinstance(entry, dict) and not entry.get("IsDir")
    }
    for file_path in local_files:
        remote_path = file_path.relative_to(source).as_posix()
        if remote_sizes.get(remote_path) != file_path.stat().st_size:
            return False

    shutil.rmtree(source)
    return True


def run_rclone_subprocess(command: list[str]) -> RcloneResult:
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            shell=False,
        )
    except FileNotFoundError as error:
        return RcloneResult(exit_code=127, stderr=str(error))
    return RcloneResult(
        exit_code=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
    )


class RcloneUploadService:
    def __init__(
        self,
        config: UploadConfig,
        *,
        runner: RcloneRunner = run_rclone_subprocess,
        sleeper: Sleeper = time.sleep,
    ) -> None:
        self._config = config
        self._runner = runner
        self._sleeper = sleeper
        self._app_root = current_app_root()
        self.status = UploadStatus()

    def run_once(self, source_path: str | Path) -> UploadRunResult:
        source = Path(source_path)
        files_total, bytes_total = _source_file_stats(source)
        if files_total == 0:
            result = UploadRunResult(
                phase="skipped",
                attempts=0,
                exit_code=0,
                message=f"source has no files: {source}",
            )
            self.status = UploadStatus(phase=result.phase, exit_code=result.exit_code, message=result.message)
            return result

        config_command = build_rclone_config_create_command(self._config, app_root=self._app_root)
        if config_command is not None:
            config_result = self._runner(config_command)
            if config_result.exit_code != 0:
                result = UploadRunResult(
                    phase="failed",
                    attempts=0,
                    exit_code=config_result.exit_code,
                    stdout=config_result.stdout,
                    stderr=config_result.stderr,
                    message="webdav remote config failed",
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

        command = build_rclone_move_command(self._config, source, app_root=self._app_root)
        max_attempts = max(0, self._config.app_retries) + 1
        last_result = RcloneResult(exit_code=1)

        for attempt in range(1, max_attempts + 1):
            self.status = UploadStatus(phase="running", attempts=attempt, message=f"attempt {attempt}/{max_attempts}")
            last_result = self._runner(command)
            if last_result.exit_code == 0:
                result = upload_result_from_success(
                    source_path=source,
                    attempts=attempt,
                    stdout=last_result.stdout,
                    stderr=last_result.stderr,
                    message="upload completed",
                    files_total=files_total,
                    bytes_total=bytes_total,
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
            failure_text = f"{last_result.stderr}\n{last_result.stdout}"
            if accept_failed_upload_if_remote_verified(
                self._config,
                source,
                failure_text,
                app_root=self._app_root,
                runner=self._runner,
            ):
                result = UploadRunResult(
                    phase="success",
                    attempts=attempt,
                    exit_code=0,
                    stdout=last_result.stdout,
                    stderr=last_result.stderr,
                    message="upload completed after remote verification",
                    files_total=files_total,
                    bytes_total=bytes_total,
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
            if attempt < max_attempts:
                self._sleeper(self._config.retry_sleep_seconds)

        result = UploadRunResult(
            phase="failed",
            attempts=max_attempts,
            exit_code=last_result.exit_code,
            stdout=last_result.stdout,
            stderr=last_result.stderr,
            message="upload failed",
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
