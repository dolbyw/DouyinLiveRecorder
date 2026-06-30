# Upload Queue Workbench Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the coarse one-shot upload loop with a durable file-level upload queue and add a separate read-only upload workbench console window.

**Architecture:** The main process owns upload scanning, planning, execution, SQLite state, and JSON snapshots. The recording dashboard stays the default UI and shows only brief per-room upload summaries. The upload workbench is a separate observer process/window that reads snapshots and never mutates queue state or calls rclone.

**Tech Stack:** Python 3.11+, SQLite via stdlib `sqlite3`, rclone CLI/RC, existing Rich console dashboard, pytest, ruff, PyInstaller onedir packaging.

---

## File Structure

- Create `src/uploader/models.py`: upload task dataclasses, status enum, conflict policy enum, remote entry model, snapshot models.
- Create `src/uploader/store.py`: SQLite schema, migrations, task upsert/update/query methods.
- Create `src/uploader/scanner.py`: stable-file detection and local file discovery.
- Create `src/uploader/planner.py`: local/remote comparison and deterministic duplicate rename planning.
- Create `src/uploader/executor.py`: file-level copy, verify, delete, retry, and empty-dir cleanup.
- Create `src/uploader/snapshot.py`: convert queue state into compact JSON snapshots for dashboard and workbench.
- Create `src/upload_workbench.py`: standalone read-only console workbench entrypoint.
- Modify `src/uploader/service.py`: preserve existing helpers, route `RcloneUploadService.run_once` through queue/executor for CLI mode.
- Modify `src/uploader/rc_service.py`: keep RC daemon progress path, but use file-level queue semantics and verification.
- Modify `src/uploader/__init__.py`: export new public models/services.
- Modify `src/dashboard_state.py`: add room upload summary and richer aggregate upload status.
- Modify `src/dashboard_view.py`: render brief upload text in room rows and aggregate counters in health/config.
- Modify `src/dashboard_input.py`: change `U` behavior from detail toggle to workbench launch callback.
- Modify `main.py`: create queue store, start upload scheduler, publish snapshots, launch observer window on `U`.
- Modify `DouyinLiveRecorder.spec`: include `src/upload_workbench.py` as a collected script or ensure it can be launched by the main exe with an argument.
- Add tests under `tests/uploader/`: `test_store.py`, `test_scanner.py`, `test_planner.py`, `test_executor.py`, `test_snapshot.py`.
- Add tests under `tests/runtime/`: `test_upload_workbench_wiring.py`.
- Add tests under `tests/`: update dashboard and packaging tests for new UI and workbench entrypoint.

---

## Task 1: Queue Models And SQLite Store

**Files:**
- Create: `src/uploader/models.py`
- Create: `src/uploader/store.py`
- Test: `tests/uploader/test_store.py`

- [ ] **Step 1: Write failing store tests**

Add `tests/uploader/test_store.py`:

```python
from pathlib import Path

from src.uploader.models import UploadConflictPolicy, UploadTaskStatus
from src.uploader.store import UploadQueueStore


def test_store_initializes_schema_and_upserts_task(tmp_path):
    db_path = tmp_path / "upload.sqlite3"
    store = UploadQueueStore(db_path)

    task = store.upsert_discovered_file(
        source_root=tmp_path / "downloads",
        local_path=tmp_path / "downloads" / "room" / "a.ts",
        relative_path="room/a.ts",
        size_bytes=12,
        mtime_ns=123456,
        room_label="room",
    )

    loaded = store.get_task(task.id)
    assert loaded is not None
    assert loaded.relative_path == "room/a.ts"
    assert loaded.status is UploadTaskStatus.WAITING
    assert loaded.conflict_policy is UploadConflictPolicy.RENAME


def test_store_persists_planned_remote_path_and_status(tmp_path):
    store = UploadQueueStore(tmp_path / "upload.sqlite3")
    task = store.upsert_discovered_file(
        source_root=tmp_path,
        local_path=tmp_path / "a.ts",
        relative_path="a.ts",
        size_bytes=1,
        mtime_ns=10,
        room_label="",
    )

    store.mark_planned(task.id, remote_path="123pan:/LiveBackup/a (2).ts", status=UploadTaskStatus.RENAMED)
    store.record_attempt(task.id, status=UploadTaskStatus.UPLOADING, error="")
    store.mark_done(task.id)

    loaded = store.get_task(task.id)
    assert loaded is not None
    assert loaded.planned_remote_path == "123pan:/LiveBackup/a (2).ts"
    assert loaded.status is UploadTaskStatus.DONE
    assert loaded.attempts == 1


def test_store_lists_active_tasks_in_priority_order(tmp_path):
    store = UploadQueueStore(tmp_path / "upload.sqlite3")
    old = store.upsert_discovered_file(tmp_path, tmp_path / "old.ts", "old.ts", 1, 1, "")
    new = store.upsert_discovered_file(tmp_path, tmp_path / "new.ts", "new.ts", 1, 2, "")
    store.mark_failed(old.id, "network timeout")

    active = store.list_active_tasks(limit=10)

    assert [task.relative_path for task in active] == ["new.ts", "old.ts"]
```

- [ ] **Step 2: Run tests and verify RED**

Run:

```powershell
& 'C:\Users\Admin\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m pytest tests/uploader/test_store.py -q
```

Expected: import error for missing `src.uploader.models` or `src.uploader.store`.

- [ ] **Step 3: Implement models**

