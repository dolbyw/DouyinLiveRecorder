# PR5C Recording Lifecycle Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bridge blocking recording work into the asyncio runtime with explicit stop propagation and provide an idempotent, ordered application shutdown boundary.

**Architecture:** `RecordingExecutor` owns a dedicated `ThreadPoolExecutor`, one `StopToken` per active room, and the asyncio futures that represent blocking recording calls. `RuntimeApp` coordinates state shutdown intent, recording stop signals, scheduler cancellation, recording drain, and HTTP client closure in a fixed order; `main.py` cutover remains a separate final integration after these lifecycle semantics are proven.

**Tech Stack:** Python 3.11 asyncio, concurrent.futures, threading, pytest-asyncio, Ruff

---

## Locked API

```python
ResultT = TypeVar("ResultT")
RecordingOperation = Callable[[StopToken], ResultT]

class StopToken:
    @property
    def room_stop_requested(self) -> bool: ...
    @property
    def shutdown_requested(self) -> bool: ...
    def request_room_stop(self) -> None: ...
    def request_shutdown(self) -> None: ...

class RecordingExecutor:
    def __init__(self, *, max_workers: int = 4) -> None: ...
    @property
    def active_room_ids(self) -> frozenset[str]: ...
    async def run(self, room_id: str, operation: RecordingOperation[ResultT]) -> ResultT: ...
    def request_room_stop(self, room_id: str) -> bool: ...
    def request_shutdown(self) -> None: ...
    async def close(self, timeout: float) -> tuple[str, ...]: ...

@dataclass(frozen=True, slots=True)
class ShutdownReport:
    unfinished_recordings: tuple[str, ...] = ()

class RuntimeApp:
    async def shutdown(self, *, timeout: float = 10.0) -> ShutdownReport: ...
```

### Task 1: Non-blocking recording execution

**Files:**
- Create: `src/runtime/recording.py`
- Create: `tests/runtime/test_recording_executor.py`
- Modify: `src/runtime/__init__.py`

- [ ] **Step 1: Write failing tests**

```python
@pytest.mark.asyncio
async def test_recording_operation_does_not_block_event_loop():
    release = threading.Event()
    executor = RecordingExecutor(max_workers=1)
    task = asyncio.create_task(executor.run("room-1", lambda token: release.wait() or "done"))
    await asyncio.sleep(0.01)
    assert executor.active_room_ids == frozenset({"room-1"})
    release.set()
    assert await task == "done"
    await executor.close(1)

@pytest.mark.asyncio
async def test_duplicate_active_room_is_rejected():
    release = threading.Event()
    executor = RecordingExecutor(max_workers=1)
    first = asyncio.create_task(executor.run("room-1", lambda token: release.wait()))
    await asyncio.sleep(0.01)
    with pytest.raises(RuntimeError, match="already recording"):
        await executor.run("room-1", lambda token: None)
    release.set()
    await first
    await executor.close(1)
```

- [ ] **Step 2: Verify RED**

Run: `.venv\Scripts\python.exe -m pytest tests/runtime/test_recording_executor.py -q --basetemp=.pytest-tmp-recording`

Expected: import failure because `src.runtime.recording` does not exist.

- [ ] **Step 3: Implement minimal executor**

Use `loop.run_in_executor()` with a dedicated `ThreadPoolExecutor`, register each room before submitting, use `asyncio.shield()` while awaiting, and remove the matching job in `finally`. Validate `max_workers > 0` and reject duplicate active room IDs.

- [ ] **Step 4: Verify GREEN**

Run the focused test command and expect both tests to pass.

### Task 2: Stop propagation and bounded close

**Files:**
- Modify: `src/runtime/recording.py`
- Modify: `tests/runtime/test_recording_executor.py`

- [ ] **Step 1: Write failing tests**

```python
@pytest.mark.asyncio
async def test_cancelling_async_wait_requests_room_stop():
    observed = threading.Event()
    executor = RecordingExecutor(max_workers=1)
    def operation(token):
        while not token.room_stop_requested:
            time.sleep(0.001)
        observed.set()
    task = asyncio.create_task(executor.run("room-1", operation))
    await asyncio.sleep(0.01)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert observed.wait(1)
    await executor.close(1)

@pytest.mark.asyncio
async def test_close_reports_operation_that_ignores_shutdown():
    release = threading.Event()
    executor = RecordingExecutor(max_workers=1)
    task = asyncio.create_task(executor.run("room-1", lambda token: release.wait()))
    await asyncio.sleep(0.01)
    assert await executor.close(0.01) == ("room-1",)
    release.set()
    await task
```

- [ ] **Step 2: Verify RED**

Run the focused tests and expect cancellation/close assertions to fail before stop propagation exists.

- [ ] **Step 3: Implement stop and close**

On `run()` cancellation set the room stop token before re-raising. `request_shutdown()` sets the shutdown bit on every active token. `close()` requests shutdown, waits on shielded job futures up to the supplied non-negative timeout, returns sorted unfinished room IDs, and calls executor shutdown with `wait=True` only when all jobs finished.

- [ ] **Step 4: Verify GREEN**

Run the focused tests and expect all recording-executor tests to pass with no pending-task warnings.

### Task 3: Ordered idempotent RuntimeApp shutdown

**Files:**
- Create: `src/runtime/app.py`
- Create: `tests/runtime/test_app.py`
- Modify: `src/runtime/__init__.py`

- [ ] **Step 1: Write failing tests**

```python
@pytest.mark.asyncio
async def test_shutdown_uses_fixed_order_and_is_idempotent():
    events = []
    state = FakeState(events)
    scheduler = FakeScheduler(events)
    recordings = FakeRecordings(events)
    async def close_http():
        events.append("http.close")
    app = RuntimeApp(state, scheduler, recordings, close_http=close_http)
    first = await app.shutdown(timeout=3)
    second = await app.shutdown(timeout=3)
    assert first is second
    assert events == ["state.shutdown", "recordings.stop", "scheduler.stop", "recordings.close:3", "http.close"]
```

- [ ] **Step 2: Verify RED**

Run: `.venv\Scripts\python.exe -m pytest tests/runtime/test_app.py -q --basetemp=.pytest-tmp-app`

Expected: import failure because `RuntimeApp` does not exist.

- [ ] **Step 3: Implement the application boundary**

Store an `asyncio.Lock` and cached `ShutdownReport`. Inside the lock: mark state shutdown, signal recordings, await scheduler stop, await recording close, close HTTP clients in `finally`, cache the report, and return the same report object on repeated calls.

- [ ] **Step 4: Verify GREEN**

Run focused app tests and expect them to pass.

### Task 4: Verification and roadmap

**Files:**
- Modify: `docs/项目优化实施路线图.md`

- [ ] Record the recording/lifecycle foundation as complete while explicitly leaving signal installation and `main.py` cutover outstanding.
- [ ] Run runtime and full pytest with workspace-local `--basetemp` directories.
- [ ] Run Ruff check, Ruff format check, and `py_compile` over `src/runtime`.

Expected final evidence: all commands exit zero. Do not commit because this workspace has no Git metadata.
