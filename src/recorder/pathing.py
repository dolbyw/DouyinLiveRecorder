from __future__ import annotations

import re
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from .models import OutputPlan, RecordRequest

_INVALID_NAME = re.compile(r"[\/\\\:\*\？?\"\<\>\|&#.。,， ~！· ]")
_EMOJI = re.compile(
    "["
    "\U0001f1e0-\U0001f1ff"
    "\U0001f300-\U0001f5ff"
    "\U0001f600-\U0001f64f"
    "\U0001f680-\U0001f6ff"
    "\U0001f700-\U0001f77f"
    "\U0001f780-\U0001f7ff"
    "\U0001f800-\U0001f8ff"
    "\U0001f900-\U0001f9ff"
    "\U0001fa00-\U0001fa6f"
    "\U0001fa70-\U0001faff"
    "\U00002702-\U000027b0"
    "]+",
)


def sanitize_name(text: str, *, clean_emojis: bool = False) -> str:
    cleaned = _INVALID_NAME.sub("_", text.strip()).strip("_")
    cleaned = cleaned.replace("（", "(").replace("）", ")")
    if clean_emojis:
        cleaned = _EMOJI.sub("_", cleaned).strip("_")
    return cleaned or "空白昵称"


class PathBuilder:
    def __init__(self, now: Callable[[], datetime] = datetime.now) -> None:
        self._now = now

    def build(self, request: RecordRequest) -> OutputPlan:
        timestamp = self._now()
        date = timestamp.strftime("%Y-%m-%d")
        date_time = timestamp.strftime("%Y-%m-%d_%H-%M-%S")
        anchor = sanitize_name(request.anchor_name, clean_emojis=request.clean_emojis)
        title = sanitize_name(request.title, clean_emojis=request.clean_emojis) if request.title else None

        directory = request.output_root / request.platform
        if request.folder_by_author:
            directory /= anchor
        if request.folder_by_date:
            directory /= date
        if request.folder_by_title and title:
            directory /= f"{title}_{anchor}" if request.folder_by_date else f"{date}_{title}"
        directory.mkdir(parents=True, exist_ok=True)

        title_part = f"{title}_" if title and request.filename_by_title else ""
        segment_part = "_%03d" if request.split else ""
        save_format = request.effective_format
        stem = f"{anchor}_{title_part}{date_time}{segment_part}"
        output_path = directory / f"{stem}.{save_format.value.lower()}"
        file_glob = Path(str(output_path).replace("%03d", "*"))
        return OutputPlan(output_path, file_glob, save_format, request.split)
