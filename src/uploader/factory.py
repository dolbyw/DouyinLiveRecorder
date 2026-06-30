from __future__ import annotations

from src.models import UploadConfig

from .rc_service import ProgressCallback, RcloneRcUploadService
from .service import RcloneUploadService


def create_upload_service(config: UploadConfig, *, progress_callback: ProgressCallback | None = None):
    mode = config.execution_mode.strip().lower()
    if mode in {"cli", "command", "commandline", "命令行"}:
        return RcloneUploadService(config)
    return RcloneRcUploadService(config, progress_callback=progress_callback)
