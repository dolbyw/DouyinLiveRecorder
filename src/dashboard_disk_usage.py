from __future__ import annotations

import threading
import time
from collections.abc import Callable
from pathlib import Path

DASHBOARD_RECORDING_SIZE_TTL_SECONDS = 300.0

DirectorySizeScanner = Callable[[Path], int]


def scan_recording_directory_size(save_path: Path) -> int:
    total = 0
    if not save_path.exists():
        return 0
    for candidate in save_path.rglob("*"):
        try:
            if candidate.is_file():
                total += candidate.stat().st_size
        except OSError:
            continue
    return total


class RecordingDirectorySizeCache:
    def __init__(
        self,
        *,
        ttl_seconds: float = DASHBOARD_RECORDING_SIZE_TTL_SECONDS,
        scanner: DirectorySizeScanner = scan_recording_directory_size,
    ) -> None:
        self._ttl_seconds = ttl_seconds
        self._scanner = scanner
        self._path: Path | None = None
        self._size_bytes: int | None = None
        self._checked_at: float | None = None
        self._lock = threading.RLock()

    def get(self, save_path: str | Path, *, now: float | None = None) -> int | None:
        timestamp = time.monotonic() if now is None else now
        path = Path(save_path)
        with self._lock:
            if (
                self._path == path
                and self._checked_at is not None
                and timestamp - self._checked_at < self._ttl_seconds
            ):
                return self._size_bytes
            try:
                size_bytes = self._scanner(path)
            except OSError:
                size_bytes = None
            self._path = path
            self._size_bytes = size_bytes
            self._checked_at = timestamp
            return size_bytes
