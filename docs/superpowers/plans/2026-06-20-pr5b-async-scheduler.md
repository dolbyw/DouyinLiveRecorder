# PR5B Async Scheduler Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the cancellation-safe dynamic network limiter and fault-isolated room scheduler that will become PR5's single-loop control plane.

**Architecture:** `AdjustableLimiter` owns network-request capacity and supports live resize without revoking active permits. `RuntimeScheduler` owns room tasks, reconciles them against `StateStore`, isolates room failures inside per-room supervisors, and provides deterministic asynchronous shutdown; actual platform probing and blocking recording integration remain injected dependencies until PR5C cuts over `main.py`.

**Tech Stack:** Python 3.11 asyncio, dataclasses, pytest-asyncio, Ruff

---

## Locked API contract

The implementation tasks below use these exact public signatures:

```python
class AdjustableLimiter:
    def __init__(self, limit: int) -> None: ...
    @property
    def limit(self) -> int: ...
    @property
    def active_count(self) -> int: ...
    @property
    def waiting_count(self) -> int: ...
    async def acquire(self) -> None: ...
    async def release(self) -> None: ...
    async def set_limit(self, limit: int) -> None: ...
    async def __aenter__(self) -> AdjustableLimiter: ...
    async def __aexit__(self, exc_type, exc, traceback) -> None: ...

RoomWorker = Callable[[RoomSpec], Awaitable[None]]

class RuntimeScheduler:
    def __init__(self, state: StateStore, worker: RoomWorker, *, retry_delay: float = 5.0) -> None: ...
    @property
    def room_ids(self) -> frozenset[str]: ...
    async def reconcile(self, rooms: Iterable[RoomSpec]) -> RoomChangeSet: ...
    async def stop_all(self) -> None: ...
```

The limiter wraps individual platform network probes at their eventual call site; the scheduler must not hold a limiter permit for a room task's lifetime.

### Task 1: Cancellation-safe adjustable limiter

**Files:**
- Create: `src/runtime/limiter.py`
- Create: `tests/runtime/test_limiter.py`
- Modify: `src/runtime/__init__.py`

- [ ] Write tests proving positive limit validation, active-count enforcement, context-manager release, and observable metrics.

```python
async def test_limiter_blocks_above_limit_and_context_releases():
    limiter = AdjustableLimiter(1)
    await limiter.acquire()
    waiter = asyncio.create_task(limiter.acquire())
    await asyncio.sleep(0)
    assert limiter.active_count == 1
    assert limiter.waiting_count == 1
    assert not waiter.done()
    await limiter.release()
    await waiter
    await limiter.release()
    assert limiter.active_count == 0
```
- [ ] Run `pytest tests/runtime/test_limiter.py -q` and verify RED because the limiter module is absent.
- [ ] Implement `AdjustableLimiter` with an `asyncio.Condition`, `acquire()`, `release()`, `set_limit()`, and async context-manager methods.
- [ ] Run the focused tests and verify GREEN.

### Task 2: Runtime resizing and cancellation

**Files:**
- Modify: `tests/runtime/test_limiter.py`
- Modify: `src/runtime/limiter.py`

- [ ] Add tests proving expansion wakes a waiter, shrinkage does not revoke active permits, and cancelling a waiter leaves no leaked permit or waiter count.

```python
async def test_shrink_waits_for_active_count_to_fall_below_new_limit():
    limiter = AdjustableLimiter(2)
    await limiter.acquire()
    await limiter.acquire()
    await limiter.set_limit(1)
    waiter = asyncio.create_task(limiter.acquire())
    await limiter.release()
    await asyncio.sleep(0)
    assert not waiter.done()
    await limiter.release()
    await waiter
```
- [ ] Run the focused tests and verify RED on missing resize behavior.
- [ ] Implement cancellation-safe waiting and condition notifications without modifying active permit count during resize.
- [ ] Run focused tests and verify GREEN.

### Task 3: Room task reconciliation

**Files:**
- Create: `src/runtime/scheduler.py`
- Create: `tests/runtime/test_scheduler.py`
- Modify: `src/runtime/__init__.py`

- [ ] Write async tests proving reconcile starts added rooms once, removes and cancels deleted rooms, and replaces a task when room quality or name changes.

```python
async def test_reconcile_cancels_removed_room():
    cancelled = asyncio.Event()
    async def worker(room):
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()
    scheduler = RuntimeScheduler(StateStore(), worker)
    spec = RoomSpec("https://live.douyin.com/1", QualityLevel.ORIGIN)
    await scheduler.reconcile([spec])
    await scheduler.reconcile([])
    assert cancelled.is_set()
    assert scheduler.room_ids == frozenset()
```
- [ ] Run focused tests and verify RED because `RuntimeScheduler` is absent.
- [ ] Implement URL-keyed task ownership, async `reconcile()`, task cancellation awaiting, `room_ids`, and idempotent `stop_all()`.
- [ ] Run focused tests and verify GREEN.

### Task 4: Supervisor fault isolation and retry

**Files:**
- Modify: `tests/runtime/test_scheduler.py`
- Modify: `src/runtime/scheduler.py`

- [ ] Add tests proving one room exception increments only that room's state and retries after the configured delay while a sibling remains alive; verify `CancelledError` terminates rather than retries.

```python
async def test_room_failure_is_retried_without_cancelling_sibling():
    attempts = Counter()
    sibling_alive = asyncio.Event()
    async def worker(room):
        attempts[room.room_id] += 1
        if room.room_id.endswith("/bad"):
            raise RuntimeError("probe failed")
        sibling_alive.set()
        await asyncio.Event().wait()
    scheduler = RuntimeScheduler(StateStore(), worker, retry_delay=0)
    await scheduler.reconcile([bad_room, good_room])
    await sibling_alive.wait()
    while attempts[bad_room.room_id] < 2:
        await asyncio.sleep(0)
    assert good_room.room_id in scheduler.room_ids
    await scheduler.stop_all()
```
- [ ] Run focused tests and verify RED on absent retry behavior.
- [ ] Implement `_supervise()` with explicit `CancelledError` propagation, ordinary exception capture, `StateStore.mark_room_error()`, and cancellable retry sleep.
- [ ] Run focused tests and verify GREEN.

### Task 5: Verification and roadmap status

**Files:**
- Modify: `docs/项目优化实施路线图.md`

- [ ] Record PR5B foundation status without claiming platform dispatch or `main.py` cutover is complete.
- [ ] Run `pytest tests/runtime -q --basetemp=.pytest-tmp-runtime`.
- [ ] Run full `pytest -q --basetemp=.pytest-tmp-pr5b`.
- [ ] Run Ruff check, Ruff format check, and `py_compile` for `src/runtime`.

Expected final evidence: runtime tests, full regression tests, Ruff, formatting, and compilation all exit zero. Do not commit because this workspace has no Git metadata.
