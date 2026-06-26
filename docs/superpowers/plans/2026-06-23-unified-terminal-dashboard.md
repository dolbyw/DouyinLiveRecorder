# Unified Terminal Dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace mixed Rich/print terminal output with one persistent dashboard that shows sanitized runtime configuration and every configured live room with an in-place status.

**Architecture:** Add a thread-safe, UI-specific dashboard state store that reconciles parsed room configuration and receives monitoring, recording, conversion, and retry events. Keep semantic state construction separate from Rich/plain rendering; `main.py` becomes the integration layer and routes high-frequency lifecycle output into the store instead of stdout.

**Tech Stack:** Python 3.11+, dataclasses, `threading.RLock`, Rich `Live`/`Table`/`Panel`, pytest, Ruff.

---

## File map

- Create `src/dashboard_state.py`: immutable dashboard models, thread-safe room/event store, status priority, event deduplication, sanitized configuration model.
- Modify `src/cli_ui.py`: render one compact dashboard from the new snapshot; provide Rich and plain-text renderers; enforce a single Live lifecycle.
- Modify `main.py`: initialize/reconcile dashboard state, route runtime callbacks to it, remove high-frequency prints, and feed one dashboard instance.
- Modify `tests/test_cli_ui.py`: layout, sensitive-data exclusion, narrow-terminal, and Live lifecycle tests.
- Create `tests/test_dashboard_state.py`: room reconciliation, lifecycle transitions, conversion progress, and event deduplication tests.
- Modify `tests/runtime/test_main_runtime_wiring.py`: assert main integration uses dashboard state callbacks and no progress print path.

### Task 1: Build the semantic dashboard state store

**Files:**
- Create: `tests/test_dashboard_state.py`
- Create: `src/dashboard_state.py`

- [ ] **Step 1: Write failing tests for reconciliation, ordering, and sanitized configuration**

```python
from datetime import UTC, datetime

from src.dashboard_state import DashboardConfig, DashboardStateStore, RoomDisplayStatus
from src.models import QualityLevel
from src.runtime import RoomSpec


def test_reconcile_lists_every_enabled_room_in_config_order():
    store = DashboardStateStore()
    rooms = (
        RoomSpec("https://live.douyin.com/1", QualityLevel.ORIGIN, "招财"),
        RoomSpec("https://www.bilibili.com/2", QualityLevel.HD, "小鹿"),
    )

    store.reconcile_rooms(rooms)
    snapshot = store.snapshot(now=datetime(2026, 6, 23, tzinfo=UTC))

    assert [room.name for room in snapshot.rooms] == ["招财", "小鹿"]
    assert [room.status for room in snapshot.rooms] == [
        RoomDisplayStatus.WAITING,
        RoomDisplayStatus.WAITING,
    ]


def test_dashboard_config_contains_only_operational_fields():
    config = DashboardConfig(
        save_format="TS", quality="原画", split_seconds=1800,
        poll_seconds=300, max_requests=3, use_proxy=True,
        convert_to_mp4=True, save_path="D:/downloads", disk_free_gb=463.9,
    )

    assert "cookie" not in repr(config).lower()
    assert "token" not in repr(config).lower()
    assert "password" not in repr(config).lower()
```

- [ ] **Step 2: Run tests and verify RED**

Run: `uv run pytest tests/test_dashboard_state.py -v`

Expected: collection fails because `src.dashboard_state` does not exist.

- [ ] **Step 3: Implement immutable models and room reconciliation**

```python
class RoomDisplayStatus(StrEnum):
    WAITING = "等待监控"
    MONITORING = "监控中"
    RECORDING = "录制中"
    CONVERTING = "转码中"
    RETRYING = "重试中"
    DISABLED = "已停用"


@dataclass(frozen=True, slots=True)
class DashboardConfig:
    save_format: str
    quality: str
    split_seconds: int | None
    poll_seconds: int
    max_requests: int
    use_proxy: bool
    convert_to_mp4: bool
    save_path: str
    disk_free_gb: float | None
```

