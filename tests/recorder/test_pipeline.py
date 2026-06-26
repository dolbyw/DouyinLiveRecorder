import pytest

from src.recorder.models import (
    EndReason,
    OutputPlan,
    PostprocessResult,
    ProcessResult,
    RecordRequest,
    SaveFormat,
)
from src.recorder.pipeline import RecordingPipeline


class FakePathBuilder:
    def __init__(self, plan=None, error=None):
        self.plan = plan
        self.error = error

    def build(self, request):
        if self.error:
            raise self.error
        return self.plan


class FakeCommandBuilder:
    def __init__(self):
        self.calls = []

    def build(self, request, plan):
        self.calls.append((request, plan))
        return ["ffmpeg", str(plan.output_path)]


class FakeProcess:
    def __init__(self, result=None):
        self.result = result or ProcessResult(EndReason.COMPLETED, 0)
        self.calls = []

    def run(self, command, **kwargs):
        self.calls.append((command, kwargs))
        on_started = kwargs.get("on_started")
        if on_started and self.result.reason is not EndReason.FAILED_TO_START:
            on_started(object())
        return self.result


class FakePostProcessor:
    def __init__(self):
        self.calls = []

    def run(self, request, plan, process):
        self.calls.append((request, plan, process))
        return PostprocessResult()


def make_request(tmp_path, **changes):
    values = dict(anchor_name="a", platform="p", room_url="room", source_url="stream", output_root=tmp_path)
    values.update(changes)
    return RecordRequest(**values)


def make_plan(tmp_path, fmt=SaveFormat.TS):
    path = tmp_path / f"a.{fmt.value.lower()}"
    return OutputPlan(path, path, fmt, False)


def test_ffmpeg_strategy_builds_runs_and_postprocesses_once(tmp_path):
    request = make_request(tmp_path)
    plan = make_plan(tmp_path)
    command_builder, process, postprocessor = FakeCommandBuilder(), FakeProcess(), FakePostProcessor()
    pipeline = RecordingPipeline(FakePathBuilder(plan), command_builder, process, postprocessor)
    result = pipeline.run(request, should_comment_stop=lambda: False, should_exit=lambda: False)
    assert result.process.reason is EndReason.COMPLETED
    assert len(command_builder.calls) == len(process.calls) == len(postprocessor.calls) == 1


def test_direct_flv_skips_ffmpeg_and_postprocessing(tmp_path):
    request = make_request(
        tmp_path, direct_flv=True, save_format=SaveFormat.MP4, split=True, convert_to_mp4=True, custom_script="done"
    )
    plan = make_plan(tmp_path, SaveFormat.FLV)
    command_builder, process, postprocessor = FakeCommandBuilder(), FakeProcess(), FakePostProcessor()
    downloads = []
    pipeline = RecordingPipeline(
        FakePathBuilder(plan),
        command_builder,
        process,
        postprocessor,
        direct_downloader=lambda source, output: downloads.append((source, output)) or True,
    )
    result = pipeline.run(request, should_comment_stop=lambda: False, should_exit=lambda: False)
    assert result.process.reason is EndReason.COMPLETED
    assert downloads == [("stream", plan.output_path)]
    assert command_builder.calls == process.calls == postprocessor.calls == []


def test_audio_only_request_executes_exactly_one_process(tmp_path):
    request = make_request(tmp_path, audio_only=True)
    plan = make_plan(tmp_path, SaveFormat.MP3)
    process = FakeProcess()
    pipeline = RecordingPipeline(FakePathBuilder(plan), FakeCommandBuilder(), process, FakePostProcessor())
    pipeline.run(request, should_comment_stop=lambda: False, should_exit=lambda: False)
    assert len(process.calls) == 1


def test_finish_callback_runs_when_path_builder_raises(tmp_path):
    finished = []
    pipeline = RecordingPipeline(
        FakePathBuilder(error=OSError("path")), FakeCommandBuilder(), FakeProcess(), FakePostProcessor()
    )
    with pytest.raises(OSError, match="path"):
        pipeline.run(
            make_request(tmp_path),
            should_comment_stop=lambda: False,
            should_exit=lambda: False,
            on_finish=lambda: finished.append(True),
        )
    assert finished == [True]


def test_failed_process_reaches_postprocessor_for_gating(tmp_path):
    plan = make_plan(tmp_path)
    process = FakeProcess(ProcessResult(EndReason.FAILED, 3))
    postprocessor = FakePostProcessor()
    pipeline = RecordingPipeline(FakePathBuilder(plan), FakeCommandBuilder(), process, postprocessor)
    result = pipeline.run(make_request(tmp_path), should_comment_stop=lambda: False, should_exit=lambda: False)
    assert result.process.return_code == 3
    assert len(postprocessor.calls) == 1


def test_on_start_runs_only_after_process_start(tmp_path):
    plan = make_plan(tmp_path)
    started = []
    process = FakeProcess(ProcessResult(EndReason.FAILED_TO_START, error=OSError("missing ffmpeg")))
    pipeline = RecordingPipeline(FakePathBuilder(plan), FakeCommandBuilder(), process, FakePostProcessor())
    result = pipeline.run(
        make_request(tmp_path),
        should_comment_stop=lambda: False,
        should_exit=lambda: False,
        on_start=lambda _plan: started.append(True),
    )
    assert result.process.reason is EndReason.FAILED_TO_START
    assert started == []