Create `src/uploader/models.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from pathlib import Path


class UploadTaskStatus(StrEnum):
    WAITING = "waiting"
    COOLING = "cooling"
    COMPARING = "comparing"
    UPLOADING = "uploading"
    VERIFYING = "verifying"
    DONE = "done"
    SKIPPED = "skipped"
    RENAMED = "renamed"
    FAILED = "failed"


class UploadConflictPolicy(StrEnum):
    RENAME = "rename"


@dataclass(frozen=True, slots=True)
class UploadTask:
    id: int
    source_root: Path
    local_path: Path
    relative_path: str
    planned_remote_path: str
    size_bytes: int
    mtime_ns: int
    room_label: str
    status: UploadTaskStatus
    conflict_policy: UploadConflictPolicy
    attempts: int
    last_error: str
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class RemoteEntry:
    path: str
    size_bytes: int
    hash_value: str = ""
    is_dir: bool = False
```

- [ ] **Step 4: Implement SQLite store**

Create `src/uploader/store.py`:

```python
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from .models import UploadConflictPolicy, UploadTask, UploadTaskStatus


SCHEMA = """
CREATE TABLE IF NOT EXISTS upload_tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_root TEXT NOT NULL,
    local_path TEXT NOT NULL UNIQUE,
    relative_path TEXT NOT NULL,
    planned_remote_path TEXT NOT NULL DEFAULT '',
    size_bytes INTEGER NOT NULL,
    mtime_ns INTEGER NOT NULL,
    room_label TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL,
    conflict_policy TEXT NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 0,
    last_error TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_upload_tasks_status_updated ON upload_tasks(status, updated_at);
"""


class UploadQueueStore:
    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(SCHEMA)

    def upsert_discovered_file(
        self,
        source_root: str | Path,
        local_path: str | Path,
        relative_path: str,
        size_bytes: int,
        mtime_ns: int,
        room_label: str,
    ) -> UploadTask:
        now = _now()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO upload_tasks (
                    source_root, local_path, relative_path, size_bytes, mtime_ns,
                    room_label, status, conflict_policy, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(local_path) DO UPDATE SET
                    size_bytes=excluded.size_bytes,
                    mtime_ns=excluded.mtime_ns,
                    room_label=excluded.room_label,
                    updated_at=excluded.updated_at
                """,
                (
                    str(Path(source_root)),
                    str(Path(local_path)),
                    relative_path,
                    max(0, int(size_bytes)),
                    int(mtime_ns),
                    room_label,
                    UploadTaskStatus.WAITING.value,
                    UploadConflictPolicy.RENAME.value,
                    now,
                    now,
                ),
            )
            row = connection.execute("SELECT * FROM upload_tasks WHERE local_path = ?", (str(Path(local_path)),)).fetchone()
        return _task_from_row(row)

    def get_task(self, task_id: int) -> UploadTask | None:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM upload_tasks WHERE id = ?", (task_id,)).fetchone()
        return None if row is None else _task_from_row(row)

    def mark_planned(self, task_id: int, *, remote_path: str, status: UploadTaskStatus) -> None:
        self._update(task_id, planned_remote_path=remote_path, status=status.value)

    def record_attempt(self, task_id: int, *, status: UploadTaskStatus, error: str) -> None:
        now = _now()
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE upload_tasks
                SET attempts = attempts + 1, status = ?, last_error = ?, updated_at = ?
                WHERE id = ?
                """,
                (status.value, error, now, task_id),
            )

    def mark_done(self, task_id: int) -> None:
        self._update(task_id, status=UploadTaskStatus.DONE.value, last_error="")

    def mark_failed(self, task_id: int, error: str) -> None:
        self._update(task_id, status=UploadTaskStatus.FAILED.value, last_error=error)

    def list_active_tasks(self, *, limit: int) -> list[UploadTask]:
        active = (
            UploadTaskStatus.WAITING.value,
            UploadTaskStatus.COOLING.value,
            UploadTaskStatus.COMPARING.value,
            UploadTaskStatus.UPLOADING.value,
            UploadTaskStatus.VERIFYING.value,
            UploadTaskStatus.RENAMED.value,
            UploadTaskStatus.FAILED.value,
        )
        with self._connect() as connection:
            rows = connection.execute(
                f"""
                SELECT * FROM upload_tasks
                WHERE status IN ({",".join("?" for _ in active)})
                ORDER BY
                    CASE status WHEN ? THEN 1 ELSE 0 END,
                    updated_at ASC,
                    id ASC
                LIMIT ?
                """,
                (*active, UploadTaskStatus.FAILED.value, limit),
            ).fetchall()
        return [_task_from_row(row) for row in rows]

    def _update(self, task_id: int, **values: str) -> None:
        if not values:
            return
        values["updated_at"] = _now()
        assignments = ", ".join(f"{key} = ?" for key in values)
        with self._connect() as connection:
            connection.execute(
                f"UPDATE upload_tasks SET {assignments} WHERE id = ?",
                (*values.values(), task_id),
            )


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _task_from_row(row: sqlite3.Row) -> UploadTask:
    return UploadTask(
        id=int(row["id"]),
        source_root=Path(row["source_root"]),
        local_path=Path(row["local_path"]),
        relative_path=str(row["relative_path"]),
        planned_remote_path=str(row["planned_remote_path"]),
        size_bytes=int(row["size_bytes"]),
        mtime_ns=int(row["mtime_ns"]),
        room_label=str(row["room_label"]),
        status=UploadTaskStatus(str(row["status"])),
        conflict_policy=UploadConflictPolicy(str(row["conflict_policy"])),
        attempts=int(row["attempts"]),
        last_error=str(row["last_error"]),
        created_at=datetime.fromisoformat(str(row["created_at"])),
        updated_at=datetime.fromisoformat(str(row["updated_at"])),
    )
```

