from pathlib import Path


def test_main_uses_recording_pipeline_and_no_longer_builds_format_commands_inline():
    source = Path("main.py").read_text(encoding="utf-8")
    assert "from src.recorder import" in source
    assert "RecordingPipeline(" in source
    assert "RecordRequest(" in source
    recording_tail = source[source.index("real_url = select_source_url") :]
    assert 'elif record_save_type == "FLV"' not in recording_tail
    assert 'elif record_save_type == "MKV"' not in recording_tail
    assert 'elif record_save_type == "MP4"' not in recording_tail


def test_main_delegates_process_lifecycle():
    source = Path("main.py").read_text(encoding="utf-8")
    assert "def check_subprocess(" not in source


def test_main_uses_actual_pipeline_output_format_for_record_script():
    source = Path("main.py").read_text(encoding="utf-8")
    assert 'pipeline_output["save_format"] = plan.save_format.value' in source
    assert 'actual_save_format = pipeline_output.get("save_format", save_format.value)' in source
