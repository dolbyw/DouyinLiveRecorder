# PR4 Recorder Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extract the complete recording pipeline from `main.py`, preserve existing user-facing behavior, and fix the four recording defects defined by PR4.

**Architecture:** A typed `src/recorder/` package owns output planning, FFmpeg command construction, process lifecycle, post-processing, and strategy orchestration. `main.py` remains responsible for stream discovery and application state, and connects to the package through a narrow request/result interface and callbacks.

**Tech Stack:** Python 3.10+, dataclasses, pathlib, subprocess, pytest, pytest monkeypatch, Ruff

**Repository note:** The current workspace has no `.git` directory. Execute each commit step only if Git metadata is restored; otherwise record the test checkpoint and continue without inventing repository state.

---

## File map

- Create `src/recorder/models.py`: immutable request, plan, process, and pipeline contracts.
- Create `src/recorder/pathing.py`: sanitization, directory layout, filenames, segment templates, and glob discovery.
- Create `src/recorder/ffmpeg_builder.py`: common input options and six output-format strategies.
- Create `src/recorder/process.py`: subprocess lifecycle and cross-platform graceful stop.
- Create `src/recorder/postprocess.py`: file expansion, MP4 conversion, custom script execution, and failure reporting.
- Create `src/recorder/pipeline.py`: FFmpeg/direct-download orchestration and callback cleanup boundary.
- Create `src/recorder/__init__.py`: stable public API.
- Create `tests/recorder/`: focused tests matching each recorder module.
- Modify `main.py`: construct `RecordRequest`, invoke `RecordingPipeline`, and remove replaced inline format/process branches.
- Modify `docs/项目优化实施路线图.md`: record PR4 scope, validation, and remaining manual-live boundary.

### Task 1: Define recorder contracts

**Files:**
- Create: `src/recorder/models.py`
- Create: `src/recorder/__init__.py`
- Create: `tests/recorder/test_models.py`

- [ ] **Step 1: Write failing contract tests**

```python
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
        RecordRequest(anchor_name="a", platform="p", room_url="room", source_url="stream", split=True,
                      segment_seconds=0)


def test_end_reasons_identify_successful_recordings():
    assert EndReason.COMPLETED.is_success
    assert EndReason.COMMENT_STOPPED.is_success
    assert EndReason.EXIT_STOPPED.is_success
    assert not EndReason.FAILED.is_success
```

- [ ] **Step 2: Run RED**

Run: `.\.venv\Scripts\python.exe -m pytest tests/recorder/test_models.py -q`

Expected: collection fails because `src.recorder` does not exist.

- [ ] **Step 3: Implement the contracts**

Implement `SaveFormat(str, Enum)` with `TS`, `FLV`, `MKV`, `MP4`, `MP3`, `M4A` and a case-insensitive `parse()`. Implement `EndReason` with `COMPLETED`, `COMMENT_STOPPED`, `EXIT_STOPPED`, `FAILED_TO_START`, and `FAILED`, plus `is_success`.

Implement frozen, slotted dataclasses with these stable fields:

```python
@dataclass(frozen=True, slots=True)
class RecordRequest:
    anchor_name: str
    platform: str
    room_url: str
    source_url: str
    title: str | None = None
    output_root: Path = Path("downloads")
    save_format: SaveFormat = SaveFormat.TS
    folder_by_author: bool = True
    folder_by_date: bool = True
    folder_by_title: bool = False
    filename_by_title: bool = False
    split: bool = False
    segment_seconds: int = 1800
    proxy: str | None = None
    headers: str | None = None
    overseas: bool = False
    audio_only: bool = False
    direct_flv: bool = False
    convert_to_mp4: bool = False
    convert_to_h264: bool = False
    custom_script: str | None = None

@dataclass(frozen=True, slots=True)
class OutputPlan:
    output_path: Path
    file_glob: Path
    save_format: SaveFormat
    segmented: bool

@dataclass(frozen=True, slots=True)
class ProcessResult:
    reason: EndReason
    return_code: int | None = None
    error: BaseException | None = None

@dataclass(frozen=True, slots=True)
class PostprocessResult:
    processed_files: tuple[Path, ...] = ()
    errors: tuple[BaseException, ...] = ()

@dataclass(frozen=True, slots=True)
class PipelineResult:
    output: OutputPlan
    process: ProcessResult
    postprocess: PostprocessResult = PostprocessResult()
```

Validate non-empty identity/source fields and positive segment seconds in `RecordRequest.__post_init__`. Export these types from `src/recorder/__init__.py`.

