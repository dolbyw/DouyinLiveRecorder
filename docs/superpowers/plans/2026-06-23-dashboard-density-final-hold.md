# Dashboard Density and Final Hold Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver approved layout A with meaningful per-room realtime details and keep the completed remux dashboard visible until the user presses a key or Ctrl+C.

**Architecture:** Extend the thread-safe dashboard snapshot with application phase, start time, last real probe time, and recording output pattern. Keep filesystem-derived size/bitrate formatting in small presentation helpers, and isolate single-key console waiting behind a testable adapter used by the signal handler.

**Tech Stack:** Python 3.12, Rich, pytest, FFmpeg/ffprobe, PyInstaller

---

## File map

- Modify `src/dashboard_state.py`: add application phases and realtime room fields.
- Modify `src/cli_ui.py`: render layout A header, full-width path, adaptive details, and final prompt.
- Create `src/runtime/exit_wait.py`: testable single-key wait adapter.
- Modify `main.py`: publish real probe/output data and wait after remux completion.
- Modify `tests/test_dashboard_state.py`: verify phase monotonicity and probe/output fields.
- Modify `tests/test_cli_ui.py`: verify header, path and state-specific details.
- Create `tests/runtime/test_exit_wait.py`: verify interactive and non-interactive waiting.
- Modify `tests/runtime/test_main_runtime_wiring.py`: enforce final-hold wiring.

### Task 1: Extend the dashboard state contract

**Files:**
- Modify: `tests/test_dashboard_state.py`
- Modify: `src/dashboard_state.py`

- [ ] **Step 1: Write failing state tests**

Add tests for start time, monotonic phase transitions, real probe timestamps and output paths:

```python
def test_snapshot_carries_start_time_and_monotonic_application_phase():
    store = DashboardStateStore(started_at=STARTED_AT)
    store.set_phase(AppDisplayPhase.STOPPING)
    store.set_phase(AppDisplayPhase.RUNNING)

    snapshot = store.snapshot(now=NOW)

    assert snapshot.started_at == STARTED_AT
    assert snapshot.phase is AppDisplayPhase.STOPPING


def test_monitoring_records_only_real_probe_time():
    store = configured_store()
    store.mark_monitoring(ROOM_ID, at=STARTED_AT, checked=True)
    store.mark_monitoring(ROOM_ID, at=NOW, checked=False)

    assert store.snapshot(now=NOW).rooms[0].last_checked_at == STARTED_AT


def test_recording_snapshot_carries_output_pattern():
    store = configured_store()
    store.mark_recording(ROOM_ID, "序号1 招财", "原画", STARTED_AT, output_path="D:/downloads/a_%03d.ts")

    assert store.snapshot(now=NOW).rooms[0].output_path == "D:/downloads/a_%03d.ts"
```

- [ ] **Step 2: Run state tests and verify RED**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_dashboard_state.py -q
```

Expected: import/signature failures because `AppDisplayPhase`, `started_at`, `last_checked_at`, and `output_path` do not exist.

- [ ] **Step 3: Implement the minimal state model**

Add:

```python
class AppDisplayPhase(StrEnum):
    RUNNING = "运行正常"
    STOPPING = "正在停止"
    FINALIZING = "正在收尾"
    COMPLETE = "收尾完成"


_PHASE_PRIORITY = {
    AppDisplayPhase.RUNNING: 0,
    AppDisplayPhase.STOPPING: 1,
    AppDisplayPhase.FINALIZING: 2,
    AppDisplayPhase.COMPLETE: 3,
}
```

Add `started_at` and `phase` to `DashboardSnapshot`; add `last_checked_at` and `output_path` to mutable and immutable rooms. Make `DashboardStateStore(started_at=None)` capture one timezone-aware start value, and implement:

```python
def set_phase(self, phase: AppDisplayPhase) -> None:
    with self._lock:
        if _PHASE_PRIORITY[phase] >= _PHASE_PRIORITY[self._phase]:
            self._phase = phase
```

Extend `mark_monitoring(..., checked: bool = True)` so only real checks change `last_checked_at`. Extend `mark_recording(..., output_path: str | None = None)` without clearing a previously known path when sync callers omit it.

- [ ] **Step 4: Run state tests and verify GREEN**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_dashboard_state.py -q
```

Expected: all state tests pass.

### Task 2: Render layout A and adaptive realtime details

**Files:**
- Modify: `tests/test_cli_ui.py`
- Modify: `src/cli_ui.py`

- [ ] **Step 1: Write failing UI contract tests**

Update the fixture with `started_at`, `last_checked_at`, `output_path`, and `AppDisplayPhase`. Add assertions:

