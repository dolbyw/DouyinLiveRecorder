# Terminal Dashboard Rewrite Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the current card-heavy terminal dashboard with the approved full-width operational dashboard, including persistent attention semantics, semantic events, responsive room budgeting, and an `R` room-list toggle, while preserving all recording behavior.

**Architecture:** Keep `DashboardStateStore` as the thread-safe runtime source, add a Rich-independent `dashboard_view` presentation layer, and make Rich/plain renderers consume the same immutable view model. Add a small isolated keyboard controller for interactive Windows consoles; it changes only presentation state and wakes the existing dashboard refresh event.

**Tech Stack:** Python 3.11+, dataclasses, Rich 15+, threading, pytest, Ruff, PyInstaller.

**Repository note:** This workspace has no `.git` directory. Commit steps are replaced by focused verification checkpoints; do not initialize a synthetic repository. Existing build folders, ZIP files, logs, downloads, and user configuration are not cleanup targets.

---

## File Structure

- Create `src/dashboard_view.py`: immutable presentation types, width/height budgeting, room priority, incident/event formatting, and file-detail adapter boundary.
- Create `src/dashboard_input.py`: thread-safe compact/expanded state and non-blocking Windows `R` key reader.
- Modify `src/dashboard_state.py`: persistent incident state, recovery lifecycle, structured/correlated event metadata, and snapshot fields.
- Rewrite dashboard portions of `src/cli_ui.py`: approved Rich hierarchy and plain renderer over `DashboardView`.
- Modify `main.py`: incident/event lifecycle wiring, terminal dimensions, view-mode wiring, key-reader startup/shutdown, and refresh wakeups.
- Modify `requirements.txt`: declare Rich consistently with `pyproject.toml`.
- Modify `tests/test_dashboard_state.py`: incident persistence/recovery and correlated event contracts.
- Create `tests/test_dashboard_view.py`: pure priority, budget, responsive, detail, and semantic formatting tests.
- Create `tests/test_dashboard_input.py`: interaction and reader lifecycle tests.
- Rewrite obsolete layout assertions in `tests/test_cli_ui.py` for the approved interface.
- Modify `tests/runtime/test_main_runtime_wiring.py`: key reader, incident lifecycle, and shared presentation-model wiring.

### Task 1: Add Persistent Attention State

**Files:**
- Modify: `src/dashboard_state.py`
- Test: `tests/test_dashboard_state.py`

- [ ] **Step 1: Write failing tests for automatic, actionable, and recovered incidents**

Add tests using the existing configured store:

```python
from src.dashboard_state import AttentionDisposition


def test_incident_stays_active_until_explicitly_cleared():
    store = configured_store()
    store.report_incident(
        ROOM_ID,
        "recording-connection",
        "录制连接中断",
        disposition=AttentionDisposition.AUTOMATIC,
        at=STARTED_AT,
        retry_attempt=2,
        retry_limit=5,
        next_retry_at=NOW,
    )

    incident = store.snapshot(now=NOW).incidents[0]
    assert incident.disposition is AttentionDisposition.AUTOMATIC
    assert incident.occurrences == 1
    assert incident.retry_attempt == 2

    store.clear_incident(ROOM_ID, "recording-connection", at=NOW)
    assert store.snapshot(now=NOW).incidents == ()


def test_repeated_incident_updates_one_entry_and_can_escalate():
    store = configured_store()
    store.report_incident(
        ROOM_ID,
        "recording-connection",
        "连接中断",
        disposition=AttentionDisposition.AUTOMATIC,
        at=STARTED_AT,
    )
    store.report_incident(
        ROOM_ID,
        "recording-connection",
        "重试耗尽",
        disposition=AttentionDisposition.ACTION_REQUIRED,
        at=NOW,
    )

    incident = store.snapshot(now=NOW).incidents[0]
    assert incident.disposition is AttentionDisposition.ACTION_REQUIRED
    assert incident.occurrences == 2
    assert incident.started_at == STARTED_AT
    assert incident.updated_at == NOW
```

