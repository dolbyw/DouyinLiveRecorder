# Dashboard Disk Usage Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Show cached recording-directory usage as `已占用` and drive free space as `剩余` in the dashboard header without scanning disk every UI refresh.

**Architecture:** Extend `DashboardConfig` with a cached recording directory size in bytes. Add a small cache helper in `main.py` that scans only the active save directory when stale or when the path changes. Keep rendering inside the existing `health` model so Rich and plain dashboards continue sharing one view model.

**Tech Stack:** Python 3.12, dataclasses, pathlib, shutil, pytest, existing Rich terminal dashboard.

---

## File Structure

- Modify `src/dashboard_state.py`: add `recordings_size_bytes: int | None` to `DashboardConfig`.
- Modify `src/dashboard_view.py`: render `已占用` and `剩余` health items using existing `_format_bytes`.
- Modify `main.py`: add low-frequency recording directory size cache and pass cached size into `DashboardConfig`.
- Modify `tests/test_dashboard_view.py`: verify health labels and unknown value handling.
- Modify `tests/test_cli_ui.py`: update expected rendered dashboard text.
- Add or modify `tests/test_dashboard_disk_usage.py`: test cache behavior without touching the real downloads directory.

### Task 1: Dashboard State And View

**Files:**
- Modify: `src/dashboard_state.py`
- Modify: `src/dashboard_view.py`
- Test: `tests/test_dashboard_view.py`
- Test: `tests/test_cli_ui.py`

- [ ] **Step 1: Write failing dashboard view tests**

Add to `tests/test_dashboard_view.py`:

```python
def test_dashboard_health_shows_used_and_remaining_disk(snapshot):
    snapshot = replace(
        snapshot,
        config=replace(
            snapshot.config,
            recordings_size_bytes=128_600_000_000,
            disk_free_gb=424.3,
        ),
    )

    view = build_dashboard_view(snapshot, width=140, height=40, room_mode=RoomListMode.COMPACT)

    assert [(item.label, item.value) for item in view.health[:3]] == [
        ("FFmpeg", "正常"),
        ("已占用", "128.6 GB"),
        ("剩余", "424.3 GB"),
    ]


def test_dashboard_health_shows_unknown_recording_size(snapshot):
    snapshot = replace(
        snapshot,
        config=replace(snapshot.config, recordings_size_bytes=None),
    )

    view = build_dashboard_view(snapshot, width=140, height=40, room_mode=RoomListMode.COMPACT)

    used = next(item for item in view.health if item.label == "已占用")
    assert used.value == "未知"
```

Update `tests/test_cli_ui.py::dashboard_snapshot` so `DashboardConfig(...)` includes:

```python
recordings_size_bytes=128_600_000_000,
```

Update `tests/test_cli_ui.py::test_wide_dashboard_matches_approved_full_width_hierarchy` expected text tuple to include:

```python
"已占用",
"剩余",
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```powershell
pytest tests/test_dashboard_view.py tests/test_cli_ui.py -q
```

Expected: failure because `DashboardConfig` does not accept `recordings_size_bytes` yet or health labels are still `磁盘`.

- [ ] **Step 3: Add state and rendering support**

In `src/dashboard_state.py`, change `DashboardConfig` to:

```python
@dataclass(frozen=True, slots=True)
class DashboardConfig:
    save_format: str = "-"
    quality: str = "-"
    split_seconds: int | None = None
    poll_seconds: int = 0
    max_requests: int = 0
    use_proxy: bool = False
    convert_to_mp4: bool = False
    save_path: str = "-"
    disk_free_gb: float | None = None
    recordings_size_bytes: int | None = None
```

In `src/dashboard_view.py`, replace the current `磁盘` health entry with:

```python
HealthView(
    "已占用",
    _format_bytes(snapshot.config.recordings_size_bytes)
    if snapshot.config.recordings_size_bytes is not None
    else "未知",
    True,
),
HealthView(
    "剩余",
    f"{snapshot.config.disk_free_gb:.1f} GB" if snapshot.config.disk_free_gb is not None else "未知",
    snapshot.config.disk_free_gb is None or snapshot.config.disk_free_gb > 1,
),
```

- [ ] **Step 4: Run dashboard view tests**

Run:

```powershell
pytest tests/test_dashboard_view.py tests/test_cli_ui.py -q
```

Expected: all selected tests pass.

- [ ] **Step 5: Commit or record changes**

This workspace is not a git repository. Skip commit and keep the file changes in place.

### Task 2: Cached Recording Directory Size

**Files:**
- Modify: `main.py`
- Test: `tests/test_dashboard_disk_usage.py`

- [ ] **Step 1: Write failing cache tests**

Create `tests/test_dashboard_disk_usage.py`:

```python
from pathlib import Path

import main


def test_recording_directory_size_cache_reuses_fresh_value(tmp_path, monkeypatch):
    calls = []

    def fake_scan(path: Path) -> int:
        calls.append(path)
        return 123

    monkeypatch.setattr(main, "_scan_recording_directory_size", fake_scan)
    cache = main.RecordingDirectorySizeCache(ttl_seconds=300)
    save_path = tmp_path / "downloads"

    assert cache.get(save_path, now=100.0) == 123
    assert cache.get(save_path, now=200.0) == 123
    assert calls == [save_path]


