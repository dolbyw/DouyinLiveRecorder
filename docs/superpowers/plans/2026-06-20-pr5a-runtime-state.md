# PR5A Runtime State Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Introduce a typed, domain-oriented runtime state store that separates desired room configuration from observed monitoring and recording state without changing the current thread scheduler.

**Architecture:** Add immutable runtime value objects in `src/runtime/models.py` and an event-loop-owned `StateStore` in `src/runtime/state.py`. The store uses URL identity, returns explicit reconciliation deltas, exposes immutable snapshots, and contains no asyncio tasks or generic key-value API; `main.py` integration is deferred until the state contract is proven independently.

**Tech Stack:** Python 3.11 dataclasses, enums, pytest, Ruff

---

### Task 1: Runtime room models

**Files:**
- Create: `src/runtime/__init__.py`
- Create: `src/runtime/models.py`
- Test: `tests/runtime/test_runtime_models.py`

- [ ] **Step 1: Write the failing model tests**

```python
from dataclasses import FrozenInstanceError

import pytest

from src.models import QualityLevel
from src.runtime.models import RoomSpec, RoomStatus


def test_room_spec_requires_an_absolute_http_url():
    with pytest.raises(ValueError, match="absolute HTTP URL"):
        RoomSpec(url="live.douyin.com/1", quality=QualityLevel.ORIGIN)


def test_room_spec_is_immutable_and_uses_url_identity():
    room = RoomSpec(url="https://live.douyin.com/1", quality=QualityLevel.HD, name="主播")
    with pytest.raises(FrozenInstanceError):
        room.name = "changed"
    assert room.room_id == "https://live.douyin.com/1"


def test_room_status_starts_idle():
    status = RoomStatus(room_id="https://live.douyin.com/1")
    assert status.monitoring is False
    assert status.recording_name is None
    assert status.consecutive_errors == 0
```

- [ ] **Step 2: Run the tests and verify RED**

Run: `.venv\Scripts\python.exe -m pytest tests/runtime/test_runtime_models.py -q`

Expected: collection fails because `src.runtime` does not exist.

- [ ] **Step 3: Implement the immutable models**

Create `RoomSpec` with URL validation and a `room_id` property, `RoomStatus` with monitoring/recording/error/stop fields, `RoomChangeSet` with added/removed/updated tuples, and `RuntimeSnapshot` with desired rooms, statuses, and shutdown state. Use frozen, slotted dataclasses and tuple-based snapshot collections.

- [ ] **Step 4: Run model tests and verify GREEN**

Run: `.venv\Scripts\python.exe -m pytest tests/runtime/test_runtime_models.py -q`

Expected: `3 passed`.

### Task 2: Desired-room reconciliation

**Files:**
- Create: `src/runtime/state.py`
- Test: `tests/runtime/test_state.py`

- [ ] **Step 1: Write failing reconciliation tests**

```python
import pytest

from src.models import QualityLevel
from src.runtime import RoomSpec, StateStore


def room(url: str, quality: QualityLevel = QualityLevel.ORIGIN, name: str = "") -> RoomSpec:
    return RoomSpec(url=url, quality=quality, name=name)


def test_replace_desired_rooms_reports_added_removed_and_updated():
    store = StateStore()
    first = room("https://live.douyin.com/1")
    removed = room("https://live.douyin.com/2")
    store.replace_desired_rooms([first, removed])

    updated = room(first.url, QualityLevel.HD, "new name")
    added = room("https://live.douyin.com/3")
    changes = store.replace_desired_rooms([updated, added])

    assert changes.added == (added,)
    assert changes.removed == (removed,)
    assert changes.updated == ((first, updated),)


def test_replace_desired_rooms_rejects_duplicate_urls():
    store = StateStore()
    duplicate = room("https://live.douyin.com/1")
    with pytest.raises(ValueError, match="duplicate room"):
        store.replace_desired_rooms([duplicate, duplicate])
```

- [ ] **Step 2: Run the reconciliation tests and verify RED**

Run: `.venv\Scripts\python.exe -m pytest tests/runtime/test_state.py -q`

Expected: import fails because `StateStore` does not exist.

- [ ] **Step 3: Implement minimal reconciliation**

Implement `StateStore.replace_desired_rooms()` using URL-keyed dictionaries, deterministic input ordering, duplicate rejection, and `RoomChangeSet`. Removing a desired room marks its existing status as stop requested but does not silently discard observed state.

- [ ] **Step 4: Run reconciliation tests and verify GREEN**

Run: `.venv\Scripts\python.exe -m pytest tests/runtime/test_state.py -q`

Expected: reconciliation tests pass.

### Task 3: Observed state transitions

**Files:**
- Modify: `src/runtime/state.py`
- Test: `tests/runtime/test_state.py`

- [ ] **Step 1: Add failing state-transition tests**

