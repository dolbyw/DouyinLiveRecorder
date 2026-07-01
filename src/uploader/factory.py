from __future__ import annotations

from src.models import UploadConfig

from .rc_service import ProgressCallback, RcloneRcUploadService
from .service import RcloneUploadService, StopRequested


def create_upload_service(
    config: UploadConfig,
    *,
    progress_callback: ProgressCallback | None = None,
    stop_requested: StopRequested | None = None,
):
    mode = config.execution_mode.strip().lower()
    if mode in {"cli", "command", "commandline", "命令行"}:
        return RcloneUploadService(config, stop_requested=stop_requested)
    return RcloneRcUploadService(config, progress_callback=progress_callback, stop_requested=stop_requested)