```python
def test_header_shows_phase_and_two_full_timestamps_without_ffmpeg_metric():
    output = render_dashboard(dashboard_snapshot(), width=140)
    assert "DouyinLiveRecorder  ● 运行正常" in output
    assert "当前  2026-06-23 08:16:24" in output
    assert "启动  2026-06-23 08:00:00" in output
    assert output.count("FFmpeg") == 1
    assert "错误" in output


def test_complete_phase_shows_key_exit_prompt():
    snapshot = replace(dashboard_snapshot(), phase=AppDisplayPhase.COMPLETE)
    output = render_dashboard(snapshot, width=140)
    assert "收尾完成" in output
    assert "按任意键退出" in output
    assert "Ctrl+C 强制退出" in output
```

Add direct helper tests with `tmp_path` for non-segmented and `%03d` segmented output patterns. Assert details contain total MB and Mbps. Add monitoring countdown and conversion task-name assertions.

- [ ] **Step 2: Run UI tests and verify RED**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_cli_ui.py -q
```

Expected: failures for missing phase title, second timestamp, error card, full-width path and adaptive details.

- [ ] **Step 3: Add presentation helpers**

Implement focused helpers:

```python
def _recording_files(pattern: str) -> tuple[Path, ...]:
    path = Path(pattern)
    if "%03d" not in pattern:
        return (path,) if path.is_file() else ()
    glob_path = Path(pattern.replace("%03d", "*"))
    return tuple(glob_path.parent.glob(glob_path.name))


def _format_room_detail(room: DashboardRoom, snapshot: DashboardSnapshot) -> str:
    if room.status is RoomDisplayStatus.WAITING:
        return "等待首次检测"
    if room.status is RoomDisplayStatus.MONITORING:
        if room.last_checked_at is None:
            return "等待首次检测"
        remaining = max(0, snapshot.config.poll_seconds - int((snapshot.current_time - room.last_checked_at).total_seconds()))
        return f"下次检测 {remaining // 60:02d}:{remaining % 60:02d}"
    if room.status is RoomDisplayStatus.RECORDING:
        files = _recording_files(room.output_path or "")
        size = sum(path.stat().st_size for path in files)
        elapsed = max(1.0, room.elapsed_seconds or 0)
        return f"{_format_bytes(size)} · {size * 8 / elapsed / 1_000_000:.1f} Mbps" if size else "正在写入"
    if room.status is RoomDisplayStatus.CONVERTING:
        return room.task_name or "正在转码"
    if room.status is RoomDisplayStatus.RETRYING:
        return room.last_error or "等待重试"
    return "配置已停用"
```

Catch `OSError` around file enumeration/stat and fall back to the output filename or `正在写入`.

- [ ] **Step 4: Rebuild the layout hierarchy**

Use the outer panel title for `DouyinLiveRecorder  ● {phase.value}`. Put full current and start datetimes plus FFmpeg on the metadata row. Replace the fifth metric with `error_count`. Build the configuration panel as `Group(config_grid, full_width_path_text)` so save path owns a full row. Rename the last table column to `实时详情` and use `_format_room_detail`.

When phase is `COMPLETE`, append a centered green prompt panel: `按任意键退出  |  Ctrl+C 强制退出`. Mirror the same fields in `build_plain_dashboard`.

- [ ] **Step 5: Run UI and state tests and verify GREEN**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_cli_ui.py tests\test_dashboard_state.py -q
```

Expected: all selected tests pass.

### Task 3: Add a safe single-key exit adapter

**Files:**
- Create: `tests/runtime/test_exit_wait.py`
- Create: `src/runtime/exit_wait.py`
- Modify: `src/runtime/__init__.py`

- [ ] **Step 1: Write failing adapter tests**

```python
from src.runtime.exit_wait import wait_for_exit_key


def test_interactive_wait_reads_exactly_one_key():
    calls = []
    assert wait_for_exit_key(is_interactive=lambda: True, read_key=lambda: calls.append("read") or "x") is True
    assert calls == ["read"]


def test_noninteractive_wait_returns_without_reading():
    assert wait_for_exit_key(is_interactive=lambda: False, read_key=lambda: (_ for _ in ()).throw(AssertionError())) is False
```

- [ ] **Step 2: Run adapter tests and verify RED**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\runtime\test_exit_wait.py -q
```

Expected: collection fails because `src.runtime.exit_wait` does not exist.

- [ ] **Step 3: Implement the adapter**

Implement `wait_for_exit_key(*, is_interactive=None, read_key=None) -> bool`. Default interactivity is `sys.stdin is not None and sys.stdin.isatty()`. On Windows default `read_key` imports and calls `msvcrt.getwch`; elsewhere it calls `input`. Return `False` immediately when non-interactive or on `EOFError`/`OSError`; otherwise return `True` after one key.

- [ ] **Step 4: Run adapter tests and verify GREEN**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\runtime\test_exit_wait.py -q
```