- [ ] **Step 2: Run the focused tests and verify RED**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_dashboard_state.py -q
```

Expected: import/attribute failures because incident types and methods do not exist.

- [ ] **Step 3: Add the immutable incident contract and mutable storage**

Add public types:

```python
class AttentionDisposition(StrEnum):
    AUTOMATIC = "自动恢复"
    ACTION_REQUIRED = "需要处理"


@dataclass(frozen=True, slots=True)
class DashboardIncident:
    room_id: str
    incident_id: str
    message: str
    disposition: AttentionDisposition
    started_at: datetime
    updated_at: datetime
    occurrences: int = 1
    retry_attempt: int | None = None
    retry_limit: int | None = None
    next_retry_at: datetime | None = None
```

Store incidents by `(room_id, incident_id)`. `report_incident()` preserves `started_at`, increments occurrences, and replaces current message/disposition/retry metadata. `clear_incident()` returns the cleared incident or `None`. Add `incidents: tuple[DashboardIncident, ...]` to `DashboardSnapshot`, ordered action-required first and then by latest update.

- [ ] **Step 4: Make room recovery clear retry incidents explicitly**

Do not silently clear every incident from generic status changes. Add:

```python
def clear_room_incidents(
    self,
    room_id: str,
    *,
    incident_ids: tuple[str, ...] | None = None,
    at: datetime | None = None,
) -> tuple[DashboardIncident, ...]:
    timestamp = at or datetime.now().astimezone()
    with self._lock:
        keys = [
            key
            for key in self._incidents
            if key[0] == room_id and (incident_ids is None or key[1] in incident_ids)
        ]
        cleared = tuple(self._incidents.pop(key) for key in keys)
        for incident in cleared:
            self._events.append(
                DashboardEvent(
                    room_id=room_id,
                    event_type="incident_recovered",
                    message=f"{incident.message} · 已恢复",
                    at=timestamp,
                    correlation_id=f"incident:{room_id}:{incident.incident_id}",
                )
            )
        return cleared
```

Use `incident_ids=None` only at an explicit successful probe/recording boundary, not inside `snapshot()` or rendering.

- [ ] **Step 5: Verify the state tests are GREEN**

Run the Step 2 command. Expected: all dashboard-state tests pass.

### Task 2: Add Structured Semantic Event Correlation

**Files:**
- Modify: `src/dashboard_state.py`
- Test: `tests/test_dashboard_state.py`

- [ ] **Step 1: Write failing tests for correlation updates and recovery events**

```python
def test_correlated_recording_lifecycle_updates_one_semantic_event():
    store = configured_store()
    store.add_event(
        ROOM_ID,
        "recording_finished",
        "直播结束 · 等待转码",
        at=STARTED_AT,
        correlation_id="recording-42",
        details={"duration": "01:18:42", "size": "3.6 GB"},
    )
    store.add_event(
        ROOM_ID,
        "conversion_finished",
        "录制完成并转为 MP4",
        at=NOW,
        correlation_id="recording-42",
        details={"duration": "01:18:42", "size": "3.6 GB", "format": "MP4"},
    )

    events = store.snapshot(now=NOW).events
    assert len(events) == 1
    assert events[0].event_type == "conversion_finished"
    assert events[0].correlation_id == "recording-42"
    assert dict(events[0].details)["format"] == "MP4"


def test_clearing_incident_can_emit_one_recovery_event():
    store = configured_store()
    store.report_incident(
        ROOM_ID,
        "probe",
        "探测失败",
        disposition=AttentionDisposition.AUTOMATIC,
        at=STARTED_AT,
    )
    assert store.clear_incident(ROOM_ID, "probe", at=NOW, recovery_message="连接已恢复") is not None
    assert [event.message for event in store.snapshot(now=NOW).events] == ["连接已恢复"]