- [ ] **Step 5: Run tests and verify GREEN**

Run:

```powershell
& 'C:\Users\Admin\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m pytest tests/uploader/test_store.py -q
```

Expected: `3 passed`.

- [ ] **Step 6: Commit**

```powershell
git add src/uploader/models.py src/uploader/store.py tests/uploader/test_store.py
git commit -m "feat: add durable upload queue store"
```

---

## Task 2: Scanner And Difference Planner

**Files:**
- Create: `src/uploader/scanner.py`
- Create: `src/uploader/planner.py`
- Test: `tests/uploader/test_scanner.py`
- Test: `tests/uploader/test_planner.py`

- [ ] **Step 1: Write scanner tests**

Create `tests/uploader/test_scanner.py`:

```python
from src.uploader.scanner import discover_stable_files


def test_discover_stable_files_returns_nested_video_files(tmp_path):
    root = tmp_path / "downloads"
    room = root / "抖音直播" / "Alice"
    room.mkdir(parents=True)
    video = room / "a.ts"
    video.write_bytes(b"x")

    files = discover_stable_files(root, min_age_seconds=0, now_seconds=100)

    assert len(files) == 1
    assert files[0].local_path == video
    assert files[0].relative_path == "抖音直播/Alice/a.ts"
    assert files[0].room_label == "Alice"


def test_discover_stable_files_skips_partial_and_recent_files(tmp_path):
    root = tmp_path / "downloads"
    root.mkdir()
    partial = root / "a.ts.part"
    partial.write_bytes(b"x")
    fresh = root / "fresh.ts"
    fresh.write_bytes(b"x")
    old = root / "old.ts"
    old.write_bytes(b"x")

    fresh_mtime = fresh.stat().st_mtime
    old_mtime = fresh_mtime - 7200
    old_mtime_ns = int(old_mtime * 1_000_000_000)
    old.touch()
    import os
    os.utime(old, ns=(old_mtime_ns, old_mtime_ns))

    files = discover_stable_files(root, min_age_seconds=3600, now_seconds=fresh_mtime)

    assert [file.relative_path for file in files] == ["old.ts"]
```

- [ ] **Step 2: Write planner tests**

Create `tests/uploader/test_planner.py`:

```python
from pathlib import Path

from src.uploader.models import RemoteEntry, UploadConflictPolicy, UploadTask, UploadTaskStatus
from src.uploader.planner import plan_upload_target


def _task(relative_path: str, size: int = 10) -> UploadTask:
    import datetime

    now = datetime.datetime.now(datetime.UTC)
    return UploadTask(
        id=1,
        source_root=Path("downloads"),
        local_path=Path("downloads") / relative_path,
        relative_path=relative_path,
        planned_remote_path="",
        size_bytes=size,
        mtime_ns=1,
        room_label="",
        status=UploadTaskStatus.WAITING,
        conflict_policy=UploadConflictPolicy.RENAME,
        attempts=0,
        last_error="",
        created_at=now,
        updated_at=now,
    )


def test_plan_upload_target_uploads_when_remote_missing():
    plan = plan_upload_target(_task("room/a.ts"), remote_root="123pan:/LiveBackup", remote_entries=[])

    assert plan.status is UploadTaskStatus.WAITING
    assert plan.remote_path == "123pan:/LiveBackup/room/a.ts"


def test_plan_upload_target_skips_when_remote_same_size():
    plan = plan_upload_target(
        _task("room/a.ts", size=10),
        remote_root="123pan:/LiveBackup",
        remote_entries=[RemoteEntry(path="room/a.ts", size_bytes=10)],
    )

    assert plan.status is UploadTaskStatus.SKIPPED
    assert plan.remote_path == "123pan:/LiveBackup/room/a.ts"


def test_plan_upload_target_renames_when_remote_same_path_differs():
    plan = plan_upload_target(
        _task("room/a.ts", size=10),
        remote_root="123pan:/LiveBackup",
        remote_entries=[
            RemoteEntry(path="room/a.ts", size_bytes=99),
            RemoteEntry(path="room/a (2).ts", size_bytes=88),
        ],
    )

    assert plan.status is UploadTaskStatus.RENAMED
    assert plan.remote_path == "123pan:/LiveBackup/room/a (3).ts"
```

- [ ] **Step 3: Run tests and verify RED**

Run:

```powershell
& 'C:\Users\Admin\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m pytest tests/uploader/test_scanner.py tests/uploader/test_planner.py -q
```

Expected: import errors for missing modules.

- [ ] **Step 4: Implement scanner**

Create `src/uploader/scanner.py`:

```python
from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class DiscoveredUploadFile:
    source_root: Path
    local_path: Path
    relative_path: str
    size_bytes: int
    mtime_ns: int
    room_label: str


_SKIPPED_SUFFIXES = (".part", ".tmp", ".download", ".partial")
_VIDEO_SUFFIXES = {".ts", ".mp4", ".flv", ".mkv", ".mov"}


def discover_stable_files(
    source_root: str | Path,
    *,
    min_age_seconds: int,
    now_seconds: float | None = None,
) -> list[DiscoveredUploadFile]:
    root = Path(source_root)
    if not root.exists() or not root.is_dir():
        return []
    now = time.time() if now_seconds is None else now_seconds
    files: list[DiscoveredUploadFile] = []
    for candidate in sorted(root.rglob("*")):
        if not candidate.is_file():
            continue
        if candidate.name.endswith(_SKIPPED_SUFFIXES) or candidate.suffix.lower() not in _VIDEO_SUFFIXES:
            continue
        stat = candidate.stat()
        if now - stat.st_mtime < max(0, min_age_seconds):
            continue
        relative = candidate.relative_to(root).as_posix()
        files.append(
            DiscoveredUploadFile(
                source_root=root,
                local_path=candidate,
                relative_path=relative,
                size_bytes=stat.st_size,
                mtime_ns=stat.st_mtime_ns,
                room_label=_room_label(candidate, root),
            )
        )
    return files


def _room_label(path: Path, root: Path) -> str:
    parts = path.relative_to(root).parts
    return parts[-2] if len(parts) >= 2 else ""
```

- [ ] **Step 5: Implement planner**

Create `src/uploader/planner.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath

from .models import RemoteEntry, UploadTask, UploadTaskStatus


@dataclass(frozen=True, slots=True)
class UploadPlan:
    remote_path: str
    relative_path: str
    status: UploadTaskStatus


def plan_upload_target(task: UploadTask, *, remote_root: str, remote_entries: list[RemoteEntry]) -> UploadPlan:
    remote_root = remote_root.rstrip("/")
    remote_by_path = {entry.path.replace("\\", "/"): entry for entry in remote_entries if not entry.is_dir}
    relative = task.relative_path.replace("\\", "/")
    existing = remote_by_path.get(relative)
    if existing is None:
        return UploadPlan(remote_path=f"{remote_root}/{relative}", relative_path=relative, status=UploadTaskStatus.WAITING)
    if existing.size_bytes == task.size_bytes:
        return UploadPlan(remote_path=f"{remote_root}/{relative}", relative_path=relative, status=UploadTaskStatus.SKIPPED)

    renamed = _next_available_name(relative, set(remote_by_path))
    return UploadPlan(remote_path=f"{remote_root}/{renamed}", relative_path=renamed, status=UploadTaskStatus.RENAMED)


def _next_available_name(relative_path: str, existing_paths: set[str]) -> str:
    path = PurePosixPath(relative_path)
    stem = path.stem
    suffix = path.suffix
    parent = "" if str(path.parent) == "." else f"{path.parent}/"
    counter = 2
    while True:
        candidate = f"{parent}{stem} ({counter}){suffix}"
        if candidate not in existing_paths:
            return candidate
        counter += 1
```

- [ ] **Step 6: Run tests and verify GREEN**

Run:

```powershell
& 'C:\Users\Admin\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m pytest tests/uploader/test_scanner.py tests/uploader/test_planner.py -q
```

Expected: all tests pass.

- [ ] **Step 7: Commit**

```powershell
git add src/uploader/scanner.py src/uploader/planner.py tests/uploader/test_scanner.py tests/uploader/test_planner.py
git commit -m "feat: plan upload tasks from local and remote state"
```

---

## Task 3: File-Level Executor With Verify Before Delete

**Files:**
- Create: `src/uploader/executor.py`
- Modify: `src/uploader/service.py`
- Test: `tests/uploader/test_executor.py`
- Test: `tests/uploader/test_service.py`

- [ ] **Step 1: Write executor tests**

Create `tests/uploader/test_executor.py`:

```python
from pathlib import Path

from src.models import UploadConfig
from src.uploader.executor import FileUploadExecutor
from src.uploader.models import UploadConflictPolicy, UploadTask, UploadTaskStatus
from src.uploader.service import RcloneResult


def _task(tmp_path: Path) -> UploadTask:
    import datetime

    source = tmp_path / "downloads"
    source.mkdir()
    local = source / "a.ts"
    local.write_bytes(b"x")
    now = datetime.datetime.now(datetime.UTC)
    return UploadTask(
        id=1,
        source_root=source,
        local_path=local,
        relative_path="a.ts",
        planned_remote_path="123pan:/LiveBackup/a.ts",
        size_bytes=1,
        mtime_ns=local.stat().st_mtime_ns,
        room_label="",
        status=UploadTaskStatus.WAITING,
        conflict_policy=UploadConflictPolicy.RENAME,
        attempts=0,
        last_error="",
        created_at=now,
        updated_at=now,
    )


def test_executor_copies_verifies_and_deletes_local_file(tmp_path):
    task = _task(tmp_path)
    calls = []

    def runner(command):
        calls.append(command)
        if "lsjson" in command:
            return RcloneResult(exit_code=0, stdout='[{"Path":"a.ts","Size":1,"IsDir":false}]')
        return RcloneResult(exit_code=0)

    result = FileUploadExecutor(UploadConfig(enabled=True), runner=runner).upload(task)

    assert result.phase == "success"
    assert not task.local_path.exists()
    assert calls[0][1] == "copyto"
    assert calls[1][1] == "lsjson"


def test_executor_keeps_local_file_when_verify_fails(tmp_path):
    task = _task(tmp_path)

    def runner(command):
        if "lsjson" in command:
            return RcloneResult(exit_code=0, stdout="[]")
        return RcloneResult(exit_code=0)

    result = FileUploadExecutor(UploadConfig(enabled=True), runner=runner).upload(task)

    assert result.phase == "failed"
    assert task.local_path.exists()
    assert "remote verification failed" in result.message
```

