# Graceful TS Remux and Progress Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ensure shutdown waits for every TS-to-MP4 conversion, shows machine-derived FFmpeg progress, and preserves TS sources whenever conversion fails.

**Architecture:** Add a focused `FFmpegConverter` that probes duration, parses FFmpeg's progress protocol, and atomically publishes MP4 files. Keep file ordering in `PostProcessor`, render progress through the CLI layer, and replace the fixed ten-second signal wait with a two-stage graceful/forced shutdown controller.

**Tech Stack:** Python 3.11, subprocess/FFmpeg/ffprobe, pathlib, threading, Rich-compatible console output, pytest, Ruff

---

## File Structure

- Create `src/recorder/converter.py`: conversion command construction, duration probing, progress parsing, temporary output lifecycle, and error propagation.
- Create `tests/recorder/test_converter.py`: isolated fake-process tests for progress, success, failure, and probe fallback.
- Modify `src/recorder/postprocess.py`: pass deterministic file position metadata to each converter invocation.
- Modify `tests/recorder/test_postprocess.py`: lock the indexed converter contract and error continuation behavior.
- Modify `src/recorder/__init__.py`: export the converter API.
- Modify `src/cli_ui.py`: format and throttle progress output without coupling conversion to Rich.
- Modify `tests/test_cli_ui.py`: verify determinate and indeterminate progress text.
- Modify `main.py`: wire the converter and progress presenter; implement first-signal drain and second-signal force exit.
- Modify `tests/runtime/test_main_runtime_wiring.py`: verify shutdown and converter wiring structurally.
- Create `tests/runtime/test_shutdown_control.py`: test two-stage shutdown state without importing side-effectful `main.py`.
- Create `src/runtime/shutdown.py`: small, independently testable two-stage signal state.
- Modify `src/runtime/__init__.py`: export shutdown control.

### Task 1: Parse FFmpeg progress and build conversion commands

**Files:**
- Create: `src/recorder/converter.py`
- Create: `tests/recorder/test_converter.py`
- Modify: `src/recorder/__init__.py`

- [ ] **Step 1: Write the failing progress and command tests**

```python
from pathlib import Path

from src.recorder.converter import ConversionProgress, FFmpegConverter, parse_progress_time


def test_progress_time_prefers_out_time_us_and_clamps_percentage():
    assert parse_progress_time("out_time_us", "2500000") == 2.5
    progress = ConversionProgress(Path("a.ts"), elapsed=12.0, duration=10.0, finished=False)
    assert progress.percent == 100.0


def test_copy_command_uses_progress_protocol_and_temporary_target(tmp_path):
    source = tmp_path / "a.ts"
    converter = FFmpegConverter()
    command = converter.build_command(source, tmp_path / "a.converting.mp4", transcode_h264=False)
    assert command[:5] == ["ffmpeg", "-y", "-v", "error", "-i"]
    assert ["-c:v", "copy", "-c:a", "copy"] == command[command.index("-c:v"):command.index("-progress")]
    assert command[-4:] == ["-progress", "pipe:1", "-nostats", str(tmp_path / "a.converting.mp4")]
```

- [ ] **Step 2: Run the focused tests and verify RED**

Run: `python -m pytest tests/recorder/test_converter.py -q --basetemp=.pytest-tmp-converter-red`

Expected: FAIL because `src.recorder.converter` does not exist.

- [ ] **Step 3: Implement the progress model, parser, and command builder**

```python
@dataclass(frozen=True, slots=True)
class ConversionProgress:
    source: Path
    elapsed: float
    duration: float | None
    finished: bool = False

    @property
    def percent(self) -> float | None:
        if self.duration is None or self.duration <= 0:
            return None
        return min(100.0, max(0.0, self.elapsed / self.duration * 100.0))


def parse_progress_time(key: str, value: str) -> float | None:
    if key not in {"out_time_us", "out_time_ms"}:
        return None
    try:
        return max(0.0, int(value) / 1_000_000)
    except ValueError:
        return None
```

Implement `FFmpegConverter.build_command()` with the exact copy and H.264 codec settings from the approved design, `-progress pipe:1`, `-nostats`, and the supplied temporary target.

- [ ] **Step 4: Export the public API and verify GREEN**

Add `ConversionError`, `ConversionProgress`, and `FFmpegConverter` to `src/recorder/__init__.py`, then run:

`python -m pytest tests/recorder/test_converter.py -q --basetemp=.pytest-tmp-converter-green`

Expected: PASS.

- [ ] **Step 5: Record checkpoint**

No Git commit is possible because this workspace has no `.git` directory. Record the passing command in the task handoff instead.

### Task 2: Implement safe conversion lifecycle

**Files:**
- Modify: `src/recorder/converter.py`
- Modify: `tests/recorder/test_converter.py`

- [ ] **Step 1: Write failing success, failure, and probe-fallback tests**

Use fake probe and process factories. The success fake writes the temporary MP4, exposes progress lines (`out_time_us=...`, `progress=continue`, `progress=end`), and returns zero. Assert that the final MP4 exists, the temporary path is gone, deletion follows `delete_source`, and the last callback is 100%/finished. The failure fake returns nonzero after writing a temporary file; assert `ConversionError`, TS preservation, and temporary-file removal. Make the probe fake raise `CalledProcessError`; assert conversion still runs and callbacks have `duration is None`.

