from src.recorder.models import EndReason, OutputPlan, ProcessResult, RecordRequest, SaveFormat
from src.recorder.postprocess import PostProcessor


def make_request(tmp_path, **changes):
    values = {
        "anchor_name": "a",
        "platform": "p",
        "room_url": "room",
        "source_url": "stream",
        "output_root": tmp_path,
    }
    values.update(changes)
    return RecordRequest(**values)


def test_segmented_plan_expands_real_files_in_order(tmp_path):
    files = [tmp_path / "a_001.ts", tmp_path / "a_000.ts"]
    for path in files:
        path.write_bytes(b"x")
    plan = OutputPlan(tmp_path / "a_%03d.ts", tmp_path / "a_*.ts", SaveFormat.TS, True)
    assert PostProcessor().files_for(plan) == tuple(sorted(files))


def test_failed_process_skips_converter_and_script(tmp_path):
    calls = []
    plan = OutputPlan(tmp_path / "a.ts", tmp_path / "a.ts", SaveFormat.TS, False)
    result = PostProcessor(converter=lambda *args: calls.append(args), script_runner=calls.append).run(
        make_request(tmp_path, convert_to_mp4=True, custom_script="done"),
        plan,
        ProcessResult(EndReason.FAILED, 1),
    )
    assert calls == []
    assert result.processed_files == ()


def test_completed_and_comment_stopped_use_same_conversion_rule(tmp_path):
    source = tmp_path / "a.ts"
    source.write_bytes(b"x")
    plan = OutputPlan(source, source, SaveFormat.TS, False)
    calls = []
    processor = PostProcessor(converter=lambda path, h264, _index, _total: calls.append((path, h264)))
    request = make_request(tmp_path, convert_to_mp4=True, convert_to_h264=True)
    processor.run(request, plan, ProcessResult(EndReason.COMPLETED, 0))
    processor.run(request, plan, ProcessResult(EndReason.COMMENT_STOPPED, 0))
    assert calls == [(source, True), (source, True)]


def test_ctrl_c_exit_with_ffmpeg_255_still_converts_ts(tmp_path):
    source = tmp_path / "shutdown.ts"
    source.write_bytes(b"x")
    plan = OutputPlan(source, source, SaveFormat.TS, False)
    calls = []

    PostProcessor(converter=lambda path, _h264, _index, _total: calls.append(path)).run(
        make_request(tmp_path, convert_to_mp4=True),
        plan,
        ProcessResult(EndReason.EXIT_STOPPED, 255),
    )

    assert calls == [source]


def test_conversion_error_is_reported_and_source_is_preserved(tmp_path):
    source = tmp_path / "a.ts"
    source.write_bytes(b"x")
    error = RuntimeError("convert failed")

    def fail(*_args):
        raise error

    plan = OutputPlan(source, source, SaveFormat.TS, False)
    result = PostProcessor(converter=fail).run(
        make_request(tmp_path, convert_to_mp4=True), plan, ProcessResult(EndReason.COMPLETED, 0)
    )
    assert result.errors == (error,)
    assert source.exists()


def test_custom_script_runs_once_after_success(tmp_path):
    source = tmp_path / "a.flv"
    source.write_bytes(b"x")
    calls = []
    plan = OutputPlan(source, source, SaveFormat.FLV, False)
    result = PostProcessor(script_runner=calls.append).run(
        make_request(tmp_path, save_format=SaveFormat.FLV, custom_script="done"),
        plan,
        ProcessResult(EndReason.EXIT_STOPPED, 0),
    )
    assert calls == ["done"]
    assert result.processed_files == (source,)


def test_segment_conversion_receives_one_based_file_position(tmp_path):
    first, second = tmp_path / "a_000.ts", tmp_path / "a_001.ts"
    first.write_bytes(b"x")
    second.write_bytes(b"x")
    calls = []
    plan = OutputPlan(tmp_path / "a_%03d.ts", tmp_path / "a_*.ts", SaveFormat.TS, True)

    PostProcessor(converter=lambda path, _h264, index, total: calls.append((path, index, total))).run(
        make_request(tmp_path, convert_to_mp4=True),
        plan,
        ProcessResult(EndReason.COMPLETED, 0),
    )

    assert calls == [(first, 1, 2), (second, 2, 2)]


def test_postprocessor_skips_files_already_handled_during_recording(tmp_path):
    first, second = tmp_path / "a_000.ts", tmp_path / "a_001.ts"
    first.write_bytes(b"x")
    second.write_bytes(b"x")
    calls = []
    plan = OutputPlan(tmp_path / "a_%03d.ts", tmp_path / "a_*.ts", SaveFormat.TS, True)

    PostProcessor(
        converter=lambda path, _h264, index, total: calls.append((path, index, total)),
        skip_files=lambda: {first},
    ).run(
        make_request(tmp_path, convert_to_mp4=True),
        plan,
        ProcessResult(EndReason.COMPLETED, 0),
    )

    assert calls == [(second, 1, 1)]