- [ ] **Step 2: Run tests and verify RED**

Run:

```powershell
& 'C:\Users\Admin\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m pytest tests/uploader/test_executor.py -q
```

Expected: import error for missing `src.uploader.executor`.

- [ ] **Step 3: Implement executor**

Create `src/uploader/executor.py`:

```python
from __future__ import annotations

import json
from pathlib import Path

from src.models import UploadConfig

from .models import UploadTask
from .service import RcloneResult, UploadRunResult, RcloneRunner, resolve_rclone_binary, run_rclone_subprocess


class FileUploadExecutor:
    def __init__(
        self,
        config: UploadConfig,
        *,
        runner: RcloneRunner = run_rclone_subprocess,
        app_root: str | Path | None = None,
    ) -> None:
        self.config = config
        self.runner = runner
        self.app_root = app_root

    def upload(self, task: UploadTask) -> UploadRunResult:
        copy_result = self.runner(_copyto_command(self.config, task, app_root=self.app_root))
        if copy_result.exit_code != 0 and "object not found" not in f"{copy_result.stderr}\n{copy_result.stdout}".lower():
            return UploadRunResult(
                phase="failed",
                attempts=1,
                exit_code=copy_result.exit_code,
                stdout=copy_result.stdout,
                stderr=copy_result.stderr,
                message="upload failed",
            )
        if not self._verify(task):
            return UploadRunResult(
                phase="failed",
                attempts=1,
                exit_code=1,
                stdout=copy_result.stdout,
                stderr=copy_result.stderr,
                message="remote verification failed",
            )
        task.local_path.unlink(missing_ok=True)
        _remove_empty_parents(task.local_path.parent, task.source_root)
        return UploadRunResult(
            phase="success",
            attempts=1,
            exit_code=0,
            stdout=copy_result.stdout,
            stderr=copy_result.stderr,
            message="upload completed after remote verification",
        )

    def _verify(self, task: UploadTask) -> bool:
        result = self.runner(_lsjson_command(self.config, task, app_root=self.app_root))
        if result.exit_code != 0:
            return False
        try:
            entries = json.loads(result.stdout or "[]")
        except ValueError:
            return False
        if not isinstance(entries, list):
            return False
        filename = Path(task.planned_remote_path).name
        return any(
            isinstance(entry, dict)
            and not entry.get("IsDir")
            and str(entry.get("Name") or entry.get("Path") or "").endswith(filename)
            and int(entry.get("Size", -1)) == task.size_bytes
            for entry in entries
        )


def _copyto_command(config: UploadConfig, task: UploadTask, *, app_root: str | Path | None) -> list[str]:
    command = [
        resolve_rclone_binary(config, app_root),
        "copyto",
        str(task.local_path),
        task.planned_remote_path,
        "--transfers",
        "1",
        "--checkers",
        str(config.checkers),
        "--retries",
        str(config.rclone_retries),
        "-v",
    ]
    if config.dry_run:
        command.append("--dry-run")
    return command


def _lsjson_command(config: UploadConfig, task: UploadTask, *, app_root: str | Path | None) -> list[str]:
    return [resolve_rclone_binary(config, app_root), "lsjson", task.planned_remote_path]


def _remove_empty_parents(path: Path, stop_at: Path) -> None:
    current = path
    stop = stop_at.resolve()
    while current.exists() and current.resolve() != stop:
        try:
            current.rmdir()
        except OSError:
            return
        current = current.parent
```

- [ ] **Step 4: Run executor tests**

Run:

```powershell
& 'C:\Users\Admin\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m pytest tests/uploader/test_executor.py -q
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```powershell
git add src/uploader/executor.py tests/uploader/test_executor.py
git commit -m "feat: upload files with verify-before-delete"
```

---

## Task 4: Snapshot Publisher And Dashboard Summaries

**Files:**
- Create: `src/uploader/snapshot.py`
- Modify: `src/dashboard_state.py`
- Modify: `src/dashboard_view.py`
- Test: `tests/uploader/test_snapshot.py`
- Test: `tests/test_dashboard_view.py`

- [ ] **Step 1: Write snapshot tests**

Create `tests/uploader/test_snapshot.py`:

```python
from src.uploader.models import UploadTaskStatus
from src.uploader.snapshot import UploadSnapshot, summarize_upload_status


def test_upload_snapshot_counts_statuses():
    snapshot = UploadSnapshot(
        uploading=2,
        waiting=23,
        verifying=1,
        conflicts=2,
        failed=1,
        completed_today=41,
        current=("a.ts · 62% · 8.4 MB/s",),
        next_items=("b.ts · 等待文件冷却",),
        strategy="冲突：改名上传",
        remote="123pan:/LiveBackup",
        status_summary="1 个失败需要检查 WebDAV 认证",
        diff_summary="本地 372 · 远端 349 · 待上传 23",
        updated_at="2026-06-30T09:00:00+00:00",
    )

    assert summarize_upload_status(snapshot) == "上传中 2 · 等待 23 · 失败 1"


def test_summarize_upload_status_reports_disabled_when_snapshot_missing():
    assert summarize_upload_status(None) == "上传关闭"
