# PR5E Platform Probe and Runtime Runner Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Connect registered async platform adapters to `RoomMonitor` and provide a signal-driven runner that always performs ordered runtime shutdown.

**Architecture:** `RegisteredPlatformProbe` converts `RoomSpec` quality/context into the existing platform dispatcher and returns `ProbeResult`, while explicitly distinguishing unsupported legacy URLs from adapter failures. `RuntimeRunner` owns the coordinator task and shutdown event; an injectable signal installer makes OS signal behavior testable and guarantees `RuntimeApp.shutdown()` runs on signals, coordinator completion, failure, or cancellation.

**Tech Stack:** Python 3.11 asyncio/signals, existing platform registry, pytest-asyncio, Ruff

---

### Task 1: Registered async platform probe

**Files:**
- Create: `src/runtime/platform_probe.py`
- Create: `tests/runtime/test_platform_probe.py`
- Modify: `src/runtime/__init__.py`

- [ ] Write failing tests proving quality-code conversion and context propagation for a matched adapter, offline/live payload conversion, explicit `LegacyPlatformRequired` for unmatched URLs, and `PlatformProbeError` preserving adapter failures.
- [ ] Run focused pytest and verify RED because the probe module is absent.
- [ ] Implement `PlatformProbeSettings`, a settings provider callback, quality mapping, and `RegisteredPlatformProbe.__call__()` using `try_resolve()`.
- [ ] Run focused pytest and verify GREEN.

### Task 2: Signal-driven runtime runner

**Files:**
- Create: `src/runtime/runner.py`
- Create: `tests/runtime/test_runner.py`
- Modify: `src/runtime/__init__.py`

- [ ] Write failing tests with injected fake signal installation proving a signal cancels the coordinator and shuts down the app once; prove coordinator exceptions still shut down then propagate.
- [ ] Run focused pytest and verify RED because `RuntimeRunner` is absent.
- [ ] Implement `install_shutdown_signal_handlers()`, cleanup restoration, `RuntimeRunner.request_shutdown()`, and `run()` using explicit tasks and `asyncio.wait(FIRST_COMPLETED)`.
- [ ] Run focused pytest and verify GREEN.

### Task 3: Verification and roadmap

**Files:**
- Modify: `docs/项目优化实施路线图.md`

- [ ] Record platform-probe and signal-runner completion while leaving `main.py` selection/cutover outstanding.
- [ ] Run runtime and full pytest with local basetemp directories.
- [ ] Run Ruff, format check, and `py_compile` over runtime modules.

Expected final evidence: all commands exit zero. Do not commit because this workspace has no Git metadata.
