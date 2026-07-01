from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from typing import Any

from .ffmpeg_builder import FFmpegBuilder
from .models import EndReason, PipelineResult, PostprocessResult, ProcessResult, RecordRequest
from .pathing import PathBuilder
from .postprocess import PostProcessor
from .process import RecorderProcess


class RecordingPipeline:
    def __init__(
        self,
        path_builder: Any = None,
        command_builder: Any = None,
        process_runner: Any = None,
        postprocessor: Any = None,
        *,
        direct_downloader: Callable[[str, Path], bool] | None = None,
    ) -> None:
        self._path_builder = path_builder or PathBuilder()
        self._command_builder = command_builder or FFmpegBuilder()
        self._process_runner = process_runner or RecorderProcess()
        self._postprocessor = postprocessor or PostProcessor()
        self._direct_downloader = direct_downloader

    def run(
        self,
        request: RecordRequest,
        *,
        should_comment_stop: Callable[[], bool],
        should_exit: Callable[[], bool],
        on_start: Callable[[Any], None] | None = None,
        on_finish: Callable[[], None] | None = None,
        on_tick: Callable[[], None] | None = None,
        before_postprocess: Callable[[], None] | None = None,
        startupinfo: Any = None,
    ) -> PipelineResult:
        try:
            planning_request = replace(request, split=False) if request.direct_flv else request
            plan = self._path_builder.build(planning_request)
            if request.direct_flv:
                if on_start:
                    on_start(plan)
                process = self._run_direct(request, plan.output_path)
                return PipelineResult(plan, process, PostprocessResult())

            command = self._command_builder.build(request, plan)
            process = self._process_runner.run(
                command,
                should_comment_stop=should_comment_stop,
                should_exit=should_exit,
                on_started=(lambda _process: on_start(plan)) if on_start else None,
                on_tick=on_tick,
                startupinfo=startupinfo,
            )
            if before_postprocess is not None:
                before_postprocess()
            postprocess = self._postprocessor.run(request, plan, process)
            return PipelineResult(plan, process, postprocess)
        finally:
            if on_finish:
                on_finish()

    def _run_direct(self, request: RecordRequest, output_path: Path) -> ProcessResult:
        if self._direct_downloader is None:
            error = RuntimeError("direct FLV downloader is not configured")
            return ProcessResult(EndReason.FAILED_TO_START, error=error)
        try:
            success = self._direct_downloader(request.source_url, output_path)
        except Exception as error:
            return ProcessResult(EndReason.FAILED, error=error)
        return ProcessResult(EndReason.COMPLETED if success else EndReason.FAILED, 0 if success else 1)