```

- [ ] **Step 2: Run the focused tests and verify RED**

Run the dashboard-state test command. Expected: `add_event()` rejects `correlation_id/details`, and `clear_incident()` rejects `recovery_message`.

- [ ] **Step 3: Extend the event contract without message parsing**

Extend `DashboardEvent`:

```python
@dataclass(frozen=True, slots=True)
class DashboardEvent:
    room_id: str
    event_type: str
    message: str
    at: datetime
    occurrences: int = 1
    correlation_id: str | None = None
    details: tuple[tuple[str, str], ...] = ()
```

Change `add_event()` to normalize `details` into a sorted tuple. If `correlation_id` is present, replace the existing correlated entry and move it to newest position. If absent, retain existing duplicate-message behavior. Replace the existing three-event retention limit with a fixed 50-event in-memory limit so the presentation layer can honestly select 3–10 visible rows.

- [ ] **Step 4: Emit recovery through the state boundary**

Allow `clear_incident` to accept a `recovery_message` keyword and append exactly one `incident_recovered` event only when an active incident was actually removed. A second clear is a no-op and emits nothing.

- [ ] **Step 5: Verify semantic state tests are GREEN**

Run `tests/test_dashboard_state.py`. Expected: all tests pass, including prior duplicate-event behavior.

### Task 3: Build the Rich-Independent Presentation Model

**Files:**
- Create: `src/dashboard_view.py`
- Create: `tests/test_dashboard_view.py`

- [ ] **Step 1: Write failing tests for width modes and room priority**

Define the wished-for API in tests:

```python
from src.dashboard_view import RoomListMode, ViewWidth, build_dashboard_view


@pytest.mark.parametrize(
    ("width", "expected"),
    [(79, ViewWidth.NARROW), (80, ViewWidth.MEDIUM), (119, ViewWidth.MEDIUM), (120, ViewWidth.WIDE)],
)
def test_width_boundaries(width, expected, snapshot):
    view = build_dashboard_view(snapshot, width=width, height=40, room_mode=RoomListMode.COMPACT)
    assert view.width_mode is expected


def test_compact_rooms_prioritize_attention_then_active_statuses(snapshot):
    view = build_dashboard_view(snapshot, width=140, height=28, room_mode=RoomListMode.COMPACT)
    assert [row.status for row in view.rooms[:3]] == ["需要处理", "自动恢复", "录制"]
    assert view.hidden_room_count > 0
```

- [ ] **Step 2: Run the new file and verify RED**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_dashboard_view.py -q
```

Expected: import failure because `src.dashboard_view` does not exist.

- [ ] **Step 3: Implement the immutable view contracts and width classification**

Create focused frozen dataclasses:

```python
class ViewWidth(StrEnum):
    NARROW = "narrow"
    MEDIUM = "medium"
    WIDE = "wide"


class RoomListMode(StrEnum):
    COMPACT = "compact"
    EXPANDED = "expanded"


@dataclass(frozen=True, slots=True)
class DashboardView:
    width_mode: ViewWidth
    title: str
    phase: str
    current_time: str
    uptime: str
    metrics: tuple[MetricView, ...]
    health: tuple[HealthView, ...]
    config_items: tuple[str, ...]
    save_path: str
    rooms: tuple[RoomRowView, ...]
    hidden_room_count: int
    incidents: tuple[IncidentRowView, ...]
    events: tuple[EventRowView, ...]
    hidden_event_count: int
    first_sweep: str | None
    complete_prompt: str | None
```

Implement only classification, labels, counts, and priority order in this step. Use original room index as the stable final tie-breaker.

- [ ] **Step 4: Write failing tests for height budgets**

Add tests proving:

- all attention rows are included;
- at least three events remain when three exist;
- compact mode shows fewer normal rooms than expanded mode;
- expanded mode shows all rooms when they fit;
- both modes expose exact hidden counts when they do not fit.

Use a deterministic budget helper:

```python
budget = allocate_rows(
    height=32,
    incident_count=2,
    room_count=15,
    event_count=8,
    room_mode=RoomListMode.COMPACT,
)
assert budget.event_rows >= 3
assert budget.incident_rows == 2
```