Implement `DashboardStateStore.reconcile_rooms()` with an `RLock`, preserving incoming order and updating existing room names/quality without duplicating URLs. Implement `snapshot(now=...)` as an immutable detached value.

- [ ] **Step 4: Run the focused tests and verify GREEN**

Run: `uv run pytest tests/test_dashboard_state.py -v`

Expected: all current tests pass.

- [ ] **Step 5: Write failing lifecycle and event-deduplication tests**

```python
def test_room_lifecycle_uses_strongest_active_status():
    store = configured_store()
    store.mark_monitoring(ROOM_ID)
    store.mark_recording(ROOM_ID, "序号1 招财", "原画", STARTED_AT)
    store.mark_converting(ROOM_ID, "招财_000.ts", 47.4, 72, 152)

    room = store.snapshot(now=NOW).rooms[0]
    assert room.status is RoomDisplayStatus.CONVERTING
    assert room.progress_percent == 47.4


def test_duplicate_events_update_one_entry_and_keep_three_most_recent():
    store = configured_store()
    store.add_event(ROOM_ID, "recording_started", "开始录制", at=STARTED_AT)
    store.add_event(ROOM_ID, "recording_started", "开始录制", at=NOW)

    assert len(store.snapshot(now=NOW).events) == 1
    assert store.snapshot(now=NOW).events[0].occurrences == 2
```

- [ ] **Step 6: Run lifecycle tests and verify RED**

Run: `uv run pytest tests/test_dashboard_state.py -v`

Expected: failures report missing lifecycle/event methods.

- [ ] **Step 7: Implement lifecycle methods and bounded events**

Implement `mark_monitoring`, `mark_recording`, `mark_converting`, `mark_retrying`, `mark_recording_finished`, `mark_conversion_finished`, and `mark_disabled`. Store timestamps as timezone-aware datetimes. Deduplicate events by `(room_id, event_type, normalized_message)`, increment `occurrences`, replace the timestamp, and retain only the newest three entries.

- [ ] **Step 8: Run focused tests and Ruff**

Run: `uv run pytest tests/test_dashboard_state.py -v && uv run ruff check src/dashboard_state.py tests/test_dashboard_state.py`

Expected: PASS with no Ruff diagnostics.

### Task 2: Replace the current two-panel renderer with the approved one-screen layout

**Files:**
- Modify: `tests/test_cli_ui.py`
- Modify: `src/cli_ui.py`

- [ ] **Step 1: Replace the existing dashboard test with failing layout assertions**

```python
def test_dashboard_contains_summary_config_all_rooms_and_events():
    snapshot = dashboard_snapshot_with_monitoring_recording_and_conversion()
    console = Console(file=buffer, force_terminal=False, width=120)

    console.print(build_dashboard_renderable(snapshot))
    output = buffer.getvalue()

    assert "直播间 3" in output
    assert "录制 1" in output
    assert "监控 1" in output
    assert "招财" in output and "监控中" in output
    assert "嘉嘉" in output and "录制中" in output
    assert "小鹿" in output and "转码中" in output
    assert "关键配置" in output and "最近事件" in output
```

Add a second test that renders at width 72 and asserts core columns remain present. Add a third test that constructs only `DashboardConfig` and verifies strings such as `cookie`, `token`, and `密码` never appear.

- [ ] **Step 2: Run the renderer tests and verify RED**

Run: `uv run pytest tests/test_cli_ui.py -v`

Expected: failures because the old snapshot and two-panel layout are still used.

- [ ] **Step 3: Implement the approved A layout**

Change `build_dashboard_renderable()` to return one outer panel containing:

```python
Group(
    health_line,
    summary_grid,
    Panel(config_grid, title="关键配置", padding=(0, 1)),
    room_table,
    Panel(event_lines, title="最近事件", padding=(0, 1)),
)
```

Use status colors: waiting dim, monitoring green, recording bold red, converting magenta, retrying yellow, disabled dim. Keep `直播间`, `状态`, `质量`, and `时长/进度` visible at narrow widths; omit or truncate the detail column when `console.size.width < 90`.