Expected: both tests pass.

### Task 4: Wire real activity data and final dashboard hold

**Files:**
- Modify: `tests/runtime/test_main_runtime_wiring.py`
- Modify: `main.py`

- [ ] **Step 1: Add failing wiring tests**

Add AST/source assertions that:

```python
assert "DashboardStateStore(started_at=start_display_time)" in source
assert "output_path=str(plan.output_path)" in start_record_source()
assert "dashboard_store.mark_monitoring(room.room_id" in source
assert "checked=False" in build_dashboard_snapshot_source
assert "dashboard_store.set_phase(AppDisplayPhase.STOPPING)" in signal_handler_source
assert "dashboard_store.set_phase(AppDisplayPhase.COMPLETE)" in signal_handler_source
assert "wait_for_exit_key()" in signal_handler_source
assert signal_handler_source.index("wait_for_exit_key()") < signal_handler_source.index("sys.exit(0)")
```

- [ ] **Step 2: Run wiring tests and verify RED**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\runtime\test_main_runtime_wiring.py -q
```

Expected: new assertions fail because state initialization, output/probe wiring and final wait do not exist.

- [ ] **Step 3: Wire start time, output path and real probes**

Make `start_display_time` timezone-aware and construct `DashboardStateStore(started_at=start_display_time)`. Pass `output_path=str(plan.output_path)` from `on_pipeline_start`. In `mark_runtime_success`, call `dashboard_store.mark_monitoring(room.room_id)` after a real probe cycle. In snapshot synchronization call `mark_monitoring(..., checked=False)` so refreshes cannot reset the countdown.

Include file position in conversion task text:

```python
dashboard_store.mark_converting(
    room_id,
    f"{index}/{total} · {progress.source.name}",
    progress.percent,
    progress.elapsed,
    progress.duration,
)
```

- [ ] **Step 4: Wire stop/finalize/complete and key wait**

In `signal_handler`, set `STOPPING` immediately after the first request. Conversion progress sets `FINALIZING`. After runtime join and `recording` becomes empty, add the final event once, set `COMPLETE`, call `wait_for_exit_key()`, then call `sys.exit(0)`. Keep the second signal behavior untouched through `ShutdownControl.request()`.

Skip configuration/runtime snapshot synchronization in `build_dashboard_snapshot` once `exit_recording` is true, while still returning a fresh dashboard snapshot so current time continues updating.

- [ ] **Step 5: Run focused runtime/UI tests and verify GREEN**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\runtime\test_main_runtime_wiring.py tests\runtime\test_exit_wait.py tests\test_dashboard_state.py tests\test_cli_ui.py -q
```

Expected: all selected tests pass.

### Task 5: Verify and package safely

**Files:**
- Verify all changed files and tests.
- Create `dist-ui-density-final-20260623/DouyinLiveRecorder`.
- Create `DouyinLiveRecorder-dashboard-density-final-win64-20260623.zip`.

- [ ] **Step 1: Run changed-file Ruff and full pytest**

```powershell
.\.venv\Scripts\python.exe -m ruff check main.py src\dashboard_state.py src\cli_ui.py src\runtime\exit_wait.py tests\test_dashboard_state.py tests\test_cli_ui.py tests\runtime\test_exit_wait.py tests\runtime\test_main_runtime_wiring.py
.\.venv\Scripts\python.exe -m pytest -q
```

Expected: changed-file lint exits 0 and all tests pass.

- [ ] **Step 2: Run real FFmpeg remux smoke**

Generate a one-second H.264 TS using the bundled FFmpeg, convert it through `FFmpegConverter`, and validate the MP4 with bundled ffprobe. Expected: source TS is deleted only after a readable MP4 exists.

- [ ] **Step 3: Build a new versioned distribution**

```powershell
.\.venv\Scripts\python.exe -m PyInstaller DouyinLiveRecorder.spec --noconfirm --distpath dist-ui-density-final-20260623 --workpath build-ui-density-final-20260623
```

Expected: the new executable exists. Do not overwrite either previous dist directory because they contain user recordings.

- [ ] **Step 4: Migrate active configuration and package**

Copy only `config.ini` and `URL_config.ini` from `dist-ui-remux-fixed-20260623/DouyinLiveRecorder/config` into the new package. Compress the new distribution to `DouyinLiveRecorder-dashboard-density-final-win64-20260623.zip` and verify both configuration hashes match.

- [ ] **Step 5: Report evidence and manual key-wait check**

Report exact test count, lint result, FFmpeg smoke result, package paths, and the remaining manual check: run the packaged console, press Ctrl+C once, observe `收尾完成`, then press a normal key.