```python
def test_failed_conversion_preserves_source_and_removes_temporary_file(tmp_path):
    source = tmp_path / "a.ts"
    source.write_bytes(b"ts")
    process = FakeProcess(returncode=1, lines=["fatal conversion error\n"])
    converter = FFmpegConverter(process_factory=lambda *_a, **_k: process, probe_duration=lambda _p: 10.0)
    with pytest.raises(ConversionError, match="fatal conversion error"):
        converter.convert(source, delete_source=True)
    assert source.exists()
    assert not (tmp_path / "a.converting.mp4").exists()
```

- [ ] **Step 2: Verify RED**

Run: `python -m pytest tests/recorder/test_converter.py -q --basetemp=.pytest-tmp-converter-lifecycle-red`

Expected: FAIL because `convert()` and injectable process/probe seams are not implemented.

- [ ] **Step 3: Implement probe and conversion**

Implement `probe_duration()` using:

```text
ffprobe -v error -show_entries format=duration -of default=noprint_wrappers=1:nokey=1 SOURCE
```

Implement `convert(source, transcode_h264=False, delete_source=True, on_progress=None)` so it validates a nonempty source, removes a stale `.converting.mp4`, tolerates probe failure, streams progress records, keeps bounded diagnostic lines, waits for FFmpeg, atomically calls `temporary.replace(final)`, and deletes TS only after replacement. Progress callback exceptions must be suppressed as presentation-only failures.

- [ ] **Step 4: Verify GREEN**

Run: `python -m pytest tests/recorder/test_converter.py -q --basetemp=.pytest-tmp-converter-lifecycle-green`

Expected: all converter tests PASS.

- [ ] **Step 5: Record checkpoint**

No Git commit is possible; retain the focused test output for final reporting.

### Task 3: Pass segment position and render progress

**Files:**
- Modify: `src/recorder/postprocess.py`
- Modify: `tests/recorder/test_postprocess.py`
- Modify: `src/cli_ui.py`
- Modify: `tests/test_cli_ui.py`

- [ ] **Step 1: Write failing indexed-postprocessor test**

```python
def test_segment_conversion_receives_one_based_file_position(tmp_path):
    first, second = tmp_path / "a_000.ts", tmp_path / "a_001.ts"
    first.write_bytes(b"x")
    second.write_bytes(b"x")
    calls = []
    plan = OutputPlan(tmp_path / "a_%03d.ts", tmp_path / "a_*.ts", SaveFormat.TS, True)
    PostProcessor(converter=lambda path, h264, index, total: calls.append((path, index, total))).run(
        make_request(tmp_path, convert_to_mp4=True), plan, ProcessResult(EndReason.COMPLETED, 0)
    )
    assert calls == [(first, 1, 2), (second, 2, 2)]
```

Update existing two-argument converter test doubles in the same test file to accept `index` and `total`.

- [ ] **Step 2: Write failing CLI formatting tests**

```python
def test_format_conversion_progress_includes_file_position_percent_and_times():
    progress = ConversionProgress(Path("主播_001.ts"), 72, 152)
    assert format_conversion_progress(progress, 2, 3) == (
        "[转MP4 2/3] 主播_001.ts 47.4%  00:01:12 / 00:02:32"
    )


def test_format_conversion_progress_handles_unknown_duration():
    progress = ConversionProgress(Path("a.ts"), 4, None)
    assert "--.-%" in format_conversion_progress(progress, 1, 1)
```

- [ ] **Step 3: Verify RED**

Run: `python -m pytest tests/recorder/test_postprocess.py tests/test_cli_ui.py -q --basetemp=.pytest-tmp-progress-ui-red`

Expected: FAIL on the new converter arity and missing formatter.

- [ ] **Step 4: Implement indexed invocation and formatter**

Change the converter contract to `Callable[[Path, bool, int, int], None]`. Iterate with `enumerate(files, start=1)` and pass `len(files)`. Add `format_media_time()` and `format_conversion_progress()` to `src/cli_ui.py`; format hours, minutes, seconds and use `--.-%`/`--:--:--` when duration is unknown.

- [ ] **Step 5: Verify GREEN**

Run: `python -m pytest tests/recorder/test_postprocess.py tests/test_cli_ui.py -q --basetemp=.pytest-tmp-progress-ui-green`

Expected: all selected tests PASS.

- [ ] **Step 6: Record checkpoint**

No Git commit is possible; retain the focused test output.

### Task 4: Add two-stage shutdown control

**Files:**
- Create: `src/runtime/shutdown.py`
- Create: `tests/runtime/test_shutdown_control.py`
- Modify: `src/runtime/__init__.py`

- [ ] **Step 1: Write the failing controller tests**

```python
def test_first_request_starts_graceful_shutdown_without_forcing():
    forced = []
    control = ShutdownControl(force_exit=forced.append)
    assert control.request() is True
    assert control.requested is True
    assert forced == []


def test_second_request_forces_interrupted_exit():
    forced = []
    control = ShutdownControl(force_exit=forced.append)
    control.request()
    assert control.request() is False
    assert forced == [130]
```

