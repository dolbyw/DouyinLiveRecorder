# Request Pacing and Windows Console Hold Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Spread monitoring probes across the configured cycle, raise the default probe concurrency to five, and reliably hold the completed dashboard on Windows until a key is pressed.

**Architecture:** A shared async `RequestPacer` controls probe start times before the existing concurrency limiter. Compatibility threads use the same spacing formula at startup, while Windows key waiting validates the native console input handle instead of trusting Python's `isatty()` wrapper.

**Tech Stack:** Python 3.12 asyncio/threading, ctypes Win32 APIs, pytest, Rich, PyInstaller

---

## File map

- Create `src/runtime/pacer.py`: dynamic global request-start pacer and spacing formula.
- Create `tests/runtime/test_pacer.py`: deterministic pacing tests with injected clock/sleep/jitter.
- Modify `src/runtime/monitor.py`: wait for the pacer before acquiring probe concurrency.
- Modify `src/runtime/coordinator.py`: update pacing from current room count.
- Modify `main.py`: construct shared pacer, stagger legacy threads, and trigger final refresh.
- Modify `src/runtime/exit_wait.py`: use Win32 console handle validation.
- Modify `tests/runtime/test_exit_wait.py`: reproduce false-`isatty` Windows behavior.
- Modify `src/models/config.py`, `src/config_loader.py`, `config/config.ini`: default probe concurrency five.
- Modify `src/cli_ui.py`: label the setting `探测并发`.

### Task 1: Build a deterministic global request pacer

**Files:**
- Create: `tests/runtime/test_pacer.py`
- Create: `src/runtime/pacer.py`
- Modify: `src/runtime/__init__.py`

- [ ] **Step 1: Write failing pacer tests**

Use a fake monotonic clock whose injected sleep advances time:

```python
def test_spacing_divides_window_by_room_count():
    pacer = RequestPacer(jitter=lambda _low, _high: 1.0)
    await pacer.configure(window_seconds=300, room_count=14)
    assert pacer.spacing == pytest.approx(300 / 14)


def test_first_turn_is_immediate_and_following_turn_waits():
    clock = FakeClock()
    pacer = RequestPacer(clock=clock, sleep=clock.sleep, jitter=lambda _low, _high: 1.0)
    await pacer.configure(window_seconds=300, room_count=14)
    await pacer.wait_turn()
    await pacer.wait_turn()
    assert clock.sleeps == [pytest.approx(300 / 14)]


def test_legacy_spacing_uses_larger_of_configured_and_automatic():
    assert calculate_start_spacing(300, 14, 0) == pytest.approx(300 / 14)
    assert calculate_start_spacing(300, 14, 30) == 30
```

- [ ] **Step 2: Run tests and verify RED**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\runtime\test_pacer.py -q
```

Expected: collection fails because `src.runtime.pacer` does not exist.

- [ ] **Step 3: Implement `RequestPacer`**

Implement an async-lock-protected pacer with injectable `clock`, `sleep`, and `jitter`. `configure` validates positive window seconds and stores `spacing = window_seconds / max(1, room_count)`. `wait_turn` lets the first caller start immediately, serializes later callers, sleeps until `_next_allowed`, and advances `_next_allowed` by `spacing * jitter(0.9, 1.1)`.

Implement the pure helper:

```python
def calculate_start_spacing(window_seconds: float, room_count: int, configured_seconds: float = 0) -> float:
    automatic = window_seconds / max(1, room_count)
    return max(0.0, configured_seconds, automatic)
```

- [ ] **Step 4: Run pacer tests and verify GREEN**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\runtime\test_pacer.py -q
```

Expected: all pacer tests pass without real waiting.

### Task 2: Pace every async probe before concurrency acquisition

**Files:**
- Modify: `tests/runtime/test_monitor.py`
- Modify: `tests/runtime/test_coordinator.py`
- Modify: `src/runtime/monitor.py`
- Modify: `src/runtime/coordinator.py`
- Modify: `main.py`

- [ ] **Step 1: Write failing integration tests**

Add a fake pacer that records `wait_turn` and `configure` calls. Verify `RoomMonitor.run_once` calls the pacer while `limiter.active_count == 0`, then acquires the limiter for the probe. Verify `RuntimeCoordinator.refresh_once` configures the pacer with the supplied poll interval and current room count.

```python
assert events == ["pace:0", "probe:1"]
assert pacer.configurations == [(300, 14)]
```

- [ ] **Step 2: Run monitor/coordinator tests and verify RED**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\runtime\test_monitor.py tests\runtime\test_coordinator.py -q
```

Expected: constructors reject the new pacer arguments or no pacing events are recorded.

- [ ] **Step 3: Add optional pacer dependencies**

Add `pacer: RequestPacer | None = None` to `RoomMonitor`; call `await pacer.wait_turn()` immediately before `async with self._limiter`. Add optional `pacer` and `poll_interval` to `RuntimeCoordinator`; after loading config, call `await pacer.configure(window_seconds=poll_interval, room_count=len(config.rooms))` before reconciliation.

In `build_async_runtime_runner`, create one `RequestPacer`, pass it to both monitor and coordinator, and keep the existing `AdjustableLimiter` unchanged.

- [ ] **Step 4: Run runtime tests and verify GREEN**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\runtime\test_monitor.py tests\runtime\test_coordinator.py tests\runtime\test_runtime_runner.py -q
```

Expected: all selected runtime tests pass.

### Task 3: Set probe concurrency to five and stagger legacy rooms