```python
from datetime import UTC, datetime


def test_recording_lifecycle_updates_observed_state():
    store = StateStore()
    spec = room("https://live.douyin.com/1", QualityLevel.HD)
    store.replace_desired_rooms([spec])
    started_at = datetime(2026, 6, 20, tzinfo=UTC)

    store.mark_monitoring(spec.room_id)
    store.mark_recording_started(spec.room_id, "序号1 主播", QualityLevel.HD, started_at)
    recording = store.snapshot().status_for(spec.room_id)
    assert recording.monitoring is True
    assert recording.recording_name == "序号1 主播"
    assert recording.recording_started_at == started_at

    store.mark_recording_finished(spec.room_id)
    assert store.snapshot().status_for(spec.room_id).recording_name is None


def test_success_clears_consecutive_room_errors():
    store = StateStore()
    spec = room("https://live.douyin.com/1")
    store.replace_desired_rooms([spec])
    store.mark_room_error(spec.room_id, "network")
    store.mark_room_error(spec.room_id, "network again")
    assert store.snapshot().status_for(spec.room_id).consecutive_errors == 2
    store.mark_room_success(spec.room_id)
    assert store.snapshot().status_for(spec.room_id).consecutive_errors == 0
```

- [ ] **Step 2: Run the new tests and verify RED**

Run: `.venv\Scripts\python.exe -m pytest tests/runtime/test_state.py -q`

Expected: missing state-transition methods.

- [ ] **Step 3: Implement explicit state transitions**

Use `dataclasses.replace()` to update frozen `RoomStatus` values. Unknown room IDs raise `KeyError`; recording start validates timezone-aware timestamps; finish is idempotent; success clears the last error and consecutive error count.

- [ ] **Step 4: Run state tests and verify GREEN**

Run: `.venv\Scripts\python.exe -m pytest tests/runtime/test_state.py -q`

Expected: all state tests pass.

### Task 4: Stop intent and immutable snapshots

**Files:**
- Modify: `src/runtime/models.py`
- Modify: `src/runtime/state.py`
- Test: `tests/runtime/test_state.py`

- [ ] **Step 1: Add failing stop and snapshot tests**

```python
def test_room_and_application_stop_are_idempotent():
    store = StateStore()
    spec = room("https://live.douyin.com/1")
    store.replace_desired_rooms([spec])
    store.request_room_stop(spec.room_id)
    store.request_room_stop(spec.room_id)
    store.request_shutdown()
    store.request_shutdown()
    snapshot = store.snapshot()
    assert snapshot.shutdown_requested is True
    assert snapshot.status_for(spec.room_id).stop_requested is True


def test_snapshot_is_detached_from_later_store_changes():
    store = StateStore()
    first = room("https://live.douyin.com/1")
    store.replace_desired_rooms([first])
    before = store.snapshot()
    store.replace_desired_rooms([first, room("https://live.douyin.com/2")])
    assert before.desired_rooms == (first,)
```

- [ ] **Step 2: Run the tests and verify RED**

Run: `.venv\Scripts\python.exe -m pytest tests/runtime/test_state.py -q`

Expected: stop methods or snapshot lookup are missing.

- [ ] **Step 3: Implement stop intent and snapshots**

Add idempotent room/application stop methods. `RuntimeSnapshot.status_for()` performs URL lookup and raises `KeyError` for unknown rooms. Snapshot construction copies values into tuples so subsequent store mutations cannot affect existing snapshots.

- [ ] **Step 4: Run the runtime tests and verify GREEN**

Run: `.venv\Scripts\python.exe -m pytest tests/runtime -q`

Expected: all runtime tests pass.

### Task 5: Python 3.11 baseline and package quality

**Files:**
- Modify: `pyproject.toml`
- Modify: `docs/项目优化实施路线图.md`
- Test: `tests/runtime/test_package_contract.py`

- [ ] **Step 1: Write a failing package-contract test**

```python
from pathlib import Path


def test_project_declares_python_311_runtime_baseline():
    project = Path("pyproject.toml").read_text(encoding="utf-8")
    assert 'requires-python = ">=3.11"' in project
    assert 'target-version = "py311"' in project
```

- [ ] **Step 2: Run the contract test and verify RED**

Run: `.venv\Scripts\python.exe -m pytest tests/runtime/test_package_contract.py -q`

Expected: assertions show the existing 3.10 baseline.

- [ ] **Step 3: Update the declared baseline**

Change `requires-python` to `>=3.11` and Ruff `target-version` to `py311`. Record PR5A implementation status in the roadmap without claiming PR5B scheduling work is complete.

- [ ] **Step 4: Run focused and full verification**

Run:

```powershell
.venv\Scripts\python.exe -m pytest tests/runtime -q
.venv\Scripts\python.exe -m pytest -q
.venv\Scripts\python.exe -m ruff check src/runtime tests/runtime
.venv\Scripts\python.exe -m ruff format --check src/runtime tests/runtime
.venv\Scripts\python.exe -m py_compile src/runtime/__init__.py src/runtime/models.py src/runtime/state.py
```

Expected: all commands exit zero. Do not commit because this workspace has no Git metadata.

## Follow-on plans

After PR5A verification, write and execute separate TDD plans for:

- PR5B: `AdjustableLimiter`, room supervisor, scheduler reconciliation, Python 3.11 `TaskGroup`, and async platform-dispatch integration;
- PR5C: `RecordingExecutor`, thread-safe stop propagation, `RuntimeApp`, signal handling, HTTP client shutdown, and `main.py` cutover.