- [ ] **Step 5: Implement row allocation minimally**

Reserve fixed lines for header/configuration/panel headers and current incidents, then allocate the remaining lines in approved priority order. `EXPANDED` consumes spare lines for rooms before additional events; `COMPACT` limits normal rooms and gives spare lines to events up to ten. When physical height cannot meet all minima, never remove incident rows.

- [ ] **Step 6: Write failing tests for semantic formatting and safe file detail**

Cover:

- `需要处理` and `自动恢复` rows;
- retry `2/5`, next-at countdown, and incident duration;
- correlated conversion success and failure detail;
- missing output files;
- segmented file size/bitrate through an injected `recording_stats` callable;
- hidden-event counts and newest-first ordering.

- [ ] **Step 7: Implement formatting with an injected stats adapter**

Use:

```python
RecordingStatsReader = Callable[[DashboardRoom], RecordingStats | None]


def build_dashboard_view(
    snapshot: DashboardSnapshot,
    *,
    width: int,
    height: int,
    room_mode: RoomListMode,
    recording_stats: RecordingStatsReader = read_recording_stats,
) -> DashboardView:
    width_mode = classify_width(width)
    budget = allocate_rows(
        height=height,
        incident_count=len(snapshot.incidents),
        room_count=len(snapshot.rooms),
        event_count=len(snapshot.events),
        room_mode=room_mode,
    )
    incidents = build_incident_rows(snapshot, limit=budget.incident_rows)
    rooms = build_room_rows(snapshot, recording_stats=recording_stats)
    visible_rooms = rooms[: budget.room_rows]
    events = build_event_rows(snapshot)[: budget.event_rows]
    return DashboardView(
        width_mode=width_mode,
        title="DouyinLiveRecorder",
        phase=snapshot.phase.value,
        current_time=f"{snapshot.current_time:%Y-%m-%d %H:%M:%S}",
        uptime=format_uptime(snapshot),
        metrics=build_metrics(snapshot),
        health=build_health(snapshot),
        config_items=build_config_items(snapshot.config, width_mode),
        save_path=snapshot.config.save_path,
        rooms=visible_rooms,
        hidden_room_count=len(rooms) - len(visible_rooms),
        incidents=incidents,
        events=events,
        hidden_event_count=len(snapshot.events) - len(events),
        first_sweep=format_first_sweep(snapshot),
        complete_prompt=("按任意键退出 | Ctrl+C 强制退出" if snapshot.phase is AppDisplayPhase.COMPLETE else None),
    )
```

Catch `OSError` and per-room formatting exceptions at the adapter boundary and return safe detail text. Do not catch errors around the entire dashboard build.

- [ ] **Step 8: Verify the presentation tests are GREEN**

Run `tests/test_dashboard_view.py`. Expected: all pure model tests pass.

### Task 4: Add the Isolated `R` Key Controller

**Files:**
- Create: `src/dashboard_input.py`
- Create: `tests/test_dashboard_input.py`

- [ ] **Step 1: Write failing controller tests**

```python
from src.dashboard_input import DashboardInputController
from src.dashboard_view import RoomListMode


def test_r_toggles_room_mode_and_wakes_dashboard():
    wakes = []
    controller = DashboardInputController(on_change=lambda: wakes.append(True))
    assert controller.room_mode is RoomListMode.COMPACT
    assert controller.handle_key("r") is True
    assert controller.room_mode is RoomListMode.EXPANDED
    assert wakes == [True]
    assert controller.handle_key("R") is True
    assert controller.room_mode is RoomListMode.COMPACT


def test_other_keys_are_ignored_and_complete_phase_disables_toggle():
    controller = DashboardInputController(on_change=lambda: None)
    assert controller.handle_key("x") is False
    controller.disable()
    assert controller.handle_key("r") is False
    assert controller.room_mode is RoomListMode.COMPACT
```

