from __future__ import annotations

import subprocess
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx

from src.models import UploadConfig

from .service import build_rclone_config_create_command, current_app_root, resolve_rclone_binary, run_rclone_subprocess

UPLOAD_JOB_GROUP = "douyin-live-recorder-upload"


class RcloneRcError(RuntimeError):
    pass


def build_rcd_command(config: UploadConfig, *, app_root: str | Path | None = None) -> list[str]:
    return [
        resolve_rclone_binary(config, app_root),
        "rcd",
        "--rc-addr",
        f"127.0.0.1:{config.rc_port}",
        "--rc-no-auth",
        "--transfers",
        str(config.transfers),
        "--checkers",
        str(config.checkers),
        "--retries",
        str(config.rclone_retries),
    ]


def build_sync_move_payload(config: UploadConfig, source_path: str | Path) -> dict[str, Any]:
    filter_config: dict[str, Any] = {
        "MinAge": config.min_age,
    }
    if config.exclude_patterns:
        filter_config["ExcludeRule"] = list(config.exclude_patterns)
    return {
        "srcFs": str(Path(source_path)),
        "dstFs": config.remote_path,
        "deleteEmptySrcDirs": config.delete_empty_dirs,
        "_async": True,
        "_group": UPLOAD_JOB_GROUP,
        "_config": {
            "Transfers": config.transfers,
            "Checkers": config.checkers,
            "Retries": config.rclone_retries,
            "DryRun": config.dry_run,
        },
        "_filter": filter_config,
    }


class RcloneRcClient:
    def __init__(
        self,
        *,
        base_url: str,
        timeout: float = 30.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._client = httpx.Client(
            base_url=base_url.rstrip("/") + "/",
            timeout=timeout,
            transport=transport,
        )

    def close(self) -> None:
        self._client.close()

    def post(self, endpoint: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        response = self._client.post(endpoint.lstrip("/"), json=payload or {})
        try:
            body = response.json()
        except ValueError:
            body = {"error": response.text}
        if response.status_code >= 400:
            message = body.get("error") if isinstance(body, dict) else None
            raise RcloneRcError(str(message or response.text or response.status_code))
        if not isinstance(body, dict):
            raise RcloneRcError(f"unexpected rclone rc response: {body!r}")
        return body

    def start_move(self, config: UploadConfig, source_path: str | Path) -> int:
        response = self.post("sync/move", build_sync_move_payload(config, source_path))
        try:
            return int(response["jobid"])
        except (KeyError, TypeError, ValueError) as error:
            raise RcloneRcError(f"missing rclone rc jobid: {response!r}") from error

    def job_status(self, job_id: int) -> dict[str, Any]:
        return self.post("job/status", {"jobid": job_id})

    def noop(self) -> dict[str, Any]:
        return self.post("rc/noop", {})


PopenFactory = Callable[[list[str]], subprocess.Popen]
Sleeper = Callable[[float], None]


class RcloneRcDaemon:
    def __init__(
        self,
        config: UploadConfig,
        *,
        client: Any | None = None,
        popen: PopenFactory | None = None,
        sleeper: Sleeper = time.sleep,
        startup_attempts: int = 10,
        startup_interval_seconds: float = 0.5,
    ) -> None:
        self._config = config
        self._client = client or RcloneRcClient(base_url=f"http://127.0.0.1:{config.rc_port}")
        self._popen = popen or self._default_popen
        self._sleeper = sleeper
        self._startup_attempts = max(1, startup_attempts)
        self._startup_interval_seconds = max(0.0, startup_interval_seconds)
        self._app_root = current_app_root()
        self._process: subprocess.Popen | None = None

    @property
    def owns_process(self) -> bool:
        return self._process is not None

    def start(self) -> bool:
        if self._is_ready():
            return False

        command = build_rcd_command(self._config, app_root=self._app_root)
        try:
            self._process = self._popen(command)
        except FileNotFoundError as error:
            binary = command[0]
            raise RcloneRcError(
                f"找不到 rclone 可执行文件: {binary}。请安装 rclone，或在 config.ini 的 "
                "`rclone可执行文件路径` 填写 rclone.exe 的完整路径。"
            ) from error
        last_error: Exception | None = None
        for _attempt in range(self._startup_attempts):
            try:
                self._client.noop()
                return True
            except Exception as error:
                last_error = error
                self._sleeper(self._startup_interval_seconds)

        self.stop()
        raise RcloneRcError(str(last_error or "rclone rc daemon did not become ready"))

    def prepare_remote(self) -> None:
        command = build_rclone_config_create_command(self._config, app_root=self._app_root)
        if command is None:
            return
        result = run_rclone_subprocess(command)
        if result.exit_code != 0:
            raise RcloneRcError(result.stderr or result.stdout or "webdav remote config failed")

    def stop(self) -> None:
        process = self._process
        if process is None:
            return
        self._process = None
        process.terminate()
        try:
            process.wait(timeout=5)
        except Exception:
            process.kill()

    def _is_ready(self) -> bool:
        try:
            self._client.noop()
        except Exception:
            return False
        return True

    @staticmethod
    def _default_popen(command: list[str]) -> subprocess.Popen:
        return subprocess.Popen(
            command,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
