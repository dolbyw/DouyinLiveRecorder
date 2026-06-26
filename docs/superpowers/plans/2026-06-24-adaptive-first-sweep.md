# Adaptive First Sweep Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Check all configured rooms promptly at startup using a 15-second target window and a one-second safety floor, then automatically resume the normal evenly paced polling cycle while showing honest first-sweep progress in the terminal dashboard.

**Architecture:** Extend the shared `RequestPacer` into a room-aware two-phase pacer that distinguishes a room's first permit from later permits. Keep request-return progress in `DashboardStateStore`, driven by explicit monitor lifecycle callbacks, so slow or failed probes cannot be reported as complete. Apply the same first-start spacing formula to legacy threads without changing their long-term polling behavior.

**Tech Stack:** Python 3.11+, asyncio, dataclasses, Rich terminal UI, pytest/pytest-asyncio, PyInstaller.

**Repository note:** This workspace has no `.git` directory. Commit steps are intentionally replaced by verification checkpoints; no synthetic Git repository should be created.

---

## File Structure

- Modify `src/runtime/pacer.py`: first-sweep spacing calculation, room-aware permit state, immutable progress snapshot.
- Modify `src/runtime/coordinator.py`: configure the pacer with stable room IDs and first-sweep policy.
- Modify `src/runtime/monitor.py`: pass room IDs to pacing and emit probe-start/probe-finish callbacks.
- Modify `src/runtime/__init__.py`: export new pacing/progress types and helper.
- Modify `src/dashboard_state.py`: store initial probe lifecycle and expose honest progress in snapshots.
- Modify `src/cli_ui.py`: render first-sweep progress and per-room first-probe wording.
- Modify `main.py`: wire callbacks, first-sweep completion event, and legacy first-start spacing.
- Modify focused tests under `tests/runtime/`, `tests/test_dashboard_state.py`, `tests/test_cli_ui.py`, and `tests/runtime/test_main_runtime_wiring.py`.

### Task 1: Implement the Room-Aware Two-Phase Pacing Policy

**Files:**
- Modify: `src/runtime/pacer.py`
- Modify: `src/runtime/__init__.py`
- Test: `tests/runtime/test_pacer.py`

- [ ] **Step 1: Write failing tests for the adaptive spacing formula**

Add parameterized assertions equivalent to:

```python
@pytest.mark.parametrize(
    ("room_count", "expected"),
    [(5, 3.0), (15, 1.0), (30, 1.0), (100, 1.0)],
)
def test_first_sweep_spacing_targets_fifteen_seconds_with_safety_floor(room_count, expected):
    assert calculate_first_sweep_spacing(15, room_count, minimum_seconds=1) == expected
```

- [ ] **Step 2: Run the formula test and verify RED**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\runtime\test_pacer.py -q
```

Expected: collection/import failure because `calculate_first_sweep_spacing` does not exist.

- [ ] **Step 3: Implement the pure spacing helper**

Add:

```python
def calculate_first_sweep_spacing(
    target_window_seconds: float,
    room_count: int,
    *,
    minimum_seconds: float = 1.0,
) -> float:
    if target_window_seconds <= 0:
        raise ValueError("first sweep target window must be greater than zero")
    if minimum_seconds < 0:
        raise ValueError("first sweep minimum spacing cannot be negative")
    return max(minimum_seconds, target_window_seconds / max(1, room_count))
```

Export it from `src/runtime/__init__.py`.

- [ ] **Step 4: Verify the formula tests are GREEN**

Run the focused command from Step 2. Expected: all pacing tests pass.

- [ ] **Step 5: Write failing tests for first-to-steady transition and stable reconfiguration**

Add tests that configure IDs `room-1` through `room-15`, call `wait_turn(room_id)` once for each, and assert starts `0..14`; call `wait_turn("room-1")` again and assert the next delay is `300 / 15`. Add a reconfiguration test proving unchanged room IDs are not reset, a newly added ID receives a fast permit, and a removed ID disappears from progress.

Use a frozen progress contract:

```python
@dataclass(frozen=True, slots=True)
class FirstSweepProgress:
    total: int
    issued: int

    @property
    def permits_complete(self) -> bool:
        return self.issued >= self.total
```

- [ ] **Step 6: Run the new stateful tests and verify RED**

Expected: `configure()` rejects `room_ids` and `wait_turn()` rejects `room_id`.

- [ ] **Step 7: Implement room-aware pacing minimally**

Change the public contract to:

```python
async def configure(
    self,
    *,
    window_seconds: float,
    room_ids: Iterable[str],
    first_sweep_target_seconds: float = 15.0,
    first_sweep_minimum_seconds: float = 1.0,
) -> None: ...