- [ ] **Step 2: Run and verify RED**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_dashboard_input.py -q
```

Expected: module import failure.

- [ ] **Step 3: Implement the thread-safe controller**

Use an `RLock`; expose read-only `room_mode`; `handle_key()` toggles only for `r/R` while enabled and calls `on_change()` after releasing the lock.

- [ ] **Step 4: Write failing reader lifecycle tests**

Inject `is_interactive`, `key_available`, and `read_key` callables. Assert:

- non-interactive `start()` returns `False` and creates no thread;
- an available `r` reaches the controller;
- reader exceptions call `on_error` once and stop the reader;
- `stop()` joins promptly;
- `disable()` prevents further toggles before final any-key wait.

- [ ] **Step 5: Implement the Windows reader**

Provide:

```python
class DashboardKeyReader:
    def __init__(
        self,
        controller: DashboardInputController,
        *,
        platform_name: str = sys.platform,
        is_interactive: Callable[[], bool] = _stdin_is_interactive,
        key_available: Callable[[], bool] | None = None,
        read_key: Callable[[], str] | None = None,
        on_error: Callable[[Exception], None] | None = None,
    ) -> None:
        self._controller = controller
        self._platform_name = platform_name
        self._is_interactive = is_interactive
        self._key_available = key_available
        self._read_key = read_key
        self._on_error = on_error or (lambda _error: None)
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
```

On Windows, default to `msvcrt.kbhit`/`getwch`; otherwise `start()` returns `False`. Poll through `Event.wait(0.05)` so `stop()` is prompt. Never consume keys after `disable()`.

- [ ] **Step 6: Verify input tests are GREEN**

Run `tests/test_dashboard_input.py`. Expected: all tests pass without real console input.

### Task 5: Rewrite the Rich and Plain Renderers

**Files:**
- Modify: `src/cli_ui.py`
- Modify: `tests/test_cli_ui.py`

- [ ] **Step 1: Replace obsolete layout tests with failing approved-layout assertions**

Delete tests that inspect `_metric_card`, two event columns, or old renderable indexes. Add text/structure assertions for:

```python
view = build_dashboard_view(snapshot, width=140, height=42, room_mode=RoomListMode.COMPACT)
console.print(build_dashboard_renderable(view))
output = buffer.getvalue()

assert "DouyinLiveRecorder" in output
assert "运行正常" in output
assert "15 直播间" in output
assert "需处理" in output
assert "[R] 展开" in output
assert "运行动态" in output
assert "完整技术日志" in output
assert "最近事件" not in output
```

Add wide (140), medium (100), and narrow (72) cases. Verify medium has no standalone quality heading and narrow preserves full actionable incident text.

- [ ] **Step 2: Run UI tests and verify RED**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_cli_ui.py -q
```

Expected: signature and approved-label failures from the old renderer.

- [ ] **Step 3: Change renderers to accept `DashboardView`**

Use the exact public contracts `build_dashboard_renderable(view: DashboardView) -> Any` and `build_plain_dashboard(view: DashboardView) -> str`.

Build four stable regions: runtime header/metrics, compact configuration line, room panel, and runtime-activity panel. Use full-line color only for pinned incident rows; normal event rows color only the event label. Add the complete-phase prompt after activity.

- [ ] **Step 4: Implement responsive render functions**

Create four private focused functions with exact contracts: `_render_header(view: DashboardView) -> Any`, `_render_config(view: DashboardView) -> Any`, `_render_rooms(view: DashboardView) -> Any`, and `_render_activity(view: DashboardView) -> Any`.

Each branches only on `view.width_mode`; it does not reapply budgets or severity decisions. Narrow mode uses line-oriented rows with minimal borders.

- [ ] **Step 5: Update `RichDashboard.update()`**

Make it accept `DashboardView` and preserve the single `Live` instance, `screen=True`, `redirect_stdout=False`, `redirect_stderr=False`, explicit refresh, and existing stop behavior.