- [ ] **Step 4: Add a plain-text renderer using the same snapshot**

Implement:

```python
def build_plain_dashboard(snapshot: DashboardSnapshot, *, width: int = 100) -> str:
    ...
```

The output must contain the same room names/statuses and sanitized config fields, with long values truncated by a shared helper.

- [ ] **Step 5: Verify renderer tests and lint**

Run: `uv run pytest tests/test_cli_ui.py -v && uv run ruff check src/cli_ui.py tests/test_cli_ui.py`

Expected: PASS with no Ruff diagnostics.

### Task 3: Guarantee one Rich Live lifecycle and prevent redirected print duplication

**Files:**
- Modify: `tests/test_cli_ui.py`
- Modify: `src/cli_ui.py`

- [ ] **Step 1: Write a failing lifecycle test**

```python
def test_dashboard_updates_one_live_instance_without_redirecting_streams(monkeypatch):
    created = []
    monkeypatch.setattr(cli_ui, "Live", fake_live_factory(created))

    dashboard = RichDashboard(console=console)
    dashboard.start()
    dashboard.update(snapshot_one)
    dashboard.update(snapshot_two)
    dashboard.stop()

    assert len(created) == 1
    assert created[0].redirect_stdout is False
    assert created[0].redirect_stderr is False
    assert created[0].update_count == 2
```

- [ ] **Step 2: Run and verify RED**

Run: `uv run pytest tests/test_cli_ui.py::test_dashboard_updates_one_live_instance_without_redirecting_streams -v`

Expected: FAIL because current Live enables both redirects.

- [ ] **Step 3: Implement single-instance ownership**

Set `redirect_stdout=False`, `redirect_stderr=False`, and make `start`, `update`, and `stop` idempotent. Add a lock around lifecycle calls so the display thread cannot create or stop two Live instances concurrently. Do not construct a replacement Live after a render exception; return control to the caller for one-way plain-text fallback.

- [ ] **Step 4: Run the CLI test suite**

Run: `uv run pytest tests/test_cli_ui.py -v`

Expected: PASS.

### Task 4: Wire all configured rooms and runtime state into the dashboard

**Files:**
- Modify: `tests/runtime/test_main_runtime_wiring.py`
- Modify: `main.py`

- [ ] **Step 1: Write failing wiring assertions**

```python
def test_main_reconciles_all_configured_rooms_into_dashboard_store():
    source = MAIN_PATH.read_text(encoding="utf-8")
    assert "dashboard_store.reconcile_rooms" in source
    assert "parse_room_config_lines" in source


def test_main_routes_lifecycle_callbacks_to_dashboard_store():
    source = MAIN_PATH.read_text(encoding="utf-8")
    assert "dashboard_store.mark_recording" in source
    assert "dashboard_store.mark_converting" in source
    assert "dashboard_store.mark_recording_finished" in source
```

- [ ] **Step 2: Run and verify RED**

Run: `uv run pytest tests/runtime/test_main_runtime_wiring.py -v`

Expected: the new source-contract assertions fail.

- [ ] **Step 3: Initialize and reconcile the dashboard store**

Create one module-level `DashboardStateStore`. In `load_async_runtime_config()`, reconcile the entire parsed `desired_rooms` tuple before platform filtering, so every valid configured room appears even if its platform has no registered async resolver. Populate `DashboardConfig` from the already-loaded typed application configuration and disk-capacity result.

- [ ] **Step 4: Merge runtime observations into display state**

When building the dashboard snapshot, merge `StateStore.snapshot()` observations by room ID:

```python
for status in runtime_snapshot.statuses:
    if status.stop_requested:
        dashboard_store.mark_disabled(status.room_id)
    elif status.recording_name:
        dashboard_store.mark_recording(...)
    elif status.last_error:
        dashboard_store.mark_retrying(...)
    elif status.monitoring:
        dashboard_store.mark_monitoring(status.room_id)
```

Return only `dashboard_store.snapshot(...)` to both Rich and plain renderers.

