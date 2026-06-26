from __future__ import annotations

import subprocess
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any


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
            try:
                duration = self._probe_duration(source)
            except Exception:
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
            process = self._process_factory(
                self.build_command(source, temporary, transcode_h264=transcode_h264),
                **kwargs,
            )
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
                raise ConversionError(detail)
            if not temporary.is_file() or temporary.stat().st_size <= 0:
                raise ConversionError("ffmpeg completed without producing an MP4 file")

            temporary.replace(final)
            if delete_source:
                source.unlink()
            completed_elapsed = duration if duration is not None else elapsed
            self._notify(on_progress, ConversionProgress(source, completed_elapsed, duration, finished=True))
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
