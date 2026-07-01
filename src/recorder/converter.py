from __future__ import annotations

import subprocess
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.diagnostic_logging import format_log_context, sanitize_command
from src.logger import logger


class ConversionError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class ConversionProgress:
    source: Path
    elapsed: float
    duration: float | None
    finished: bool = False

    @property
    def percent(self) -> float | None:
        if self.duration is None or self.duration <= 0:
            return None
        return min(100.0, max(0.0, self.elapsed / self.duration * 100.0))


def parse_progress_time(key: str, value: str) -> float | None:
    if key not in {"out_time_us", "out_time_ms"}:
        return None
    try:
        return max(0.0, int(value) / 1_000_000)
    except ValueError:
        return None


class FFmpegConverter:
    def __init__(
        self,
        *,
        executable: str = "ffmpeg",
        probe_executable: str = "ffprobe",
        process_factory: Callable[..., Any] = subprocess.Popen,
        probe_duration: Callable[[Path], float | None] | None = None,
    ) -> None:
        self._executable = executable
        self._probe_executable = probe_executable
        self._process_factory = process_factory
        self._probe_duration = probe_duration or self.probe_duration

    def build_command(self, source: Path, target: Path, *, transcode_h264: bool) -> list[str]:
        codec_args = (
            [
                "-c:v",
                "libx264",
                "-preset",
                "veryfast",
                "-crf",
                "23",
                "-vf",
                "format=yuv420p",
                "-c:a",
                "copy",
            ]
            if transcode_h264
            else ["-c:v", "copy", "-c:a", "copy"]
        )
        return [
            self._executable,
            "-y",
            "-v",
            "error",
            "-i",
            str(source),
            *codec_args,
            "-progress",
            "pipe:1",
            "-nostats",
            str(target),
        ]

    def probe_duration(self, source: Path) -> float | None:
        result = subprocess.run(
            [
                self._probe_executable,
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                str(source),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        duration = float(result.stdout.strip())
        return duration if duration > 0 else None

    def convert(
        self,
        source: Path,
        *,
        transcode_h264: bool = False,
        delete_source: bool = True,
        on_progress: Callable[[ConversionProgress], None] | None = None,
        startupinfo: Any = None,
    ) -> Path:
        source = Path(source)
        if not source.is_file() or source.stat().st_size <= 0:
            raise ConversionError(f"conversion source is missing or empty: {source}")

        final = source.with_suffix(".mp4")
        temporary = source.with_suffix(".converting.mp4")
        temporary.unlink(missing_ok=True)
        try:
            logger.info(
                "conversion started | {}",
                format_log_context(source=source, target=final, transcode_h264=transcode_h264),
            )
            try:
                duration = self._probe_duration(source)
            except Exception as error:
                logger.opt(exception=error).warning(
                    "conversion probe failed | {}",
                    format_log_context(source=source, target=final),
                )
                duration = None

            self._notify(on_progress, ConversionProgress(source, 0.0, duration))
            kwargs: dict[str, Any] = {
                "stdout": subprocess.PIPE,
                "stderr": subprocess.STDOUT,
                "text": True,
                "encoding": "utf-8",
                "errors": "replace",
            }
            if startupinfo is not None:
                kwargs["startupinfo"] = startupinfo
            command = self.build_command(source, temporary, transcode_h264=transcode_h264)
            logger.debug(
                "conversion ffmpeg command prepared | {}",
                format_log_context(command=" ".join(sanitize_command(command)), source=source, target=final),
            )
            process = self._process_factory(command, **kwargs)
            elapsed = 0.0
            diagnostics: list[str] = []
            for line in self._lines(process.stdout):
                stripped = line.strip()
                if not stripped:
                    continue
                key, separator, value = stripped.partition("=")
                progress_time = parse_progress_time(key, value) if separator else None
                if progress_time is not None:
                    elapsed = max(elapsed, progress_time)
                    self._notify(on_progress, ConversionProgress(source, elapsed, duration))
                elif key != "progress":
                    diagnostics.append(stripped)
                    diagnostics = diagnostics[-20:]

            return_code = process.wait()
            if return_code != 0:
                detail = " | ".join(diagnostics) or f"ffmpeg exited with code {return_code}"
                logger.error(
                    "conversion failed | {}",
                    format_log_context(
                        detail=detail,
                        return_code=return_code,
                        source=source,
                        target=final,
                    ),
                )
                raise ConversionError(detail)
            if not temporary.is_file() or temporary.stat().st_size <= 0:
                logger.error(
                    "conversion failed | {}",
                    format_log_context(
                        detail="ffmpeg completed without producing an MP4 file",
                        source=source,
                        target=final,
                    ),
                )
                raise ConversionError("ffmpeg completed without producing an MP4 file")

            temporary.replace(final)
            if delete_source:
                source.unlink()
            completed_elapsed = duration if duration is not None else elapsed
            self._notify(on_progress, ConversionProgress(source, completed_elapsed, duration, finished=True))
            logger.info(
                "conversion completed | {}",
                format_log_context(source=source, target=final, duration_seconds=completed_elapsed),
            )
            return final
        except Exception:
            temporary.unlink(missing_ok=True)
            raise

    @staticmethod
    def _lines(stdout: Iterable[str] | None) -> Iterable[str]:
        return stdout or ()

    @staticmethod
    def _notify(
        callback: Callable[[ConversionProgress], None] | None,
        progress: ConversionProgress,
    ) -> None:
        if callback is None:
            return
        try:
            callback(progress)
        except Exception:
            pass
