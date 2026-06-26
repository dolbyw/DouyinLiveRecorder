# Dashboard Polish and Graceful Remux Fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the Rich terminal dashboard match approved layout A and guarantee that the first Ctrl+C gracefully remuxes current TS recordings without a 255 error or a new recording cycle.

**Architecture:** Keep process-exit classification inside `RecorderProcess`, where process state and stop intent are both available. Add explicit shutdown gates at legacy/runtime scheduling boundaries, then revise only the Rich presentation layer to produce the approved hierarchy from the existing dashboard snapshot.

**Tech Stack:** Python 3.12, pytest, Rich, FFmpeg/ffprobe, PyInstaller

---

## File map

- Modify `src/recorder/process.py`: classify a process that exits after a requested stop as a graceful stop even when `poll()` wins the race.
- Modify `main.py`: prevent probes, recordings, and compatibility threads from starting after shutdown begins; do not report requested stops as errors.
- Modify `src/cli_ui.py`: render the approved five-level layout and responsive fallback.
- Modify `tests/recorder/test_process.py`: reproduce the 255 poll race.
- Modify `tests/runtime/test_main_runtime_wiring.py`: enforce shutdown gates in the main wiring.
- Modify `tests/test_cli_ui.py`: enforce layout A content, symbols, and narrow-terminal behavior.
- Rebuild `dist-ui-fixed-20260623/DouyinLiveRecorder`: package the verified implementation for Windows.

### Task 1: Fix the FFmpeg stop/poll race

**Files:**
- Modify: `tests/recorder/test_process.py`
- Modify: `src/recorder/process.py`

- [ ] **Step 1: Write the failing regression tests**

Add tests where `poll()` already returns 255 before `_stop()` can run:

```python
def test_polled_255_after_requested_exit_is_graceful():
    result = make_runner(FakeProcess([255])).run(
        ["ffmpeg"],
        should_comment_stop=lambda: False,
        should_exit=lambda: True,
    )

    assert result.reason is EndReason.EXIT_STOPPED
    assert result.return_code == 255


def test_polled_255_without_stop_request_is_failed():
    result = make_runner(FakeProcess([255])).run(
        ["ffmpeg"],
        should_comment_stop=lambda: False,
        should_exit=lambda: False,
    )

    assert result.reason is EndReason.FAILED
    assert result.return_code == 255
```

- [ ] **Step 2: Run the focused tests and verify RED**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\recorder\test_process.py -q
```

Expected: `test_polled_255_after_requested_exit_is_graceful` fails because the actual reason is `EndReason.FAILED`; the natural-failure test passes.

- [ ] **Step 3: Classify an observed exit with current stop intent**

In `RecorderProcess.run`, replace the direct nonzero mapping with a helper that preserves zero as completed and checks requested stops before declaring failure:

```python
if return_code is not None:
    if return_code == 0:
        return ProcessResult(EndReason.COMPLETED, return_code)
    if should_comment_stop():
        return ProcessResult(EndReason.COMMENT_STOPPED, return_code)
    if should_exit():
        return ProcessResult(EndReason.EXIT_STOPPED, return_code)
    return ProcessResult(EndReason.FAILED, return_code)
```

Keep `_stop()` unchanged so a process first observed as running still receives `q` on Windows or SIGINT on POSIX.

- [ ] **Step 4: Run process and post-processing tests and verify GREEN**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\recorder\test_process.py tests\recorder\test_postprocess.py tests\recorder\test_pipeline.py -q
```

Expected: all selected tests pass; the existing Ctrl+C postprocessor test proves `EXIT_STOPPED` TS files are converted.

- [ ] **Step 5: Record checkpoint**

This workspace has no `.git` directory, so no commit can be created. Record the completed task in the active plan and preserve only the scoped file changes.

### Task 2: Stop all new work once shutdown starts

**Files:**
- Modify: `tests/runtime/test_main_runtime_wiring.py`
- Modify: `main.py`

- [ ] **Step 1: Add failing source-contract tests for shutdown gates**

Add assertions that the legacy record loop returns before probing and the compatibility scheduler refuses new threads:

```python
def test_start_record_stops_before_a_new_probe_when_shutdown_is_requested():
    source = start_record_source()

    assert "if exit_recording or bool(stop_token and stop_token.shutdown_requested):" in source
    assert source.index("if exit_recording or bool(stop_token and stop_token.shutdown_requested):") < source.index(
        "record_quality_zh, record_url, anchor_name = url_data"
    )


def test_compatibility_scheduler_does_not_start_threads_during_shutdown():
    source = MAIN_PATH.read_text(encoding="utf-8")

    assert "if exit_recording:" in source
    scheduling = source[source.index("if len(text_no_repeat_url) > 0:") :]
    assert scheduling.index("if exit_recording:") < scheduling.index("threading.Thread(target=start_record")
```

- [ ] **Step 2: Run the focused wiring tests and verify RED**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\runtime\test_main_runtime_wiring.py -q
```

Expected: the two new tests fail because no explicit pre-probe or pre-thread shutdown gate exists.

- [ ] **Step 3: Add minimal shutdown gates**

At the start of the outer `start_record` loop, before resolving room values, return when either global or token shutdown is active:

```python
if exit_recording or bool(stop_token and stop_token.shutdown_requested):
    return
```

Add the same guard before each inner probe iteration so a loop cannot cross the shutdown boundary after a delay. In the main compatibility scheduling loop, break before creating a thread:

```python
for url_tuple in text_no_repeat_url:
    if exit_recording:
        break
```

After `pipeline.run`, handle requested stop results before the failure branch. `EXIT_STOPPED` and `COMMENT_STOPPED` must not call `mark_retrying`, emit `recording_error`, or increment `error_count`; their post-processing result must still be inspected and logged.

- [ ] **Step 4: Run runtime and recorder regression tests and verify GREEN**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\runtime tests\recorder -q
```