async def wait_turn(self, room_id: str) -> float: ...
```

Inside the existing lock, retain a `_seen_room_ids` set across reconfiguration, intersect it with current IDs, calculate first and steady spacing, and select first spacing only when `room_id` is unseen. Mark a room seen when its permit is issued, not when its network request succeeds. Preserve `_next_allowed` so configuration refresh cannot release a burst.

- [ ] **Step 8: Run pacing tests and verify GREEN**

Run `tests/runtime/test_pacer.py`. Expected: all tests pass without real sleeps.

### Task 2: Propagate Room IDs Through Coordinator and Monitor

**Files:**
- Modify: `src/runtime/coordinator.py`
- Modify: `src/runtime/monitor.py`
- Test: `tests/runtime/test_coordinator.py`
- Test: `tests/runtime/test_monitor.py`

- [ ] **Step 1: Write failing coordinator and monitor contract tests**

Update the capturing pacer to expect:

```python
await pacer.configure(
    window_seconds=300,
    room_ids=tuple(room.room_id for room in rooms),
    first_sweep_target_seconds=15,
    first_sweep_minimum_seconds=1,
)
```

Update the monitor pacing test so its fake defines `wait_turn(room_id)` and asserts the real room ID is received before the limiter becomes active.

- [ ] **Step 2: Run both focused files and verify RED**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\runtime\test_coordinator.py tests\runtime\test_monitor.py -q
```

Expected: signature/assertion failures from the old count-only API.

- [ ] **Step 3: Implement coordinator and monitor propagation**

Give `RuntimeCoordinator` constructor defaults `first_sweep_target_seconds=15.0` and `first_sweep_minimum_seconds=1.0`. During refresh, pass the ordered room IDs to the pacer. Change `RoomMonitor.run_once()` to call `await self._pacer.wait_turn(room.room_id)`.

- [ ] **Step 4: Verify focused tests are GREEN**

Run the Step 2 command. Expected: all coordinator and monitor tests pass.

### Task 3: Track Probe Start and Probe Return Honestly

**Files:**
- Modify: `src/runtime/monitor.py`
- Modify: `src/dashboard_state.py`
- Test: `tests/runtime/test_monitor.py`
- Test: `tests/test_dashboard_state.py`

- [ ] **Step 1: Write failing dashboard lifecycle tests**

Specify snapshot fields:

```python
first_sweep_total: int
first_sweep_started: int
first_sweep_completed: int
first_sweep_started_at: datetime | None
first_sweep_completed_at: datetime | None
```

Add tests proving `reconcile_rooms()` initializes totals, `mark_initial_probe_started(room_id)` changes a waiting row to a probing state, `mark_initial_probe_finished(room_id)` increments completion once, failures also count as returned, and deleting a pending room updates the denominator without duplicating completion.

- [ ] **Step 2: Run dashboard state tests and verify RED**

Expected: missing enum values, fields, and lifecycle methods.

- [ ] **Step 3: Implement dashboard first-probe state**

Add `RoomDisplayStatus.PROBING = "首次检测"`; add per-room booleans `initial_probe_started` and `initial_probe_completed`; derive aggregate counts while creating `DashboardSnapshot`. Make lifecycle methods idempotent. Record completion time only when a non-empty startup cohort has all returned; dynamic additions after startup completion do not erase the original completion timestamp.

- [ ] **Step 4: Write failing monitor callback tests**

Add async callbacks and assert this sequence around a successful probe:

```text
pace → initial_started → limiter/probe → initial_finished
```

Add a probe that raises and assert `initial_finished` still runs from `finally`, while the original exception propagates to `RuntimeScheduler`.

- [ ] **Step 5: Run callback tests and verify RED**

Expected: `RoomMonitor` does not accept the lifecycle callbacks.

- [ ] **Step 6: Implement monitor lifecycle callbacks**

Add optional async callbacks:

```python
ProbeLifecycleCallback = Callable[[RoomSpec], Awaitable[None]]
```

After pacing and before limiter acquisition, call `on_probe_started`; wrap only the probe execution in `try/finally` and call `on_probe_finished` in `finally`. Dashboard methods remain idempotent, so later polling cycles do not alter first-sweep counts.

- [ ] **Step 7: Verify state and monitor tests are GREEN**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_dashboard_state.py tests\runtime\test_monitor.py -q
```

Expected: all focused tests pass.

### Task 4: Render Useful First-Sweep Feedback

**Files:**
- Modify: `src/cli_ui.py`
- Test: `tests/test_cli_ui.py`

- [ ] **Step 1: Write failing plain and Rich dashboard rendering tests**

Create snapshots representing `6/15` returned with one row waiting and one probing. Assert rendered text includes `首次巡检 6/15`, `等待首次检测`, and `正在首次检测`. Add a completed snapshot assertion that normal next-check detail returns after the sweep.

- [ ] **Step 2: Run UI tests and verify RED**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_cli_ui.py -q
```