- [ ] **Step 4: Run GREEN and lint**

Run: `.\.venv\Scripts\python.exe -m pytest tests/recorder/test_models.py -q`

Expected: all tests pass.

Run: `.\.venv\Scripts\python.exe -m ruff check src/recorder/models.py tests/recorder/test_models.py`

Expected: `All checks passed!`

- [ ] **Step 5: Checkpoint commit when Git is available**

```powershell
git add src/recorder/models.py src/recorder/__init__.py tests/recorder/test_models.py
git commit -m "feat: define recorder pipeline contracts"
```

### Task 2: Build output paths and segment discovery patterns

**Files:**
- Create: `src/recorder/pathing.py`
- Create: `tests/recorder/test_pathing.py`
- Modify: `src/recorder/__init__.py`

- [ ] **Step 1: Write failing path tests**

```python
from datetime import datetime
from pathlib import Path

from src.recorder.models import RecordRequest, SaveFormat
from src.recorder.pathing import PathBuilder, sanitize_name


NOW = datetime(2026, 6, 20, 12, 34, 56)


def test_sanitize_name_preserves_existing_semantics():
    assert sanitize_name(' a:b？<>| ') == "a_b"
    assert sanitize_name('////') == "空白昵称"


def test_path_builder_applies_platform_author_date_and_title(tmp_path):
    request = RecordRequest(anchor_name="主播", platform="抖音直播", room_url="room", source_url="stream",
                            title="标题", output_root=tmp_path, save_format=SaveFormat.TS,
                            folder_by_title=True, filename_by_title=True)
    plan = PathBuilder(now=lambda: NOW).build(request)
    assert plan.output_path == tmp_path / "抖音直播" / "主播" / "2026-06-20" / "标题_主播" / "主播_标题_2026-06-20_12-34-56.ts"


def test_segment_path_has_numeric_template_and_wildcard_glob(tmp_path):
    request = RecordRequest(anchor_name="a", platform="p", room_url="room", source_url="stream",
                            output_root=tmp_path, save_format=SaveFormat.FLV, split=True)
    plan = PathBuilder(now=lambda: NOW).build(request)
    assert plan.output_path.name.endswith("_%03d.flv")
    assert plan.file_glob.name.endswith("_*.flv")
```

- [ ] **Step 2: Run RED**

Run: `.\.venv\Scripts\python.exe -m pytest tests/recorder/test_pathing.py -q`

Expected: collection fails because `pathing.py` does not exist.

- [ ] **Step 3: Implement `sanitize_name()` and `PathBuilder`**

Move the character replacement and empty-name behavior from `main.clean_name` into `sanitize_name`. `PathBuilder.build(request)` must compute the directory and filename once, call `mkdir(parents=True, exist_ok=True)`, and return an `OutputPlan`. Use the fixed extension mapping from the spec and `_%03d` only when `request.split` is true. Derive `file_glob` by replacing `%03d` with `*`; do not derive it later in post-processing.

- [ ] **Step 4: Run GREEN and all recorder tests**

Run: `.\.venv\Scripts\python.exe -m pytest tests/recorder/test_pathing.py tests/recorder/test_models.py -q`

Expected: all tests pass.

- [ ] **Step 5: Checkpoint commit when Git is available**

```powershell
git add src/recorder/pathing.py src/recorder/__init__.py tests/recorder/test_pathing.py
git commit -m "feat: add recorder output path planning"
```

### Task 3: Build all FFmpeg command variants

**Files:**
- Create: `src/recorder/ffmpeg_builder.py`
- Create: `tests/recorder/test_ffmpeg_builder.py`
- Modify: `src/recorder/__init__.py`

- [ ] **Step 1: Write parameterized failing tests for the format matrix**

```python
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
    request = RecordRequest(anchor_name="a", platform="p", room_url="room", source_url="https://stream",
                            save_format=fmt, split=split)
    suffix = f"_%03d.{fmt.value.lower()}" if split else f".{fmt.value.lower()}"
    plan = OutputPlan(tmp_path / f"a{suffix}", tmp_path / f"a_*.{fmt.value.lower()}", fmt, split)
    command = FFmpegBuilder().build(request, plan)
    for token in required:
        assert token in command
    assert command[-1] == str(plan.output_path)


def test_proxy_headers_and_overseas_values_are_input_options(tmp_path):
    request = RecordRequest(anchor_name="a", platform="p", room_url="room", source_url="https://stream",
                            proxy="http://proxy", headers="Referer: x", overseas=True)
    plan = OutputPlan(tmp_path / "a.ts", tmp_path / "a.ts", SaveFormat.TS, False)
    command = FFmpegBuilder().build(request, plan)
    assert command[1:3] == ["-http_proxy", "http://proxy"]
    assert command.index("-headers") < command.index("-i")
    assert command[command.index("-rw_timeout") + 1] == "50000000"
```