**Files:**
- Modify: `tests/test_config_loader.py`
- Modify: `tests/test_cli_ui.py`
- Modify: `tests/runtime/test_main_runtime_wiring.py`
- Modify: `src/models/config.py`
- Modify: `src/config_loader.py`
- Modify: `src/cli_ui.py`
- Modify: `config/config.ini`
- Modify: `main.py`

- [ ] **Step 1: Write failing default/legacy/UI tests**

Add a config-loader test that omits “同一时间访问网络的线程数” and expects `max_request == 5`. Assert the Rich configuration label is `探测并发`. Add a source contract that main computes compatibility candidates and calls `calculate_start_spacing(delay_default, len(compatibility_candidates), local_delay_default)` before sleeping between new legacy thread starts.

- [ ] **Step 2: Run focused tests and verify RED**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_config_loader.py tests\test_cli_ui.py tests\runtime\test_main_runtime_wiring.py -q
```

Expected: default remains 3, UI label remains “并发”, and main lacks automatic compatibility spacing.

- [ ] **Step 3: Change defaults and compatibility startup pacing**

Change `RecordingConfig.max_request` and `_read_int(..., "同一时间访问网络的线程数", ...)` defaults to 5. Change the source template line to `同一时间访问网络的线程数 = 5`. Rename UI text to `探测并发`.

Before creating compatibility threads, filter rooms not owned by the active async registry and not disabled. Compute:

```python
compatibility_spacing = calculate_start_spacing(
    delay_default,
    len(compatibility_candidates),
    local_delay_default,
)
```

Start candidates in existing order and sleep `compatibility_spacing` only between newly started threads, never after the last one.

- [ ] **Step 4: Run focused tests and verify GREEN**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_config_loader.py tests\test_cli_ui.py tests\runtime\test_main_runtime_wiring.py -q
```

Expected: all focused tests pass.

### Task 4: Fix Windows console detection and immediately refresh final state

**Files:**
- Modify: `tests/runtime/test_exit_wait.py`
- Modify: `tests/runtime/test_main_runtime_wiring.py`
- Modify: `src/runtime/exit_wait.py`
- Modify: `main.py`

- [ ] **Step 1: Write failing Windows regression tests**

Add platform injection to demonstrate the production bug:

```python
def test_windows_console_handle_reads_key_even_when_python_stdin_is_not_tty():
    calls = []
    waited = wait_for_exit_key(
        platform_name="nt",
        is_interactive=lambda: False,
        console_available=lambda: True,
        read_key=lambda: calls.append("read") or "x",
    )
    assert waited is True
    assert calls == ["read"]
```

Add a Windows-no-handle test returning immediately. Extend source wiring tests to require a `dashboard_refresh_event`, event-driven display wait, and `dashboard_refresh_event.set()` between `COMPLETE` and `wait_for_exit_key()`.

- [ ] **Step 2: Run exit/wiring tests and verify RED**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\runtime\test_exit_wait.py tests\runtime\test_main_runtime_wiring.py -q
```

Expected: `wait_for_exit_key` rejects platform/console arguments and final-refresh assertions fail.

- [ ] **Step 3: Implement native Windows console validation**

Add `_windows_console_available()` using `ctypes.WinDLL("kernel32", use_last_error=True)`, `GetStdHandle(-10)`, and `GetConsoleMode`. Reject null and invalid handles. Extend `wait_for_exit_key` with injectable `platform_name` and `console_available`; on Windows use the native console result and ignore `isatty`, then call `msvcrt.getwch` through the existing reader. Preserve non-Windows TTY behavior.

- [ ] **Step 4: Add immediate dashboard refresh signaling**

Create one global `threading.Event`. Replace fixed display sleeps with `event.wait(timeout)` followed by `event.clear()`. In `signal_handler`, after setting `COMPLETE`, call `dashboard_refresh_event.set()` before `wait_for_exit_key()`.

- [ ] **Step 5: Run exit/wiring tests and verify GREEN**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\runtime\test_exit_wait.py tests\runtime\test_main_runtime_wiring.py tests\test_cli_ui.py -q
```

Expected: all selected tests pass.

### Task 5: Verify and package without touching recordings

**Files:**
- Verify all changed files and complete test suite.
- Create `dist-paced-console-final-20260623/DouyinLiveRecorder`.
- Create `DouyinLiveRecorder-paced-console-final-win64-20260623.zip`.

- [ ] **Step 1: Run changed-file Ruff and full pytest**

Run Ruff on all changed source/test files, then `python -m pytest -q`. Expected: exit 0 and zero failures.

- [ ] **Step 2: Run timing simulation**

Use a fake clock with 14 simultaneous `wait_turn` calls, a 300-second window and jitter 1.0. Expected starts: approximately `0, 21.43, 42.86, ... 278.57`, with no duplicate start time.

- [ ] **Step 3: Run real FFmpeg remux smoke**

Generate a one-second TS, convert it through `FFmpegConverter`, and validate the MP4 using bundled ffprobe. Expected: readable MP4 and source deletion only after success.

- [ ] **Step 4: Build and migrate configuration**

Build with PyInstaller into the new versioned directory. Copy current `config.ini` and `URL_config.ini` from `dist-ui-density-final-20260623`, change only the new package's concurrency line to 5, and verify all other configuration lines remain identical.

- [ ] **Step 5: Package and report**

Create the versioned ZIP, verify package resources and archive integrity, and report exact test count, timing simulation, executable path, and ZIP path. The final manual check is pressing Ctrl+C after a live recording, observing the held completion frame, then pressing a normal key.