Expected: new progress wording is absent.

- [ ] **Step 3: Implement compact progress rendering**

Render `首次巡检 completed/total` in the configuration/summary area only while the startup cohort is incomplete. In row details, map waiting and probing states to explicit first-probe wording. Keep the existing status colors, table density, recording progress, and post-sweep countdown unchanged.

- [ ] **Step 4: Verify UI tests are GREEN**

Run the Step 2 command. Expected: all UI tests pass.

### Task 5: Wire Runtime Callbacks and One Completion Event

**Files:**
- Modify: `main.py`
- Test: `tests/runtime/test_main_runtime_wiring.py`
- Test: `tests/test_dashboard_state.py`

- [ ] **Step 1: Write failing wiring and event idempotency tests**

Assert `build_async_runtime_runner()` passes callbacks that call `dashboard_store.mark_initial_probe_started` and `mark_initial_probe_finished`. Add a store-level method or main-level helper test proving exactly one `first_sweep_completed` event is emitted when startup completion changes from false to true, with elapsed time formatted to one decimal place.

- [ ] **Step 2: Run focused tests and verify RED**

Expected: callback wiring and completion-event helper are absent.

- [ ] **Step 3: Implement runtime wiring**

Create async callbacks in `build_async_runtime_runner()` that update the dashboard store and trigger `dashboard_refresh_event`. On the first transition to complete, add:

```python
dashboard_store.add_event(
    "system",
    "first_sweep_completed",
    f"首次巡检完成：{total} 个房间，用时 {elapsed:.1f} 秒",
)
```

Do not emit this event for zero rooms or dynamic additions after the startup cohort completed.

- [ ] **Step 4: Verify focused tests are GREEN**

Run the Step 2 files. Expected: all tests pass.

### Task 6: Apply Safe Adaptive Startup to Legacy Threads

**Files:**
- Modify: `main.py`
- Modify: `src/runtime/pacer.py`
- Test: `tests/runtime/test_pacer.py`
- Test: `tests/runtime/test_main_runtime_wiring.py`

- [ ] **Step 1: Write failing legacy spacing tests**

Specify:

```python
def calculate_legacy_first_start_spacing(room_count: int, configured_seconds: float) -> float:
    adaptive = calculate_first_sweep_spacing(15, room_count, minimum_seconds=1)
    return max(configured_seconds, adaptive)
```

Assert 15 rooms and configured `0` yields `1`, while configured `5` yields `5`. Add a main wiring assertion that compatibility candidates use this helper instead of `calculate_start_spacing(delay_default, ...)`.

- [ ] **Step 2: Run tests and verify RED**

Expected: helper is absent and main still spreads initial threads over 300 seconds.

- [ ] **Step 3: Implement and wire the legacy helper**

Keep `calculate_start_spacing` for backward compatibility, add/export the dedicated first-start helper, and update only compatibility thread startup. Do not change the later per-thread `delay_default` polling sleep.

- [ ] **Step 4: Verify legacy tests are GREEN**

Run pacing and main wiring tests. Expected: all pass.

### Task 7: Full Verification and Packaged Smoke Test

**Files:**
- Verify only; do not overwrite the user's existing packaged folder until the build succeeds.

- [ ] **Step 1: Run formatting/lint checks on changed Python files**

Run:

```powershell
.\.venv\Scripts\python.exe -m ruff check src\runtime\pacer.py src\runtime\coordinator.py src\runtime\monitor.py src\dashboard_state.py src\cli_ui.py main.py tests
```

Expected: exit code 0.

- [ ] **Step 2: Run the entire automated suite**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

Expected: all tests pass with zero failures.

- [ ] **Step 3: Run a deterministic 15-room pacing simulation**

Use the fake clock test harness to print permit times. Expected first-permit times: approximately `0, 1, ... 14`; first repeat waits approximately `20` seconds after the last initial permit for a 300-second cycle.

- [ ] **Step 4: Build with the existing PyInstaller specification**

Run:

```powershell
.\.venv\Scripts\pyinstaller.exe --noconfirm --clean DouyinLiveRecorder.spec
```

Expected: exit code 0 and `dist\DouyinLiveRecorder\DouyinLiveRecorder.exe` exists.

- [ ] **Step 5: Smoke-test the new executable without replacing user data**

Copy only non-sensitive test configuration into the new `dist\DouyinLiveRecorder` build, launch with redirected output, verify it remains alive through the first sweep, inspect `logs\streamget.log` for unhandled exceptions, then stop it cleanly. Never copy the user's cookies or tokens into logs or test output.

- [ ] **Step 6: Present build handoff**

Report source/test/build evidence and provide the absolute path to the new executable. Keep the existing `dist-paced-console-final-20260623` folder unchanged unless the user separately asks to replace it.
