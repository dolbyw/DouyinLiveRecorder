# Recording Reconnect and Room Density Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prevent brief HTTP input interruptions from fragmenting recordings without infinite reconnects, retain safe FFmpeg diagnostics, correct the event wording, and show ten rooms in compact mode.

**Architecture:** Keep application-level probing as the final recovery mechanism. Apply finite reconnect policy inside `FFmpegBuilder`, drain FFmpeg output in `RecorderProcess`, carry a bounded diagnostic tail through `ProcessResult`, and keep UI changes inside the presentation model.

**Tech Stack:** Python 3.11+, subprocess, threading, deque, Rich, pytest, PyInstaller.

**Repository note:** The workspace has no `.git` directory, so verification checkpoints replace commits.

---

### Task 1: Correct HTTP Input Reconnect Options

**Files:**
- Modify: `tests/recorder/test_ffmpeg_builder.py`
- Modify: `src/recorder/ffmpeg_builder.py`

- [ ] Add a failing test asserting `-reconnect 1`, EOF/streamed/network flags, delay/retry values, and that every reconnect option occurs before `-i`.
- [ ] Run `pytest tests/recorder/test_ffmpeg_builder.py -q` and verify the test fails against the current command.
- [ ] Move explicit finite reconnect options into the input-option block immediately before `-i`.
- [ ] Re-run the focused test and verify it passes.

### Task 2: Capture a Bounded FFmpeg Output Tail

**Files:**
- Modify: `src/recorder/models.py`
- Modify: `src/recorder/process.py`
- Modify: `tests/recorder/test_process.py`

- [ ] Add failing tests with a fake readable stdout stream proving `Popen` receives `stdout=PIPE`, output is drained, and `ProcessResult.output_tail` retains only the final configured lines.
- [ ] Run `pytest tests/recorder/test_process.py -q` and verify RED.
- [ ] Add `output_tail: tuple[str, ...] = ()` to `ProcessResult`.
- [ ] Start a daemon drain thread after process creation, append normalized non-empty lines to `deque(maxlen=50)`, and join briefly after exit/stop before returning the result.
- [ ] Re-run focused process and recorder tests.

### Task 3: Correct Semantics, Diagnostics, and Compact Density

**Files:**
- Modify: `src/dashboard_view.py`
- Modify: `main.py`
- Modify: `tests/test_dashboard_view.py`
- Modify: `tests/runtime/test_main_runtime_wiring.py`

- [ ] Add failing tests asserting `recording_finished` renders as `录制结束`, compact mode shows ten rooms at sufficient height, and short recordings log `output_tail` diagnostics.
- [ ] Run focused tests and verify RED.
- [ ] Change the event mapping and compact row cap from six to ten.
- [ ] In the recording result boundary, calculate elapsed recording duration; when completion is under 30 seconds, log return code plus sanitized output tail. Never log the command, headers, source URL, or cookies.
- [ ] Re-run focused dashboard and wiring tests.

### Task 4: Full Verification and Packaging

**Files:**
- Verify only.

- [ ] Run Ruff on changed files.
- [ ] Run the complete pytest suite.
- [ ] Build with `pyinstaller --noconfirm --clean DouyinLiveRecorder.spec`.
- [ ] Run an isolated no-room packaged startup for eight seconds and verify zero stderr/critical-log matches.
- [ ] Report evidence and the executable path.