- [ ] **Step 2: Run RED**

Run: `.\.venv\Scripts\python.exe -m pytest tests/recorder/test_ffmpeg_builder.py -q`

Expected: collection fails because `FFmpegBuilder` does not exist.

- [ ] **Step 3: Implement `FFmpegBuilder`**

Create one `build(request, plan) -> list[str]` entry point. Build common options in their existing order, placing proxy immediately after `ffmpeg`, headers before `-i`, and the output path last. Use a private method per format so that each output strategy has one owner. M4A segmented output must use `-segment_format ipod`, never `mpegts`. Add `RecordRequest.effective_format`: it returns MP3 when `audio_only=True` and the configured format is a video format, otherwise it returns `save_format`. `PathBuilder` and `FFmpegBuilder` must both consume this property so the planned extension and muxer cannot diverge.

- [ ] **Step 4: Run GREEN and format checks**

Run: `.\.venv\Scripts\python.exe -m pytest tests/recorder/test_ffmpeg_builder.py -q`

Expected: 13 or more tests pass.

Run: `.\.venv\Scripts\python.exe -m ruff check src/recorder/ffmpeg_builder.py tests/recorder/test_ffmpeg_builder.py`

Expected: `All checks passed!`

- [ ] **Step 5: Checkpoint commit when Git is available**

```powershell
git add src/recorder/ffmpeg_builder.py src/recorder/__init__.py tests/recorder/test_ffmpeg_builder.py
git commit -m "feat: centralize ffmpeg recording commands"
```

### Task 4: Implement subprocess lifecycle and graceful stop

**Files:**
- Create: `src/recorder/process.py`
- Create: `tests/recorder/test_process.py`
- Modify: `src/recorder/__init__.py`

- [ ] **Step 1: Write failing fake-process tests**

Create a `FakeProcess` in the test with `poll()`, `wait(timeout)`, `send_signal()`, `stdin.write()`, and `stdin.flush()`. Add tests asserting:

```python
def test_natural_zero_exit_is_completed(): ...
def test_nonzero_exit_is_failed_and_keeps_return_code(): ...
def test_factory_exception_is_failed_to_start(): ...
def test_windows_comment_stop_writes_q_once_and_waits(): ...
def test_posix_exit_stop_sends_sigint_once_and_waits(): ...
```

Use injected `should_comment_stop`, `should_exit`, `sleep`, and `platform_name` so no test sleeps or starts FFmpeg.

- [ ] **Step 2: Run RED**

Run: `.\.venv\Scripts\python.exe -m pytest tests/recorder/test_process.py -q`

Expected: collection fails because `RecorderProcess` does not exist.

- [ ] **Step 3: Implement `RecorderProcess`**

Use this public signature:

```python
class RecorderProcess:
    def __init__(self, process_factory=subprocess.Popen, sleep=time.sleep, platform_name=platform.system()): ...

    def run(self, command: list[str], *, should_comment_stop: Callable[[], bool],
            should_exit: Callable[[], bool], startupinfo=None) -> ProcessResult: ...
```

Start with `stdin=subprocess.PIPE` and `stderr=subprocess.STDOUT`. Poll once per injected sleep. For Windows, write and flush `b"q"`; elsewhere send `signal.SIGINT`. Call `wait(timeout=15)` after the single stop signal. Convert factory errors to `FAILED_TO_START`; convert stop/wait errors to `FAILED`; preserve return codes.

- [ ] **Step 4: Run GREEN**

Run: `.\.venv\Scripts\python.exe -m pytest tests/recorder/test_process.py -q`

Expected: all lifecycle tests pass with no real subprocess.

- [ ] **Step 5: Checkpoint commit when Git is available**

```powershell
git add src/recorder/process.py src/recorder/__init__.py tests/recorder/test_process.py
git commit -m "feat: isolate recorder process lifecycle"
```

### Task 5: Implement deterministic post-processing

**Files:**
- Create: `src/recorder/postprocess.py`
- Create: `tests/recorder/test_postprocess.py`
- Modify: `src/recorder/__init__.py`

- [ ] **Step 1: Write failing post-processing tests**