- [ ] **Step 6: Verify focused UI tests are GREEN**

Run `tests/test_cli_ui.py`. Expected: all new renderer tests pass and startup/FFmpeg/conversion helpers remain green.

### Task 6: Wire Presentation State, Incidents, Events, and Keyboard Input

**Files:**
- Modify: `main.py`
- Modify: `tests/runtime/test_main_runtime_wiring.py`
- Modify: `tests/test_dashboard_state.py`

- [ ] **Step 1: Write failing wiring assertions for one shared view build**

Assert the dashboard loop obtains both dimensions and one mode:

```python
view = build_dashboard_view(
    build_dashboard_snapshot(),
    width=dashboard.console.size.width,
    height=dashboard.console.size.height,
    room_mode=dashboard_input.room_mode,
)
dashboard.update(view)
```

Assert the plain path also calls `build_dashboard_view` before `build_plain_dashboard(view)`.

- [ ] **Step 2: Run wiring tests and verify RED**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\runtime\test_main_runtime_wiring.py -q
```

Expected: old snapshot-direct rendering remains.

- [ ] **Step 3: Wire the shared presentation model**

Instantiate `DashboardInputController(on_change=dashboard_refresh_event.set)` next to the dashboard store. Build a view on each refresh using current terminal width/height. For plain/non-interactive output, always pass `RoomListMode.COMPACT` and a conservative height.

- [ ] **Step 4: Write failing incident lifecycle wiring tests**

Verify source/callback behavior for all of these boundaries:

- room probe/recording retry -> `report_incident` with `AttentionDisposition.AUTOMATIC`;
- retry exhaustion -> `report_incident` with `AttentionDisposition.ACTION_REQUIRED`;
- successful probe/recording -> `clear_incident` with a recovery message;
- FFmpeg missing and disk threshold -> system action-required incidents;
- dashboard refresh event after incident changes.

- [ ] **Step 5: Implement explicit incident mapping**

Use stable IDs such as `probe`, `recording-connection`, `ffmpeg`, and `disk-space`. Do not derive IDs from exception messages. Preserve the existing numeric `error_count` for compatibility/diagnostics, but display current actionable incident count from the snapshot.

- [ ] **Step 6: Add recording correlation IDs at lifecycle boundaries**

Use the existing output path or recording start identity to create a stable per-recording correlation ID. Pass it through recording-finished, conversion-started, conversion-finished, and conversion-failed events, with normalized duration/size/format details available at those boundaries. Do not scan historical TS files.

- [ ] **Step 7: Write failing keyboard lifecycle wiring tests**

Assert:

- interactive Rich startup calls `DashboardKeyReader.start()`;
- dashboard teardown always calls `stop()`;
- before `wait_for_exit_key()`, controller/reader are disabled/stopped;
- non-Rich/plain path creates no reader;
- Ctrl+C handler order remains phase -> refresh -> any-key wait -> normal exit.

- [ ] **Step 8: Implement keyboard lifecycle wiring**

Start the reader only after Rich dashboard initialization. In `finally`, stop it before stopping the dashboard. On complete phase, disable and stop it before the existing any-key wait so no reader competes for the final key. Log reader errors through the existing technical logger and continue in compact mode.

- [ ] **Step 9: Verify state, input, UI, and wiring tests together**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_dashboard_state.py tests\test_dashboard_view.py tests\test_dashboard_input.py tests\test_cli_ui.py tests\runtime\test_main_runtime_wiring.py -q
```

Expected: all focused dashboard tests pass.

### Task 7: Remove the Old Dashboard and Reconcile Dependencies

**Files:**
- Modify: `src/cli_ui.py`
- Modify: `src/dashboard_state.py`
- Modify: `tests/test_cli_ui.py`
- Modify: `pyproject.toml` only if verification finds a declaration error
- Modify: `requirements.txt`

- [ ] **Step 1: Prove obsolete UI symbols are no longer referenced**

Run:

```powershell
rg -n "_metric_card|最近事件|event_lines|config_grid|build_dashboard_renderable\(snapshot" src tests main.py
```

Expected before cleanup: definitions or old assertions remain. Classify every match before removal.

- [ ] **Step 2: Delete obsolete renderer code and index-coupled tests**

Remove old metric-card, old configuration-card, two-column event-grid, snapshot-direct renderer, and duplicate plain-formatting code. Retain startup banner, FFmpeg summary, conversion progress, Rich availability, and single-Live lifecycle helpers if still referenced.

- [ ] **Step 3: Audit fields/imports before deleting them**

For every candidate old state field/helper, run `rg` across `src`, `main.py`, and tests. Delete it only when it is neither runtime input nor part of the new view. Keep `error_count` unless all non-UI compatibility/diagnostic uses are migrated and tested.

- [ ] **Step 4: Audit declared dependencies against runtime and dynamic imports**

Run targeted searches for every project dependency. Confirm `tqdm` remains used by `ffmpeg_install.py` and `src/initializer.py`; confirm Rich remains used by `src/cli_ui.py`. Do not remove transitive libraries such as `click` based on PyInstaller warning output.

- [ ] **Step 5: Synchronize requirements**

Add the missing direct declaration:

```text
rich>=15.0.0
```

to `requirements.txt`. Keep the matching `pyproject.toml` entry. Only remove another direct dependency if the Step 4 audit proves it unused across normal, installer, and packaging paths.

- [ ] **Step 6: Run focused cleanup verification**

Run the Step 1 search again. Expected: no obsolete implementation matches, except explicit negative assertions documenting absence if retained.

### Task 8: Full Verification and Packaged Smoke Test

**Files:**
- Verify only; do not overwrite existing packaged folders or user data.

- [ ] **Step 1: Run Ruff on changed source and tests**

```powershell
.\.venv\Scripts\python.exe -m ruff check src\dashboard_state.py src\dashboard_view.py src\dashboard_input.py src\cli_ui.py main.py tests\test_dashboard_state.py tests\test_dashboard_view.py tests\test_dashboard_input.py tests\test_cli_ui.py tests\runtime\test_main_runtime_wiring.py
```

Expected: exit code 0.

- [ ] **Step 2: Run the complete automated suite**

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

Expected: zero failures.

- [ ] **Step 3: Render deterministic terminal fixtures**

Render approved normal, recording, automatic recovery, human-action-required, conversion, and complete snapshots at:

```text
72x24, 100x32, 120x40, 160x50
```

Expected: no uncaught `NotRenderableError`, attention text remains visible, hidden counts are explicit, and each output includes at least three events when three exist.

- [ ] **Step 4: Exercise the key controller in an interactive source run**

Launch the recorder with test configuration, press `R` twice, and confirm compact -> maximum expanded -> compact without changing room statuses or interrupting refresh. Press unrelated keys and confirm no effect. Press Ctrl+C and confirm the existing graceful shutdown flow.

- [ ] **Step 5: Build with the existing PyInstaller specification**

```powershell
.\.venv\Scripts\pyinstaller.exe --noconfirm --clean DouyinLiveRecorder.spec
```

Expected: exit code 0 and `dist\DouyinLiveRecorder\DouyinLiveRecorder.exe` exists.

- [ ] **Step 6: Smoke-test the packaged executable safely**

Copy only non-sensitive test configuration into the new build. Verify monitoring, recording, one automatic retry/recovery, one simulated actionable incident, conversion completion, `R` toggling, and graceful shutdown. Inspect `logs\streamget.log` for unhandled exceptions. Do not copy cookies/tokens into test output and do not replace existing packaged folders until the build passes.

- [ ] **Step 7: Report evidence and remaining caveats**

Provide focused/full test counts, Ruff result, render dimensions checked, PyInstaller result, smoke scenarios completed, dependency changes, obsolete symbols removed, and the absolute executable path. Explicitly report any smoke scenario that could not be exercised rather than treating it as passed.
