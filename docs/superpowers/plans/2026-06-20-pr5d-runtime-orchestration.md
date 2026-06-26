# PR5D Runtime Orchestration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the pure asyncio orchestration layer that repeatedly reconciles URL configuration and monitors each room while holding network capacity only during platform probes.

**Architecture:** A pure URL-config parser converts existing lines to immutable `RoomSpec` values without mutating files. `RoomMonitor` performs one limited async probe, releases the limiter before invoking potentially long recording work, and loops with cancellable delays. `RuntimeCoordinator` loads configuration off the event loop, reconciles scheduler tasks, and refreshes the limiter when runtime configuration changes.

**Tech Stack:** Python 3.11 asyncio, existing config parser/platform contracts, pytest-asyncio, Ruff

---

## Locked API

```python
@dataclass(frozen=True, slots=True)
class RoomConfigSnapshot:
    desired_rooms: tuple[RoomSpec, ...]
    commented_room_ids: tuple[str, ...]
    rejected_lines: tuple[str, ...]

def parse_room_config_lines(lines: Iterable[str], default_quality: QualityLevel) -> RoomConfigSnapshot: ...

@dataclass(frozen=True, slots=True)
class ProbeResult:
    is_live: bool
    payload: Mapping[str, object] = field(default_factory=dict)

class RoomMonitor:
    async def run_once(self, room: RoomSpec) -> ProbeResult: ...
    async def run(self, room: RoomSpec) -> None: ...

@dataclass(frozen=True, slots=True)
class RuntimeConfig:
    rooms: tuple[RoomSpec, ...]
    max_requests: int

class RuntimeCoordinator:
    async def refresh_once(self) -> RoomChangeSet: ...
    async def run(self) -> None: ...
```

### Task 1: Pure URL configuration snapshot

**Files:**
- Create: `src/runtime/config.py`
- Create: `tests/runtime/test_runtime_config.py`
- Modify: `src/runtime/__init__.py`

- [ ] Write failing tests with active, commented, duplicate, blank, and unsupported URL lines. Assert first occurrence ordering, normalized URLs, typed qualities, commented IDs, and rejected raw lines.
- [ ] Run focused pytest and verify RED because `parse_room_config_lines` is absent.
- [ ] Implement the parser by composing `parse_url_config_entry()` and `normalize_url_config_entry()`; do not edit files or silently activate comments.
- [ ] Run focused pytest and verify GREEN.

### Task 2: Probe-limited room monitor

**Files:**
- Create: `src/runtime/monitor.py`
- Create: `tests/runtime/test_monitor.py`
- Modify: `src/runtime/__init__.py`

- [ ] Write failing tests proving offline rooms skip recording, live rooms invoke recording after the limiter permit is released, and cancellation interrupts loop delay.
- [ ] Run focused pytest and verify RED because `RoomMonitor` is absent.
- [ ] Implement `run_once()` so only `probe(room)` is inside `async with limiter`; call `record(room, result)` outside. Implement `run()` as repeated `run_once()` plus `asyncio.sleep(poll_interval)` with positive interval validation.
- [ ] Run focused pytest and verify GREEN.

### Task 3: Runtime configuration coordinator

**Files:**
- Create: `src/runtime/coordinator.py`
- Create: `tests/runtime/test_coordinator.py`
- Modify: `src/runtime/__init__.py`

- [ ] Write failing tests proving `refresh_once()` calls a synchronous loader through `asyncio.to_thread`, resizes `AdjustableLimiter`, and reconciles rooms; prove repeated identical refresh creates no duplicate scheduler task.
- [ ] Run focused pytest and verify RED because `RuntimeCoordinator` is absent.
- [ ] Implement `RuntimeConfig`, loader injection, `refresh_once()`, and cancellable periodic `run()` with positive refresh interval validation.
- [ ] Run focused pytest and verify GREEN.

### Task 4: Verification and roadmap

**Files:**
- Modify: `docs/项目优化实施路线图.md`

- [ ] Record orchestration-layer completion and keep the four-platform/legacy compatibility boundary explicit.
- [ ] Run runtime and full pytest with workspace-local basetemp directories.
- [ ] Run Ruff check, Ruff format check, and `py_compile` over all runtime modules.

Expected final evidence: all commands exit zero. Do not commit because this workspace has no Git metadata.
