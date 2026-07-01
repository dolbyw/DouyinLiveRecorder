from __future__ import annotations

import platform
import re
import signal
import subprocess
import threading
import time
from collections import deque
from collections.abc import Callable
from typing import Any

from .models import EndReason, ProcessResult

_URL_PATTERN = re.compile(r"https?://\S+", re.IGNORECASE)
_SENSITIVE_HEADER_PATTERN = re.compile(r"^\s*(cookie|authorization|headers?)\s*:", re.IGNORECASE)


def sanitize_output_tail(lines: tuple[str, ...]) -> tuple[str, ...]:
    sanitized: list[str] = []
    for line in lines:
        header = _SENSITIVE_HEADER_PATTERN.match(line)
        if header is not None:
            sanitized.append(f"{header.group(1).title()}: [REDACTED]")
        else:
            sanitized.append(_URL_PATTERN.sub("[URL]", line))
    return tuple(sanitized)


class RecorderProcess:
    def __init__(
        self,
        process_factory: Callable[..., Any] = subprocess.Popen,
        sleep: Callable[[float], None] = time.sleep,
        platform_name: str | None = None,
        output_tail_lines: int = 50,
    ) -> None:
        self._process_factory = process_factory
        self._sleep = sleep
        self._platform_name = platform_name or platform.system()
        self._output_tail_lines = max(1, output_tail_lines)

    def run(
        self,
        command: list[str],
        *,
        should_comment_stop: Callable[[], bool],
        should_exit: Callable[[], bool],
        on_started: Callable[[Any], None] | None = None,
        on_tick: Callable[[], None] | None = None,
        startupinfo: Any = None,
    ) -> ProcessResult:
        kwargs = {"stdin": subprocess.PIPE, "stdout": subprocess.PIPE, "stderr": subprocess.STDOUT}
        if startupinfo is not None:
            kwargs["startupinfo"] = startupinfo
        try:
            process = self._process_factory(command, **kwargs)
        except Exception as error:
            return ProcessResult(EndReason.FAILED_TO_START, error=error)
        if on_started is not None:
            on_started(process)
        output_tail: deque[str] = deque(maxlen=self._output_tail_lines)
        output_reader = self._start_output_reader(process, output_tail)

        while True:
            return_code = process.poll()
            if return_code is not None:
                if return_code == 0:
                    return self._result(EndReason.COMPLETED, return_code, None, output_reader, output_tail)
                if should_comment_stop():
                    return self._result(EndReason.COMMENT_STOPPED, return_code, None, output_reader, output_tail)
                if should_exit():
                    return self._result(EndReason.EXIT_STOPPED, return_code, None, output_reader, output_tail)
                return self._result(EndReason.FAILED, return_code, None, output_reader, output_tail)

            if should_comment_stop():
                return self._stop(process, EndReason.COMMENT_STOPPED, output_reader, output_tail)
            if should_exit():
                return self._stop(process, EndReason.EXIT_STOPPED, output_reader, output_tail)
            if on_tick is not None:
                try:
                    on_tick()
                except Exception:
                    pass
            self._sleep(1)

    def _stop(
        self,
        process: Any,
        reason: EndReason,
        output_reader: threading.Thread | None,
        output_tail: deque[str],
    ) -> ProcessResult:
        try:
            if self._platform_name == "Windows":
                if process.stdin is None:
                    raise RuntimeError("ffmpeg stdin is unavailable")
                process.stdin.write(b"q")
                process.stdin.flush()
            else:
                process.send_signal(signal.SIGINT)
            try:
                return_code = process.wait(timeout=15)
            except subprocess.TimeoutExpired as timeout_error:
                process.kill()
                return_code = process.wait(timeout=5)
                return self._result(
                    EndReason.FAILED,
                    return_code,
                    timeout_error,
                    output_reader,
                    output_tail,
                )
        except Exception as error:
            return self._result(EndReason.FAILED, None, error, output_reader, output_tail)
        return self._result(reason, return_code, None, output_reader, output_tail)

    @staticmethod
    def _start_output_reader(process: Any, output_tail: deque[str]) -> threading.Thread | None:
        stdout = getattr(process, "stdout", None)
        if stdout is None:
            return None

        def drain() -> None:
            for raw_line in iter(stdout.readline, b""):
                if isinstance(raw_line, bytes):
                    line = raw_line.decode("utf-8", errors="replace").strip()
                else:
                    line = str(raw_line).strip()
                if line:
                    output_tail.append(line)

        reader = threading.Thread(target=drain, name="ffmpeg-output-reader", daemon=True)
        reader.start()
        return reader

    @staticmethod
    def _result(
        reason: EndReason,
        return_code: int | None,
        error: BaseException | None,
        output_reader: threading.Thread | None,
        output_tail: deque[str],
    ) -> ProcessResult:
        if output_reader is not None:
            output_reader.join(timeout=1)
        return ProcessResult(reason, return_code, error, tuple(output_tail))