```python
from src.recorder.models import EndReason, OutputPlan, ProcessResult, RecordRequest, SaveFormat
from src.recorder.postprocess import PostProcessor


def test_segmented_plan_expands_real_files_in_order(tmp_path):
    files = [tmp_path / "a_001.ts", tmp_path / "a_000.ts"]
    for path in files: path.write_bytes(b"x")
    plan = OutputPlan(tmp_path / "a_%03d.ts", tmp_path / "a_*.ts", SaveFormat.TS, True)
    assert PostProcessor().files_for(plan) == tuple(sorted(files))


def test_failed_process_skips_converter_and_script(tmp_path): ...
def test_completed_and_comment_stopped_use_same_conversion_rule(tmp_path): ...
def test_conversion_error_is_reported_and_source_is_preserved(tmp_path): ...
def test_custom_script_runs_once_after_success(tmp_path): ...
```

Inject converter and script-runner callables and assert calls instead of invoking FFmpeg or a shell.

- [ ] **Step 2: Run RED**

Run: `.\.venv\Scripts\python.exe -m pytest tests/recorder/test_postprocess.py -q`

Expected: collection fails because `PostProcessor` does not exist.

- [ ] **Step 3: Implement `PostProcessor`**

Use `files_for(plan)` to return the output path for non-segmented plans or sorted `Path.parent.glob(Path.name)` results for segmented plans. `run(request, plan, process_result)` must immediately return an empty result when `reason.is_success` is false. Convert each TS file only when `convert_to_mp4` is enabled. Call the custom script exactly once after successful processing. Catch each post-processing exception, append it to `PostprocessResult.errors`, and never delete a source after a failed conversion.

- [ ] **Step 4: Run GREEN**

Run: `.\.venv\Scripts\python.exe -m pytest tests/recorder/test_postprocess.py -q`

Expected: all post-processing tests pass, including the `%03d` regression.

- [ ] **Step 5: Checkpoint commit when Git is available**

```powershell
git add src/recorder/postprocess.py src/recorder/__init__.py tests/recorder/test_postprocess.py
git commit -m "feat: add recorder post-processing boundary"
```

### Task 6: Orchestrate FFmpeg and direct-FLV strategies

**Files:**
- Create: `src/recorder/pipeline.py`
- Create: `tests/recorder/test_pipeline.py`
- Modify: `src/recorder/__init__.py`

- [ ] **Step 1: Write failing orchestration tests**

Use fakes for path builder, command builder, process runner, postprocessor, direct downloader, `on_start`, and `on_finish`. Cover:

```python
def test_ffmpeg_strategy_builds_runs_and_postprocesses_once(): ...
def test_direct_flv_skips_ffmpeg_split_conversion_and_custom_script(): ...
def test_audio_only_request_executes_exactly_one_process(): ...
def test_finish_callback_runs_when_path_builder_raises(): ...
def test_failed_process_reaches_postprocessor_but_success_actions_are_gated(): ...
```

- [ ] **Step 2: Run RED**

Run: `.\.venv\Scripts\python.exe -m pytest tests/recorder/test_pipeline.py -q`

Expected: collection fails because `RecordingPipeline` does not exist.

- [ ] **Step 3: Implement `RecordingPipeline`**

Use constructor injection for the four modules and direct downloader. Public entry point:

```python
def run(self, request: RecordRequest, *, should_comment_stop: Callable[[], bool],
        should_exit: Callable[[], bool], on_start: Callable[[OutputPlan], None] | None = None,
        on_finish: Callable[[], None] | None = None, startupinfo=None) -> PipelineResult:
```

Build the output once. For direct FLV, call the downloader once and synthesize `COMPLETED` or `FAILED`; do not call FFmpeg or postprocessor success actions. For all other requests, build and run exactly one FFmpeg command, then postprocess. Invoke `on_start` after path creation and `on_finish` from `finally` even when any stage raises. Do not contain a loop that can execute a second format branch.

- [ ] **Step 4: Run GREEN and the complete recorder suite**

Run: `.\.venv\Scripts\python.exe -m pytest tests/recorder -q`

Expected: all recorder tests pass.

- [ ] **Step 5: Checkpoint commit when Git is available**

```powershell
git add src/recorder/pipeline.py src/recorder/__init__.py tests/recorder/test_pipeline.py
git commit -m "feat: orchestrate recording strategies"
```

### Task 7: Wire the pipeline into `main.py`

**Files:**
- Modify: `main.py:240-632`
- Modify: `main.py:1284-1535` and the remainder of the inline format branches
- Create: `tests/recorder/test_main_wiring.py`