- [ ] **Step 2: Verify RED**

Run: `python -m pytest tests/runtime/test_shutdown_control.py -q --basetemp=.pytest-tmp-shutdown-red`

Expected: FAIL because `ShutdownControl` does not exist.

- [ ] **Step 3: Implement thread-safe shutdown state**

```python
class ShutdownControl:
    def __init__(self, force_exit=os._exit) -> None:
        self._force_exit = force_exit
        self._requested = threading.Event()

    @property
    def requested(self) -> bool:
        return self._requested.is_set()

    def request(self) -> bool:
        if self._requested.is_set():
            self._force_exit(130)
            return False
        self._requested.set()
        return True
```

Export `ShutdownControl` from `src/runtime/__init__.py`.

- [ ] **Step 4: Verify GREEN**

Run: `python -m pytest tests/runtime/test_shutdown_control.py -q --basetemp=.pytest-tmp-shutdown-green`

Expected: both tests PASS.

- [ ] **Step 5: Record checkpoint**

No Git commit is possible; retain the focused test output.

### Task 5: Wire atomic conversion, visible progress, and complete shutdown drain

**Files:**
- Modify: `main.py`
- Modify: `tests/runtime/test_main_runtime_wiring.py`

- [ ] **Step 1: Write failing structural regression tests**

Add AST/source assertions that `main.py` constructs `FFmpegConverter`, passes all four postprocessor converter arguments, calls `format_conversion_progress`, uses `ShutdownControl`, calls `async_runtime_host.join()` with no timeout, and contains no `join(timeout=10)` in `signal_handler`.

```python
def test_signal_handler_waits_for_runtime_without_ten_second_cutoff():
    source = MAIN_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source)
    function = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "signal_handler")
    handler_source = ast.get_source_segment(source, function) or ""
    assert "shutdown_control.request()" in handler_source
    assert "async_runtime_host.join()" in handler_source
    assert "join(timeout=10)" not in handler_source
```

- [ ] **Step 2: Verify RED**

Run: `python -m pytest tests/runtime/test_main_runtime_wiring.py -q --basetemp=.pytest-tmp-main-wiring-red`

Expected: FAIL because fixed-timeout shutdown and legacy converter wiring remain.

- [ ] **Step 3: Replace conversion wiring**

Construct one `FFmpegConverter`. For every postprocessor invocation, create a callback that formats progress with the supplied index and total, serializes console writes through a lock, and throttles ordinary updates to at most once per second while always showing start and completion. Pass `request.convert_to_h264` directly to `FFmpegConverter.convert()` and remove the old exception-swallowing `converts_mp4()` path from recording post-processing.

- [ ] **Step 4: Replace fixed-timeout signal exit**

Instantiate `ShutdownControl`. In `signal_handler`, call `request()` first; on the graceful path set `exit_recording`, print a message explaining that conversion may continue, request runtime shutdown, call `async_runtime_host.join()` without a timeout, wait until the active `recording` set is empty for legacy workers, and then raise `SystemExit(0)`. A repeated signal reaches the injected `os._exit(130)` force path immediately.

- [ ] **Step 5: Verify GREEN**

Run: `python -m pytest tests/runtime/test_main_runtime_wiring.py tests/runtime/test_shutdown_control.py tests/recorder/test_converter.py tests/recorder/test_postprocess.py tests/test_cli_ui.py -q --basetemp=.pytest-tmp-remux-integration-green`

Expected: all selected tests PASS.

- [ ] **Step 6: Record checkpoint**

No Git commit is possible; retain the integration test output.

### Task 6: Full verification and real FFmpeg smoke test

**Files:**
- Test only; no production changes unless verification exposes a defect.

- [ ] **Step 1: Run the full automated suite**

Run: `python -m pytest -q --basetemp=.pytest-tmp-remux-full`

Expected: all tests PASS with no pending-task warnings.

- [ ] **Step 2: Run lint and format checks**

Run: `python -m ruff check main.py src tests`

Expected: exit code 0.

Run: `python -m ruff format --check main.py src tests`

Expected: exit code 0.

- [ ] **Step 3: Compile changed Python modules**

Run: `python -m py_compile main.py src/recorder/converter.py src/recorder/postprocess.py src/runtime/shutdown.py src/cli_ui.py`

Expected: exit code 0.

- [ ] **Step 4: Run a bundled-FFmpeg smoke test**

Generate a short synthetic TS with `build/bundle_assets/ffmpeg/ffmpeg.exe`, convert it through `FFmpegConverter` with a captured progress callback, and inspect the result with `build/bundle_assets/ffmpeg/ffprobe.exe`. Assert final MP4 existence, TS deletion, at least one progress update, final 100%, and a readable MP4 duration.

- [ ] **Step 5: Review the final diff manually**

Confirm every approved requirement maps to a passing test, no unrelated files changed, TS deletion occurs only after atomic MP4 publication, and no ten-second shutdown cutoff remains.