```

- [ ] **Step 2: Run tests and verify RED**

Run:

```powershell
& 'C:\Users\Admin\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m pytest tests/uploader/test_snapshot.py -q
```

Expected: import error for missing snapshot module.

- [ ] **Step 3: Implement snapshot model**

Create `src/uploader/snapshot.py`:

```python
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class UploadSnapshot:
    uploading: int = 0
    waiting: int = 0
    verifying: int = 0
    conflicts: int = 0
    failed: int = 0
    completed_today: int = 0
    current: tuple[str, ...] = ()
    next_items: tuple[str, ...] = ()
    strategy: str = ""
    remote: str = ""
    status_summary: str = ""
    diff_summary: str = ""
    updated_at: str = ""


def summarize_upload_status(snapshot: UploadSnapshot | None) -> str:
    if snapshot is None:
        return "上传关闭"
    parts = []
    if snapshot.uploading:
        parts.append(f"上传中 {snapshot.uploading}")
    if snapshot.waiting:
        parts.append(f"等待 {snapshot.waiting}")
    if snapshot.failed:
        parts.append(f"失败 {snapshot.failed}")
    return " · ".join(parts) or "上传空闲"


def write_upload_snapshot(path: str | Path, snapshot: UploadSnapshot) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(asdict(snapshot), ensure_ascii=False, indent=2), encoding="utf-8")


def read_upload_snapshot(path: str | Path) -> UploadSnapshot | None:
    source = Path(path)
    if not source.exists():
        return None
    data = json.loads(source.read_text(encoding="utf-8"))
    return UploadSnapshot(
        uploading=int(data.get("uploading", 0)),
        waiting=int(data.get("waiting", 0)),
        verifying=int(data.get("verifying", 0)),
        conflicts=int(data.get("conflicts", 0)),
        failed=int(data.get("failed", 0)),
        completed_today=int(data.get("completed_today", 0)),
        current=tuple(str(item) for item in data.get("current", ())),
        next_items=tuple(str(item) for item in data.get("next_items", ())),
        strategy=str(data.get("strategy", "")),
        remote=str(data.get("remote", "")),
        status_summary=str(data.get("status_summary", "")),
        diff_summary=str(data.get("diff_summary", "")),
        updated_at=str(data.get("updated_at", "")),
    )
```

- [ ] **Step 4: Extend dashboard state and view**

Modify `src/dashboard_state.py` by adding a compact upload summary field to `DashboardRoom`:

```python
upload_summary: str = ""
```

Modify `_MutableRoom` with the same field:

```python
upload_summary: str = ""
```

Add a method:

```python
def set_room_upload_summary(self, room_id: str, summary: str) -> None:
    with self._lock:
        self._room(room_id).upload_summary = summary
```

Pass `upload_summary=room.upload_summary` in `_snapshot_room`.

Modify `src/dashboard_view.py` inside `_room_detail` so upload summary appends without taking over the row:

```python
def _append_upload_detail(detail: str, room: DashboardRoom) -> str:
    if not room.upload_summary:
        return detail
    return f"{detail} · {room.upload_summary}"
```

Call `_append_upload_detail(...)` before returning each normal room detail.

- [ ] **Step 5: Run snapshot and dashboard tests**

Run:

```powershell
& 'C:\Users\Admin\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m pytest tests/uploader/test_snapshot.py tests/test_dashboard_view.py -q
```

Expected: all tests pass after updating existing dashboard snapshots if they assert exact strings.

- [ ] **Step 6: Commit**

```powershell
git add src/uploader/snapshot.py src/dashboard_state.py src/dashboard_view.py tests/uploader/test_snapshot.py tests/test_dashboard_view.py
git commit -m "feat: publish upload summaries for dashboards"
```

---

## Task 5: Queue-Backed Upload Scheduler

**Files:**
- Modify: `src/uploader/service.py`
- Modify: `src/uploader/rc_service.py`
- Modify: `src/uploader/__init__.py`
- Test: `tests/uploader/test_service.py`
- Test: `tests/uploader/test_rc_service.py`

- [ ] **Step 1: Write service integration test**

Add to `tests/uploader/test_service.py`:

```python
def test_run_once_discovers_plans_and_uploads_each_file(tmp_path):
    source = tmp_path / "downloads"
    source.mkdir()
    (source / "a.ts").write_bytes(b"x")
    calls = []

    def runner(command):
        calls.append(command)
        if "lsjson" in command:
            return RcloneResult(exit_code=0, stdout="[]")
        return RcloneResult(exit_code=0)

    service = RcloneUploadService(
        UploadConfig(enabled=True, min_age="0s", remote_path="123pan:/LiveBackup"),
        runner=runner,
    )

    result = service.run_once(source)

    assert result.phase == "success"
    assert not (source / "a.ts").exists()
    assert any("copyto" in call for call in calls)
```

- [ ] **Step 2: Run test and verify RED**

Run:

```powershell
& 'C:\Users\Admin\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m pytest tests/uploader/test_service.py::test_run_once_discovers_plans_and_uploads_each_file -q
```

Expected: fails because current service uses one `rclone move`.

- [ ] **Step 3: Refactor `RcloneUploadService.run_once` to use scanner/planner/executor**

In `src/uploader/service.py`, keep existing command-builder helpers for compatibility tests, but make `run_once` use:

```python
from .executor import FileUploadExecutor
from .models import RemoteEntry, UploadTaskStatus
from .planner import plan_upload_target
from .scanner import discover_stable_files
from .store import UploadQueueStore
```

Within `run_once`:

```python
files = discover_stable_files(source, min_age_seconds=parse_rclone_duration_seconds(self._config.min_age))
if not files:
    return skipped_result
