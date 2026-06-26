from pathlib import Path

import pytest

from src.recorder.models import EndReason, OutputPlan, RecordRequest, SaveFormat


def test_save_format_normalizes_case_and_rejects_unknown_values():
    assert SaveFormat.parse("m4a") is SaveFormat.M4A
    with pytest.raises(ValueError, match="unsupported save format"):
        SaveFormat.parse("avi")


def test_segment_plan_exposes_template_and_real_file_glob():
    plan = OutputPlan(Path("out/a_%03d.flv"), Path("out/a_*.flv"), SaveFormat.FLV, True)
    assert "%03d" in str(plan.output_path)
    assert "%03d" not in str(plan.file_glob)


def test_request_rejects_non_positive_segment_time():
    with pytest.raises(ValueError, match="segment_seconds"):
        RecordRequest(
            anchor_name="a",
            platform="p",
            room_url="room",
            source_url="stream",
            split=True,
            segment_seconds=0,
        )


def test_end_reasons_identify_successful_recordings():
    assert EndReason.COMPLETED.is_success
    assert EndReason.COMMENT_STOPPED.is_success
    assert EndReason.EXIT_STOPPED.is_success
    assert not EndReason.FAILED.is_success


def test_request_carries_optional_emoji_cleaning_policy():
    request = RecordRequest(
        anchor_name="a",
        platform="p",
        room_url="room",
        source_url="stream",
        clean_emojis=True,
    )
    assert request.clean_emojis is True


def test_direct_download_always_uses_flv_output():
    request = RecordRequest(
        anchor_name="a",
        platform="p",
        room_url="room",
        source_url="stream",
        save_format=SaveFormat.MP4,
        direct_flv=True,
    )
    assert request.effective_format is SaveFormat.FLV
