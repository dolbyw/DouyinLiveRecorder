from __future__ import annotations

import queue
import threading
from collections.abc import Callable
from pathlib import Path

from .models import OutputPlan


class SegmentFinalizer:
    def __init__(self, plan: OutputPlan, *, submit: Callable[[Path], None]) -> None:
        self._plan = plan
        self._submit = submit
        self._seen: set[Path] = set()
        self._sizes: dict[Path, int] = {}

    def scan(self) -> None:
        if not self._plan.segmented:
            return
        files = tuple(
            sorted(
                path
                for path in self._plan.file_glob.parent.glob(self._plan.file_glob.name)
                if path.is_file() and not path.name.endswith(".converting.mp4")
            )
        )
        if len(files) < 2:
            self._remember_sizes(files)
            return

        for path in files[:-1]:
            if path in self._seen:
                continue
            try:
                size = path.stat().st_size
            except OSError:
                continue
            previous_size = self._sizes.get(path)
            self._sizes[path] = size
            if previous_size is None or previous_size != size or size <= 0:
                continue
            self._seen.add(path)
            self._submit(path)

        self._remember_sizes(files[-1:])

    def _remember_sizes(self, files: tuple[Path, ...]) -> None:
        for path in files:
            try:
                self._sizes[path] = path.stat().st_size
            except OSError:
                pass


class SegmentConversionQueue:
    def __init__(
        self,
        *,
        converter: Callable[[Path, bool, int, int], object],
        transcode_h264: bool,
        on_success: Callable[[Path], None] | None = None,
    ) -> None:
        self._converter = converter
        self._transcode_h264 = transcode_h264
        self._on_success = on_success
        self._queue: queue.Queue[Path | None] = queue.Queue()
        self._queued: set[Path] = set()
        self._processed: set[Path] = set()
        self._errors: list[BaseException] = []
        self._lock = threading.Lock()
        self._closed = False
        self._worker = threading.Thread(target=self._run, name="segment-converter", daemon=True)
        self._worker.start()

    def submit(self, path: Path) -> None:
        path = Path(path)
        with self._lock:
            if self._closed or path in self._queued or path in self._processed:
                return
            self._queued.add(path)
        self._queue.put(path)

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
        self._queue.put(None)
        self._worker.join()

    def processed_files(self) -> set[Path]:
        with self._lock:
            return set(self._processed)

    def errors(self) -> tuple[BaseException, ...]:
        with self._lock:
            return tuple(self._errors)

    def _run(self) -> None:
        while True:
            path = self._queue.get()
            if path is None:
                return
            try:
                self._converter(path, self._transcode_h264, 1, 1)
            except Exception as error:
                with self._lock:
                    self._errors.append(error)
            else:
                with self._lock:
                    self._processed.add(path)
                if self._on_success is not None:
                    self._on_success(path)
