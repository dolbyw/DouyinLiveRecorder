# PR5F Main Hybrid Cutover Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Activate the unified async runtime for registered platforms from `main.py` while preserving the legacy scheduler for all other platforms.

**Architecture:** `ThreadedRuntimeHost` runs exactly one asyncio event loop for registered rooms and exposes thread-safe shutdown to the main thread. `start_record()` gains an injected resolved-payload/single-cycle mode so async probing never falls back to thread-local `asyncio.run()`; the existing recording pipeline remains unchanged. The legacy configuration loop excludes URLs matched by `default_registry`, preserving all other platform behavior.

**Tech Stack:** Python 3.11 asyncio/threading, existing runtime/platform/recorder modules, pytest, Ruff

---

### Task 1: Thread-safe runtime host

**Files:**
- Create: `src/runtime/thread_host.py`
- Create: `tests/runtime/test_thread_host.py`
- Modify: `src/runtime/__init__.py`

- [ ] Write failing tests proving start creates one background loop, duplicate start is rejected, thread-safe shutdown reaches the runner, join completes, and runner failures are exposed.
- [ ] Run focused pytest and verify RED.
- [ ] Implement `ThreadedRuntimeHost` around a runner factory, a readiness event, `loop.call_soon_threadsafe()`, and captured failure state.
- [ ] Run focused pytest and verify GREEN.

### Task 2: Single-cycle resolved recording seam

**Files:**
- Modify: `main.py`
- Create: `tests/runtime/test_main_runtime_wiring.py`

- [ ] Write source-contract tests proving `start_record` accepts `resolved_once`, `single_cycle`, `stop_token`, and `session_state`; resolved mode constructs a handled dispatch result without calling `run_async`; single-cycle branches return before legacy sleep/re-probe; pipeline stop callbacks include the token.
- [ ] Run focused pytest and verify RED.
- [ ] Modify `start_record()` minimally: inject the first dispatcher result, preserve push/run-once state in a per-room dictionary, route stop callbacks through the token, and return after one processed cycle.
- [ ] Run focused pytest plus `py_compile main.py` and verify GREEN.

### Task 3: Hybrid runtime bootstrap in main

**Files:**
- Modify: `main.py`
- Modify: `tests/runtime/test_main_runtime_wiring.py`

- [ ] Add failing source-contract tests proving registered URLs are excluded from legacy thread creation, runtime loader selects registered rooms, runtime recording callback uses `RecordingExecutor`, the host starts once, and signal handling requests host shutdown.
- [ ] Run focused tests and verify RED.
- [ ] Add runtime builder/loader/callback functions, create `StateStore`, limiter, registered probe, monitor, scheduler, coordinator, recording executor, app and runner; start `ThreadedRuntimeHost` once after initial configuration; keep an environment kill switch `DLR_ASYNC_RUNTIME=0` for rollback.
- [ ] Update SIGTERM handling to request runtime shutdown before exiting and skip registered URLs in legacy thread creation.
- [ ] Run focused tests and syntax compilation.

### Task 4: Verification and roadmap

**Files:**
- Modify: `docs/项目优化实施路线图.md`

- [ ] Mark hybrid main cutover complete and document that unregistered platforms remain legacy.
- [ ] Run runtime tests, full pytest, focused Ruff for runtime and PR5 wiring, format check, and `py_compile main.py src/runtime/*.py`.

Expected final evidence: all commands exit zero. Do not commit because this workspace has no Git metadata.