def test_recording_directory_size_cache_refreshes_after_ttl(tmp_path, monkeypatch):
    sizes = [123, 456]

    def fake_scan(_path: Path) -> int:
        return sizes.pop(0)

    monkeypatch.setattr(main, "_scan_recording_directory_size", fake_scan)
    cache = main.RecordingDirectorySizeCache(ttl_seconds=300)
    save_path = tmp_path / "downloads"

    assert cache.get(save_path, now=100.0) == 123
    assert cache.get(save_path, now=401.0) == 456


def test_recording_directory_size_cache_refreshes_when_path_changes(tmp_path, monkeypatch):
    calls = []

    def fake_scan(path: Path) -> int:
        calls.append(path)
        return len(calls)

    monkeypatch.setattr(main, "_scan_recording_directory_size", fake_scan)
    cache = main.RecordingDirectorySizeCache(ttl_seconds=300)

    assert cache.get(tmp_path / "one", now=100.0) == 1
    assert cache.get(tmp_path / "two", now=101.0) == 2


def test_scan_recording_directory_size_reads_file_metadata_only(tmp_path):
    downloads = tmp_path / "downloads"
    downloads.mkdir()
    (downloads / "a.ts").write_bytes(b"x" * 10)
    nested = downloads / "room"
    nested.mkdir()
    (nested / "b.mp4").write_bytes(b"x" * 15)

    assert main._scan_recording_directory_size(downloads) == 25
```

- [ ] **Step 2: Run cache tests to verify they fail**

Run:

```powershell
pytest tests/test_dashboard_disk_usage.py -q
```

Expected: import or attribute failure because `RecordingDirectorySizeCache` and `_scan_recording_directory_size` do not exist.

- [ ] **Step 3: Add cache implementation**

In `main.py`, near dashboard globals after `dashboard_input`, add:

```python
DASHBOARD_RECORDING_SIZE_TTL_SECONDS = 300.0


class RecordingDirectorySizeCache:
    def __init__(self, *, ttl_seconds: float = DASHBOARD_RECORDING_SIZE_TTL_SECONDS) -> None:
        self._ttl_seconds = ttl_seconds
        self._path: Path | None = None
        self._size_bytes: int | None = None
        self._checked_at: float | None = None
        self._lock = threading.RLock()

    def get(self, save_path: str | Path, *, now: float | None = None) -> int | None:
        timestamp = time.monotonic() if now is None else now
        path = Path(save_path)
        with self._lock:
            if (
                self._path == path
                and self._checked_at is not None
                and timestamp - self._checked_at < self._ttl_seconds
            ):
                return self._size_bytes
            try:
                size_bytes = _scan_recording_directory_size(path)
            except OSError:
                size_bytes = None
            self._path = path
            self._size_bytes = size_bytes
            self._checked_at = timestamp
            return size_bytes


def _scan_recording_directory_size(save_path: Path) -> int:
    total = 0
    if not save_path.exists():
        return 0
    for candidate in save_path.rglob("*"):
        try:
            if candidate.is_file():
                total += candidate.stat().st_size
        except OSError:
            continue
    return total


recording_size_cache = RecordingDirectorySizeCache()
```

- [ ] **Step 4: Run cache tests**

Run:

```powershell
pytest tests/test_dashboard_disk_usage.py -q
```

Expected: all cache tests pass.

- [ ] **Step 5: Commit or record changes**

This workspace is not a git repository. Skip commit and keep the file changes in place.

### Task 3: Wire Cache Into Dashboard Configuration

**Files:**
- Modify: `main.py`
- Test: `tests/runtime/test_main_runtime_wiring.py`
- Test: `tests/test_dashboard_disk_usage.py`

- [ ] **Step 1: Add wiring assertion**

Add to `tests/runtime/test_main_runtime_wiring.py`:

```python
def test_dashboard_configuration_uses_cached_recording_directory_size():
    source = Path("main.py").read_text(encoding="utf-8")

    assert "recording_size_cache.get(save_path)" in source
    assert "recordings_size_bytes=recordings_size_bytes" in source
```

Ensure `Path` is already imported in that test file. If it is not, add:

```python
from pathlib import Path
```

- [ ] **Step 2: Run wiring test to verify it fails**

Run:

```powershell
pytest tests/runtime/test_main_runtime_wiring.py::test_dashboard_configuration_uses_cached_recording_directory_size -q
```

Expected: failure because the cache is not wired into `refresh_dashboard_configuration`.

- [ ] **Step 3: Wire cached value into config**

In `main.py::refresh_dashboard_configuration`, after resolving `save_path`, add:

```python
    recordings_size_bytes = recording_size_cache.get(save_path)
```

Then add the value to `DashboardConfig(...)`:

```python
            recordings_size_bytes=recordings_size_bytes,
```

- [ ] **Step 4: Run focused tests**

Run:

```powershell
pytest tests/test_dashboard_disk_usage.py tests/test_dashboard_view.py tests/test_cli_ui.py tests/runtime/test_main_runtime_wiring.py::test_dashboard_configuration_uses_cached_recording_directory_size -q
```

Expected: all selected tests pass.

- [ ] **Step 5: Run broader dashboard/runtime tests**

Run:

```powershell
pytest tests/test_dashboard_state.py tests/test_dashboard_view.py tests/test_cli_ui.py tests/runtime/test_main_runtime_wiring.py -q
```

Expected: all selected tests pass.

- [ ] **Step 6: Commit or record changes**

This workspace is not a git repository. Skip commit and keep the file changes in place.
