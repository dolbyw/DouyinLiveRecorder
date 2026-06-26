from datetime import datetime

from src.recorder.models import RecordRequest, SaveFormat
from src.recorder.pathing import PathBuilder, sanitize_name

NOW = datetime(2026, 6, 20, 12, 34, 56)


def test_sanitize_name_preserves_existing_semantics():
    assert sanitize_name(" a:b？<>| ") == "a_b"
    assert sanitize_name("////") == "空白昵称"


def test_path_builder_applies_platform_author_date_and_title(tmp_path):
    request = RecordRequest(
        anchor_name="主播",
        platform="抖音直播",
        room_url="room",
        source_url="stream",
        title="标题",
        output_root=tmp_path,
        save_format=SaveFormat.TS,
        folder_by_title=True,
        filename_by_title=True,
    )
    plan = PathBuilder(now=lambda: NOW).build(request)
    assert plan.output_path == (
        tmp_path / "抖音直播" / "主播" / "2026-06-20" / "标题_主播" / "主播_标题_2026-06-20_12-34-56.ts"
    )


def test_segment_path_has_numeric_template_and_wildcard_glob(tmp_path):
    request = RecordRequest(
        anchor_name="a",
        platform="p",
        room_url="room",
        source_url="stream",
        output_root=tmp_path,
        save_format=SaveFormat.FLV,
        split=True,
    )
    plan = PathBuilder(now=lambda: NOW).build(request)
    assert plan.output_path.name.endswith("_%03d.flv")
    assert plan.file_glob.name.endswith("_*.flv")


def test_audio_only_video_setting_plans_mp3_output(tmp_path):
    request = RecordRequest(
        anchor_name="a",
        platform="p",
        room_url="room",
        source_url="stream",
        output_root=tmp_path,
        save_format=SaveFormat.TS,
        audio_only=True,
    )
    plan = PathBuilder(now=lambda: NOW).build(request)
    assert plan.save_format is SaveFormat.MP3
    assert plan.output_path.suffix == ".mp3"