- [ ] **Step 5: Run focused wiring and state tests**

Run: `uv run pytest tests/runtime/test_main_runtime_wiring.py tests/test_dashboard_state.py -v`

Expected: PASS.

### Task 5: Route recording and conversion lifecycle output into room rows

**Files:**
- Modify: `tests/runtime/test_main_runtime_wiring.py`
- Modify: `main.py`

- [ ] **Step 1: Add failing source-contract tests for removed progress printing**

```python
def test_conversion_progress_updates_dashboard_instead_of_printing():
    source = MAIN_PATH.read_text(encoding="utf-8")
    assert "dashboard_store.mark_converting" in source
    assert "print(format_conversion_progress" not in source
```

Also assert the strings `等待直播`, `准备开始录制`, `直播录制完成`, and `检测直播间中` are not passed to `print` in the recording loop.

- [ ] **Step 2: Run and verify RED**

Run: `uv run pytest tests/runtime/test_main_runtime_wiring.py -v`

Expected: FAIL on the existing print calls.

- [ ] **Step 3: Pass room identity through progress callbacks**

Change `make_conversion_progress_callback(index, total)` to accept `room_id` and update:

```python
dashboard_store.mark_converting(
    room_id,
    progress.source.name,
    progress.percent,
    progress.elapsed,
    progress.duration,
)
```

On `progress.finished`, mark conversion complete and add one `conversion_finished` event.

- [ ] **Step 4: Replace high-frequency lifecycle prints**

In `on_pipeline_start`, mark the room recording and add one `recording_started` event. In `on_finish`, clear the recording state only when no conversion remains. Replace completion/error prints with a bounded event or retry state. Remove loop countdown, detection, waiting, and raw progress prints; retain detailed file paths and exceptions in the Loguru file logger.

- [ ] **Step 5: Verify focused tests**

Run: `uv run pytest tests/runtime/test_main_runtime_wiring.py tests/test_cli_ui.py tests/test_dashboard_state.py -v`

Expected: PASS.

### Task 6: Replace duplicate plain display logic and perform full verification

**Files:**
- Modify: `main.py`
- Modify: `tests/runtime/test_main_runtime_wiring.py`

- [ ] **Step 1: Write a failing fallback wiring test**

```python
def test_plain_and_rich_display_use_the_same_snapshot():
    source = MAIN_PATH.read_text(encoding="utf-8")
    assert "build_plain_dashboard(snapshot" in source
    assert "build_dashboard_snapshot" not in source
```

- [ ] **Step 2: Run and verify RED**

Run: `uv run pytest tests/runtime/test_main_runtime_wiring.py -v`

Expected: FAIL because `_display_info_plain` manually reconstructs the old summary.

- [ ] **Step 3: Make the display loop snapshot-driven**

Both paths call `dashboard_store.snapshot()` once per refresh. Rich updates once per second. Plain mode clears and prints `build_plain_dashboard(snapshot)` at a slower interval. On a Rich render failure, stop the single Live instance once and permanently enter plain mode.

- [ ] **Step 4: Run all automated checks**

Run: `uv run pytest -q`

Expected: all tests pass.

Run: `uv run ruff check src tests main.py`

Expected: no diagnostics introduced by changed files. If unrelated pre-existing diagnostics exist, record them separately and verify changed files directly.

- [ ] **Step 5: Render deterministic wide and narrow snapshots for visual QA**

Run a small test helper with Rich `Console(record=True, width=120)` and `width=72`, export the text, and verify:

- one dashboard header only;
- every configured room appears exactly once;
- room statuses are distinguishable;
- no credentials appear;
- long names/paths do not break borders.

- [ ] **Step 6: Perform a bounded live smoke test**

Run the application with two safe test room entries long enough to observe one monitoring cycle and, when available, one recording/conversion transition. Confirm the terminal retains one panel and the corresponding row changes in place. Stop gracefully and verify the final log contains details omitted from the UI.

Because this workspace is not a Git repository, omit commit steps and report that constraint in the handoff.
