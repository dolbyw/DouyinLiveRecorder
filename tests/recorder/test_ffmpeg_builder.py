import pytest

from src.recorder.ffmpeg_builder import FFmpegBuilder
from src.recorder.models import OutputPlan, RecordRequest, SaveFormat


@pytest.mark.parametrize(
    ("fmt", "split", "required"),
    [
        (SaveFormat.TS, False, ["-c:v", "copy", "-f", "mpegts"]),
        (SaveFormat.TS, True, ["-f", "segment", "-segment_format", "mpegts"]),
        (SaveFormat.FLV, False, ["-c:a", "copy", "-f", "flv"]),
        (SaveFormat.FLV, True, ["-f", "segment", "-segment_format", "flv"]),
        (SaveFormat.MKV, False, ["-f", "matroska"]),
        (SaveFormat.MKV, True, ["-segment_format", "matroska"]),
        (SaveFormat.MP4, False, ["-movflags", "+faststart"]),
        (SaveFormat.MP4, True, ["-segment_format", "mp4"]),
        (SaveFormat.MP3, False, ["-map", "0:a", "libmp3lame", "320k"]),
        (SaveFormat.MP3, True, ["-f", "segment", "libmp3lame"]),
        (SaveFormat.M4A, False, ["-map", "0:a", "aac_adtstoasc", "ipod"]),
        (SaveFormat.M4A, True, ["-f", "segment", "-segment_format", "ipod"]),
    ],
)
def test_format_matrix(fmt, split, required, tmp_path):
    request = RecordRequest(
        anchor_name="a",
        platform="p",
        room_url="room",
        source_url="https://stream",
        save_format=fmt,
        split=split,
    )
    suffix = f"_%03d.{fmt.value.lower()}" if split else f".{fmt.value.lower()}"
    plan = OutputPlan(tmp_path / f"a{suffix}", tmp_path / f"a_*.{fmt.value.lower()}", fmt, split)
    command = FFmpegBuilder().build(request, plan)
    for token in required:
        assert token in command
    assert command[-1] == str(plan.output_path)


def test_proxy_headers_and_overseas_values_are_input_options(tmp_path):
    request = RecordRequest(
        anchor_name="a",
        platform="p",
        room_url="room",
        source_url="https://stream",
        proxy="http://proxy",
        headers="Referer: x",
        overseas=True,
    )
    plan = OutputPlan(tmp_path / "a.ts", tmp_path / "a.ts", SaveFormat.TS, False)
    command = FFmpegBuilder().build(request, plan)
    assert command[1:3] == ["-http_proxy", "http://proxy"]
    assert command.index("-headers") < command.index("-i")
    assert command[command.index("-rw_timeout") + 1] == "50000000"


def test_http_reconnect_policy_is_explicit_finite_and_before_input(tmp_path):
    request = RecordRequest(
        anchor_name="a",
        platform="p",
        room_url="room",
        source_url="https://stream",
    )
    plan = OutputPlan(tmp_path / "a.ts", tmp_path / "a.ts", SaveFormat.TS, False)

    command = FFmpegBuilder().build(request, plan)
    input_index = command.index("-i")
    expected = {
        "-reconnect": "1",
        "-reconnect_at_eof": "1",
        "-reconnect_streamed": "1",
        "-reconnect_on_network_error": "1",
        "-reconnect_delay_max": "5",
        "-reconnect_max_retries": "5",
    }

    for option, value in expected.items():
        option_index = command.index(option)
        assert option_index < input_index
        assert command[option_index + 1] == value


def test_builder_rejects_plan_format_that_differs_from_effective_format(tmp_path):
    request = RecordRequest(
        anchor_name="a",
        platform="p",
        room_url="room",
        source_url="stream",
        save_format=SaveFormat.TS,
        audio_only=True,
    )
    plan = OutputPlan(tmp_path / "a.ts", tmp_path / "a.ts", SaveFormat.TS, False)
    with pytest.raises(ValueError, match="effective format"):
        FFmpegBuilder().build(request, plan)