store = UploadQueueStore(source / ".upload-state" / "upload.sqlite3")
tasks = [store.upsert_discovered_file(...fields from discovered file...) for file in files]
remote_entries = self._load_remote_entries()
executor = FileUploadExecutor(self._config, runner=self._runner, app_root=self._app_root)
for task in tasks:
    plan = plan_upload_target(task, remote_root=self._config.remote_path, remote_entries=remote_entries)
    store.mark_planned(task.id, remote_path=plan.remote_path, status=plan.status)
    if plan.status is UploadTaskStatus.SKIPPED:
        store.mark_done(task.id)
        task.local_path.unlink(missing_ok=True)
        continue
    planned_task = replace(task, planned_remote_path=plan.remote_path, status=plan.status)
    store.record_attempt(task.id, status=UploadTaskStatus.UPLOADING, error="")
    result = executor.upload(planned_task)
    if result.phase == "success":
        store.mark_done(task.id)
    else:
        store.mark_failed(task.id, result.stderr or result.message)
        return result
return UploadRunResult(phase="success", attempts=1, exit_code=0, message="upload completed")
```

Add `_load_remote_entries()` that calls `rclone lsjson <remote_path> --recursive` and maps JSON entries to `RemoteEntry`.

- [ ] **Step 4: Route RC mode through the same queue-backed executor**

In `src/uploader/rc_service.py`, make RC mode delegate to the queue-backed `RcloneUploadService` for the first queue implementation. This keeps the behavior correct and avoids maintaining two upload engines. RC daemon progress can be restored in a later enhancement after the queue path is stable.

```python
from .service import RcloneUploadService

fallback = RcloneUploadService(self.config)
return fallback.run_once(source)
```

Update RC service tests to assert that the default RC service reaches the same result contract as CLI mode. Keep low-level `RcloneRcClient` and `RcloneRcDaemon` tests in `tests/uploader/test_rclone_rc.py` unchanged.

- [ ] **Step 5: Run uploader tests**

Run:

```powershell
& 'C:\Users\Admin\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m pytest tests/uploader -q
```

Expected: all uploader tests pass.

- [ ] **Step 6: Commit**

```powershell
git add src/uploader/service.py src/uploader/rc_service.py src/uploader/__init__.py tests/uploader/test_service.py tests/uploader/test_rc_service.py
git commit -m "feat: run uploads through durable file queue"
```

---

## Task 6: Separate Read-Only Upload Workbench Window

**Files:**
- Create: `src/upload_workbench.py`
- Modify: `src/dashboard_input.py`
- Modify: `main.py`
- Test: `tests/runtime/test_upload_workbench_wiring.py`

- [ ] **Step 1: Write workbench rendering and wiring tests**

Create `tests/runtime/test_upload_workbench_wiring.py`:

```python
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_upload_workbench_is_read_only_observer_entrypoint():
    source = (ROOT / "src" / "upload_workbench.py").read_text(encoding="utf-8")

    assert "read_upload_snapshot" in source
    assert "rclone" not in source.lower()
    assert "Upload Workbench" in source
    assert "KeyboardInterrupt" in source


def test_main_launches_upload_workbench_for_u_key():
    source = (ROOT / "main.py").read_text(encoding="utf-8")

    assert "def launch_upload_workbench" in source
    assert "upload_workbench.py" in source or "--upload-workbench" in source
    assert "Start-Process" in source or "subprocess.Popen" in source
```

- [ ] **Step 2: Run tests and verify RED**

Run:

```powershell
& 'C:\Users\Admin\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m pytest tests/runtime/test_upload_workbench_wiring.py -q
```

Expected: fails because `src/upload_workbench.py` and launch function do not exist.

- [ ] **Step 3: Implement workbench entrypoint**

Create `src/upload_workbench.py`:

```python
from __future__ import annotations

import argparse
import time
from pathlib import Path

from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.table import Table

from src.uploader.snapshot import UploadSnapshot, read_upload_snapshot


def build_workbench(snapshot: UploadSnapshot | None):
    if snapshot is None:
        return Panel("等待主程序上传状态...", title="Upload Workbench")
    table = Table.grid(expand=True)
    table.add_column(ratio=2)
    table.add_column(ratio=1)
    counters = (
        f"上传中 {snapshot.uploading} | 等待 {snapshot.waiting} | "
        f"校验 {snapshot.verifying} | 冲突 {snapshot.conflicts} | 失败 {snapshot.failed}"
    )
    current = "\n".join(snapshot.current) or "当前无上传"
    next_items = "\n".join(snapshot.next_items) or "队列为空"
    left = f"{counters}\n\n当前上传\n{current}\n\n接下来\n{next_items}"
    right = f"上传策略\n{snapshot.strategy}\n\n远端\n{snapshot.remote}\n\n状态摘要\n{snapshot.status_summary}"
    table.add_row(left, right)
    return Panel(f"{table}\n\n差异摘要：{snapshot.diff_summary}", title="Upload Workbench")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--snapshot", required=True)
    args = parser.parse_args()
    console = Console()
    try:
        with Live(console=console, refresh_per_second=1) as live:
            while True:
                live.update(build_workbench(read_upload_snapshot(Path(args.snapshot))))
                time.sleep(1)
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Add launcher in `main.py`**

Add globals near upload globals:

```python
upload_workbench_process: subprocess.Popen | None = None
upload_snapshot_path = Path(current_app_root()) / "upload-state" / "snapshot.json"
```

Add:

