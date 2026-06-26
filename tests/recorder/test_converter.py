from pathlib import Path

import pytest

from src.recorder.converter import ConversionError, ConversionProgress, FFmpegConverter, parse_progress_time


class FakeProcess:
    def __init__(self, returncode, lines):
        self.returncode = returncode
        self.stdout = iter(lines)

    def wait(self):
        return self.returncode


def test_progress_time_parses_ffmpeg_microseconds():
    assert parse_progress_time("out_time_us", "2500000") == 2.5
    assert parse_progress_time("out_time_ms", "1250000") == 1.25
    assert parse_progress_time("frame", "42") is None


def test_progress_percentage_is_clamped():
    progress = ConversionProgress(Path("a.ts"), elapsed=12.0, duration=10.0)
    assert progress.percent == 100.0
    assert ConversionProgress(Path("a.ts"), elapsed=1.0, duration=None).percent is None


def test_copy_command_uses_progress_protocol_and_temporary_target(tmp_path):
    source = tmp_path / "a.ts"
    target = tmp_path / "a.converting.mp4"

    command = FFmpegConverter().build_command(source, target, transcode_h264=False)

    assert command[:6] == ["ffmpeg", "-y", "-v", "error", "-i", str(source)]
    assert command[6:10] == ["-c:v", "copy", "-c:a", "copy"]
    assert command[-4:] == ["-progress", "pipe:1", "-nostats", str(target)]


def test_h264_command_preserves_existing_encoding_settings(tmp_path):
    source = tmp_path / "a.ts"
    target = tmp_path / "a.converting.mp4"

    command = FFmpegConverter().build_command(source, target, transcode_h264=True)

    assert command[6:18] == [
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
        "-progress",
        "pipe:1",
    ]


def test_successful_conversion_atomically_publishes_mp4_and_then_deletes_ts(tmp_path):
    source = tmp_path / "a.ts"
    source.write_bytes(b"transport-stream")
    final = tmp_path / "a.mp4"
    final.write_bytes(b"old")
    progress = []

    def start(command, **_kwargs):
        Path(command[-1]).write_bytes(b"complete-mp4")
        return FakeProcess(0, ["out_time_us=5000000\n", "progress=continue\n", "progress=end\n"])

    converter = FFmpegConverter(process_factory=start, probe_duration=lambda _source: 10.0)
    result = converter.convert(source, delete_source=True, on_progress=progress.append)

    assert result == final
    assert final.read_bytes() == b"complete-mp4"
    assert not source.exists()
    assert not (tmp_path / "a.converting.mp4").exists()
    assert progress[-1].finished is True
    assert progress[-1].percent == 100.0


def test_failed_conversion_preserves_source_removes_temporary_and_reports_diagnostics(tmp_path):
    source = tmp_path / "a.ts"
    source.write_bytes(b"transport-stream")

    def start(command, **_kwargs):
        Path(command[-1]).write_bytes(b"partial")
        return FakeProcess(1, ["fatal conversion error\n"])

    converter = FFmpegConverter(process_factory=start, probe_duration=lambda _source: 10.0)

    with pytest.raises(ConversionError, match="fatal conversion error"):
        converter.convert(source, delete_source=True)

    assert source.exists()
    assert not (tmp_path / "a.mp4").exists()
    assert not (tmp_path / "a.converting.mp4").exists()


def test_probe_failure_uses_indeterminate_progress_without_blocking_conversion(tmp_path):
    source = tmp_path / "a.ts"
    source.write_bytes(b"transport-stream")
    progress = []

    def fail_probe(_source):
        raise OSError("ffprobe unavailable")

    def start(command, **_kwargs):
        Path(command[-1]).write_bytes(b"complete-mp4")
        return FakeProcess(0, ["out_time_us=1000000\n", "progress=end\n"])

    converter = FFmpegConverter(process_factory=start, probe_duration=fail_probe)
    converter.convert(source, delete_source=False, on_progress=progress.append)

    assert source.exists()
    assert all(item.duration is None for item in progress)
    assert progress[-1].finished is True


def test_progress_callback_failure_does_not_abort_conversion(tmp_path):
    source = tmp_path / "a.ts"
    source.write_bytes(b"transport-stream")

    def start(command, **_kwargs):
        Path(command[-1]).write_bytes(b"complete-mp4")
        return FakeProcess(0, ["progress=end\n"])

    converter = FFmpegConverter(process_factory=start, probe_duration=lambda _source: 1.0)
    result = converter.convert(
        source,
        delete_source=False,
        on_progress=lambda _progress: (_ for _ in ()).throw(RuntimeError("display failed")),
    )

    assert result.read_bytes() == b"complete-mp4"