- [ ] **Step 1: Write failing static wiring tests**

```python
from pathlib import Path


def test_main_uses_recording_pipeline_and_no_longer_builds_format_commands_inline():
    source = Path("main.py").read_text(encoding="utf-8")
    assert "from src.recorder import" in source
    assert "RecordingPipeline(" in source
    assert "RecordRequest(" in source
    recording_tail = source[source.index("real_url = select_source_url"):]
    assert 'elif record_save_type == "FLV"' not in recording_tail
    assert 'elif record_save_type == "MKV"' not in recording_tail
    assert 'elif record_save_type == "MP4"' not in recording_tail


def test_main_delegates_process_lifecycle():
    source = Path("main.py").read_text(encoding="utf-8")
    assert "def check_subprocess(" not in source
```

- [ ] **Step 2: Run RED**

Run: `.\.venv\Scripts\python.exe -m pytest tests/recorder/test_main_wiring.py -q`

Expected: assertions fail because the old inline pipeline is still present.

- [ ] **Step 3: Add compatibility adapters and request construction**

Import `RecordRequest`, `RecordingPipeline`, `SaveFormat`, and concrete recorder collaborators. Move the bodies of `converts_mp4`, custom script invocation, and `direct_download_stream` behind injected adapter callables; retain a thin wrapper only where other code still calls the old name.

At the current `real_url` boundary, normalize:

- final format, including H.265 FLV → TS;
- 猫耳 FM/Look → audio-only effective MP3 unless the configured format is already MP3/M4A;
- Shopee/花椒 → direct FLV;
- output root and folder flags;
- platform headers, proxy, overseas values, split settings, conversion flags, and custom script.

Construct exactly one `RecordRequest` and call one `RecordingPipeline.run()`. Map callbacks to existing `recording`, `recording_time_list`, `clear_record_info`, URL comments, exit flag, logging, subtitle thread, error window, and completion output.

- [ ] **Step 4: Delete replaced inline behavior**

Remove `check_subprocess` and the six inline output-format command branches. Remove duplicate post-processing dispatch from `main.py`. Keep platform discovery, source selection, push logic, subtitle behavior, and polling semantics unchanged.

- [ ] **Step 5: Run wiring, syntax, and focused regression tests**

Run: `.\.venv\Scripts\python.exe -m pytest tests/recorder tests/platforms -q`

Expected: all tests pass.

Run: `.\.venv\Scripts\python.exe -m py_compile main.py src/recorder/*.py`

Expected: exit code 0 with no output.

- [ ] **Step 6: Checkpoint commit when Git is available**

```powershell
git add main.py src/recorder tests/recorder
git commit -m "refactor: route main recording through pipeline"
```

### Task 8: Update documentation and run complete verification

**Files:**
- Modify: `docs/项目优化实施路线图.md`
- Modify: `docs/superpowers/plans/2026-06-20-pr4-recorder-pipeline.md` (checkbox state only)

- [ ] **Step 1: Update PR4 implementation status**

Document the new modules, the four fixed defects, compatibility boundaries, and exact test results. State that real network/live-room validation remains optional and was not used as an automated gate.

- [ ] **Step 2: Run the full test suite**

Run: `.\.venv\Scripts\python.exe -m pytest -q`

Expected: all tests pass with no collection errors.

- [ ] **Step 3: Run Ruff and formatting checks**

Run: `.\.venv\Scripts\python.exe -m ruff check main.py src tests`

Expected: `All checks passed!`

Run: `.\.venv\Scripts\python.exe -m ruff format --check src/recorder tests/recorder`

Expected: all listed files are already formatted.

- [ ] **Step 4: Run syntax compilation**

Run: `.\.venv\Scripts\python.exe -m py_compile main.py src/recorder/*.py`

Expected: exit code 0 with no output.

- [ ] **Step 5: Audit the four defect signatures**

Run: `rg -n 'segment_format.*mpegts|%03d|only_audio_record|check_subprocess|elif record_save_type' main.py src/recorder tests/recorder`

Expected: no M4A path uses MPEG-TS; `%03d` occurs only in output planning/tests; no old audio fallthrough or `check_subprocess` implementation remains in `main.py`.

- [ ] **Step 6: Final checkpoint commit when Git is available**

```powershell
git add docs/项目优化实施路线图.md docs/superpowers/plans/2026-06-20-pr4-recorder-pipeline.md
git commit -m "docs: record PR4 recorder pipeline completion"
```