Expected: all runtime and recorder tests pass, including the new shutdown-gate contracts.

- [ ] **Step 5: Record checkpoint**

Because Git metadata is absent, record task completion in the plan instead of committing.

### Task 3: Implement approved dashboard layout A

**Files:**
- Modify: `tests/test_cli_ui.py`
- Modify: `src/cli_ui.py`

- [ ] **Step 1: Replace broad dashboard assertions with layout-A contracts**

Add focused tests for the five summary values, readable configuration, state symbols, six columns, and two-column event grid:

```python
def test_wide_dashboard_matches_approved_layout_a():
    buffer = StringIO()
    console = Console(file=buffer, force_terminal=True, color_system="standard", width=140)

    console.print(build_dashboard_renderable(dashboard_snapshot(), width=140))
    output = buffer.getvalue()

    for label in ("直播间", "录制中", "监控中", "转码中", "FFmpeg"):
        assert label in output
    assert "TS → MP4" in output
    assert "30 分钟" in output
    for heading in ("直播间", "状态", "质量", "时长/进度", "详情"):
        assert heading in output
    assert "● 录制" in output
    assert "◒ 转码" in output


def test_wide_dashboard_events_are_arranged_in_two_columns():
    renderable = build_dashboard_renderable(dashboard_snapshot(), width=140)
    event_table = renderable.renderable.renderables[-1]

    assert len(event_table.columns) == 2
```

Retain the existing narrow-terminal test and strengthen it to assert that `详情` and the full save path disappear while all four core columns remain.

- [ ] **Step 2: Run CLI UI tests and verify RED**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_cli_ui.py -q
```

Expected: layout-A tests fail because the current summary has four plain fields, configuration uses seconds, statuses lack symbols, and events use one column.

- [ ] **Step 3: Build the summary card and formatting helpers**

Add small presentation-only helpers:

```python
def _format_duration_setting(seconds: int | None) -> str:
    if not seconds:
        return "关闭"
    if seconds % 60 == 0:
        return f"{seconds // 60} 分钟"
    return f"{seconds} 秒"


def _format_save_path(path: str, width: int) -> str:
    if len(path) <= width:
        return path
    tail = path.replace("/", "\\").rsplit("\\", maxsplit=1)[-1]
    return f"…\\{tail}" if len(tail) + 2 <= width else _truncate(tail, width)
```

Compute `converting_count` directly from rooms whose status is `RoomDisplayStatus.CONVERTING`. Construct five one-cell bordered panels or equivalent Rich cells with equal ratios; each contains a bright value and a dim label.

- [ ] **Step 4: Build configuration, table, and event hierarchy**

For width at least 100:

- show `TS → MP4` when `save_format == "TS" and convert_to_mp4`;
- create four equal configuration columns across two rows;
- use the exact table order `# / 直播间 / 状态 / 质量 / 时长/进度 / 详情`;
- prefix statuses with `●`, `◒`, or `!` and use green/amber/cyan/red semantics;
- create a two-column event table with up to four cells and append `无错误 · 运行稳定` when `error_count == 0`.

For narrower widths, omit the detail column and collapse configuration while preserving the four core room fields.

- [ ] **Step 5: Run UI tests and verify GREEN**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_cli_ui.py tests\test_dashboard_state.py -q
```

Expected: all selected tests pass without warnings.

- [ ] **Step 6: Render a deterministic dashboard preview**

Use the existing `dashboard_snapshot()` fixture data with a 140-column Rich console and save the ANSI-free output for comparison. Confirm all five visual levels appear in the same order as layout A and no row wraps at 140 columns.

- [ ] **Step 7: Record checkpoint**

Because Git metadata is absent, record task completion in the plan instead of committing.

### Task 4: Full verification and Windows package

**Files:**
- Verify: all source and test files
- Rebuild: `dist-ui-fixed-20260623/DouyinLiveRecorder`

- [ ] **Step 1: Run formatting and static checks**

Run:

```powershell
.\.venv\Scripts\python.exe -m ruff check main.py src tests
```

Expected: exit code 0 with no lint errors. Fix only violations caused by this change; report unrelated pre-existing violations separately.

- [ ] **Step 2: Run the complete test suite**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

Expected: exit code 0 and zero failed tests.

- [ ] **Step 3: Reproduce the Ctrl+C race without a live stream**

Run the process and pipeline regression tests once more with verbose names:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\recorder\test_process.py tests\recorder\test_postprocess.py -vv
```

Expected: the poll-first 255 test, natural 255 failure test, and Ctrl+C conversion test all pass.

- [ ] **Step 4: Build the Windows distribution**

Run the existing PyInstaller spec with clean output directories:

```powershell
.\.venv\Scripts\python.exe -m PyInstaller DouyinLiveRecorder.spec --noconfirm --distpath dist-ui-fixed-20260623 --workpath build-ui-fixed-20260623
```

Expected: exit code 0 and `dist-ui-fixed-20260623\DouyinLiveRecorder\DouyinLiveRecorder.exe` exists.

- [ ] **Step 5: Verify packaged resources and executable startup gate**

Confirm the packaged directory contains `config`, `src`, `index.html`, and `StopRecording.vbs`. Launch only if doing so will not overwrite user configuration; otherwise verify PyInstaller analysis output and package contract tests:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_packaging_wiring.py tests\runtime\test_package_contract.py -q
```

Expected: all package contract tests pass.

- [ ] **Step 6: Report verification evidence and remaining manual live-stream check**

Report exact test counts, lint status, build status, and artifact path. If no live rooms are safely available, state that the automated race reproduction passed while the final multi-room live Ctrl+C check remains for the user.