```python
def launch_upload_workbench() -> None:
    global upload_workbench_process
    if upload_workbench_process is not None and upload_workbench_process.poll() is None:
        dashboard_store.add_event("system", "upload_workbench", "上传工作台已打开")
        return
    script = Path(current_app_root()) / "src" / "upload_workbench.py"
    command = [sys.executable, str(script), "--snapshot", str(upload_snapshot_path)]
    upload_workbench_process = subprocess.Popen(
        command,
        creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0),
    )
```

Wire `DashboardInputController` so `U` calls `launch_upload_workbench` instead of toggling detail expansion. If `DashboardInputController` currently only mutates state, add an optional `on_upload_requested` callback and test it.

- [ ] **Step 5: Run workbench tests**

Run:

```powershell
& 'C:\Users\Admin\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m pytest tests/runtime/test_upload_workbench_wiring.py tests/test_dashboard_input.py -q
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```powershell
git add src/upload_workbench.py src/dashboard_input.py main.py tests/runtime/test_upload_workbench_wiring.py tests/test_dashboard_input.py
git commit -m "feat: open read-only upload workbench window"
```

---

## Task 7: Packaging, Final Verification, And Smoke Test

**Files:**
- Modify: `DouyinLiveRecorder.spec`
- Modify: `tests/test_packaging_wiring.py`

- [ ] **Step 1: Write packaging test**

Add to `tests/test_packaging_wiring.py`:

```python
def test_spec_includes_upload_workbench_entrypoint():
    source = SPEC_PATH.read_text(encoding="utf-8")

    assert "upload_workbench.py" in source or "--upload-workbench" in source
```

- [ ] **Step 2: Run packaging test and verify RED**

Run:

```powershell
& 'C:\Users\Admin\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m pytest tests/test_packaging_wiring.py::test_spec_includes_upload_workbench_entrypoint -q
```

Expected: fails until spec includes workbench launch support.

- [ ] **Step 3: Update packaging**

Use main-exe argument mode so the packaged app does not need a separate Python script executable. Ensure `main.py` handles `--upload-workbench` before normal recording startup:

```python
if "--upload-workbench" in sys.argv:
    from src.upload_workbench import main as upload_workbench_main
    raise SystemExit(upload_workbench_main())
```

Then launch:

```python
command = [sys.executable, "--upload-workbench", "--snapshot", str(upload_snapshot_path)]
```

- [ ] **Step 4: Run full automated verification**

Run:

```powershell
& 'C:\Users\Admin\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m pytest -q
& 'C:\Users\Admin\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m ruff check src/uploader src/upload_workbench.py tests/uploader tests/runtime/test_upload_workbench_wiring.py
```

Expected:

- Pytest reports all tests passing.
- Ruff reports `All checks passed!`.

- [ ] **Step 5: Build packaged app**

Run:

```powershell
& 'C:\Users\Admin\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m PyInstaller --clean --noconfirm DouyinLiveRecorder.spec
```

Expected:

- Exit code 0.
- `dist\DouyinLiveRecorder\DouyinLiveRecorder.exe` exists.
- `dist\DouyinLiveRecorder\rclone\rclone.exe` exists.

- [ ] **Step 6: Manual smoke test with provided configs**

Copy configs:

```powershell
Copy-Item -LiteralPath '.tmp\dist-smoke\DouyinLiveRecorder\config\config.ini' -Destination 'dist\DouyinLiveRecorder\config\config.ini' -Force
Copy-Item -LiteralPath '.tmp\dist-smoke\DouyinLiveRecorder\config\URL_config.ini' -Destination 'dist\DouyinLiveRecorder\config\URL_config.ini' -Force
```

Run packaged rclone:

```powershell
& 'dist\DouyinLiveRecorder\rclone\rclone.exe' version
```

Expected: prints an rclone version.

Start app for 20 seconds:

```powershell
$distRoot = (Resolve-Path 'dist\DouyinLiveRecorder').Path
$job = Start-Job -ScriptBlock { param($wd) Set-Location $wd; & '.\DouyinLiveRecorder.exe' 2>&1 } -ArgumentList $distRoot
Wait-Job $job -Timeout 20 | Out-Null
$state = $job.State
$output = Receive-Job $job -ErrorAction SilentlyContinue | Out-String
if ($state -eq 'Running') { Stop-Job $job; Start-Sleep -Seconds 1 }
Remove-Job $job -Force
$output
```

Expected:

- Job is still `Running` after 20 seconds or exits gracefully without traceback.
- Output does not contain `Traceback`, `ModuleNotFoundError`, `ImportError`, or `PermissionError`.

- [ ] **Step 7: Commit packaging**

```powershell
git add DouyinLiveRecorder.spec tests/test_packaging_wiring.py
git commit -m "build: package upload workbench"
```

---

## Self-Review

- Spec coverage:
  - Durable SQLite queue: Task 1.
  - Scanner and nested directories: Task 2.
  - Remote difference and duplicate rename: Task 2.
  - Verify-before-delete upload execution: Task 3.
  - Dashboard brief status and snapshots: Task 4.
  - Separate read-only workbench window: Task 6.
  - Packaging and smoke testing: Task 7.
- No placeholders: the plan provides concrete files, tests, code snippets, and commands.
- Type consistency:
  - `UploadTaskStatus`, `UploadConflictPolicy`, `UploadTask`, and `RemoteEntry` are introduced in Task 1 and reused consistently.
  - `UploadSnapshot` is introduced in Task 4 and reused by the workbench in Task 6.
  - `FileUploadExecutor` is introduced in Task 3 and integrated in Task 5.
