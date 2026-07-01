from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from .models import OutputPlan, PostprocessResult, ProcessResult, RecordRequest, SaveFormat


class PostProcessor:
    def __init__(
        self,
        converter: Callable[[Path, bool, int, int], None] | None = None,
        script_runner: Callable[[str], None] | None = None,
        skip_files: Callable[[], set[Path]] | None = None,
    ) -> None:
        self._converter = converter
        self._script_runner = script_runner
        self._skip_files = skip_files or set

    @staticmethod
    def files_for(plan: OutputPlan) -> tuple[Path, ...]:
        if not plan.segmented:
            return (plan.output_path,) if plan.output_path.exists() else ()
        return tuple(sorted(plan.file_glob.parent.glob(plan.file_glob.name)))

    def run(
        self,
        request: RecordRequest,
        plan: OutputPlan,
        process_result: ProcessResult,
    ) -> PostprocessResult:
        if not process_result.reason.is_success:
            return PostprocessResult()

        skip_files = {Path(path) for path in self._skip_files()}
        files = tuple(path for path in self.files_for(plan) if path not in skip_files)
        errors: list[BaseException] = []
        if request.convert_to_mp4 and plan.save_format is SaveFormat.TS and self._converter:
            for index, path in enumerate(files, start=1):
                try:
                    self._converter(path, request.convert_to_h264, index, len(files))
                except Exception as error:
                    errors.append(error)

        if request.custom_script and self._script_runner and not errors:
            try:
                self._script_runner(request.custom_script)
            except Exception as error:
                errors.append(error)
        return PostprocessResult(files, tuple(errors))
