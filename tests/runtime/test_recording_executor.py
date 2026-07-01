import asyncio
import threading
import time

import pytest

from src.runtime.recording import RecordingExecutor


@pytest.mark.asyncio
async def test_recording_operation_does_not_block_event_loop():
    release = threading.Event()
    executor = RecordingExecutor(max_workers=1)

    def operation(_token):
        release.wait()
        return "done"

    task = asyncio.create_task(executor.run("room-1", operation))
    await asyncio.sleep(0.01)

    assert executor.active_room_ids == frozenset({"room-1"})

    release.set()
    assert await task == "done"
    await executor.close(1)


@pytest.mark.asyncio
async def test_duplicate_active_room_is_rejected():
    release = threading.Event()
    executor = RecordingExecutor(max_workers=1)
    first = asyncio.create_task(executor.run("room-1", lambda _token: release.wait()))
    await asyncio.sleep(0.01)

    with pytest.raises(RuntimeError, match="already recording"):
        await executor.run("room-1", lambda _token: None)

    release.set()
    await first
    await executor.close(1)


@pytest.mark.asyncio
async def test_recordings_queue_when_worker_limit_is_reached():
    first_started = threading.Event()
    second_started = threading.Event()
    first_release = threading.Event()
    second_release = threading.Event()
    executor = RecordingExecutor(max_workers=1)

    def first(_token):
        first_started.set()
        first_release.wait()

    def second(_token):
        second_started.set()
        second_release.wait()

    first_task = asyncio.create_task(executor.run("room-1", first))
    second_task = asyncio.create_task(executor.run("room-2", second))
    await asyncio.sleep(0.02)

    try:
        assert first_started.wait(0.2)
        assert not second_started.wait(0.05)
        first_release.set()
        await first_task
        assert second_started.wait(0.2)
    finally:
        first_release.set()
        second_release.set()
        if not first_task.done():
            await first_task
        await second_task
        await executor.close(1)


@pytest.mark.asyncio
async def test_cancelling_async_wait_requests_room_stop():
    observed = threading.Event()
    release = threading.Event()
    executor = RecordingExecutor(max_workers=1)

    def operation(token):
        while not token.room_stop_requested and not release.is_set():
            time.sleep(0.001)
        if token.room_stop_requested:
            observed.set()

    task = asyncio.create_task(executor.run("room-1", operation))
    await asyncio.sleep(0.01)
    task.cancel()

    try:
        with pytest.raises(asyncio.CancelledError):
            await task
        assert observed.wait(0.2)
    finally:
        release.set()
        await executor.close(1)


@pytest.mark.asyncio
async def test_close_requests_shutdown_and_reports_unfinished_operation():
    shutdown_seen = threading.Event()
    executor = RecordingExecutor(max_workers=1)

    def operation(token):
        deadline = time.monotonic() + 0.1
        while not token.shutdown_requested and time.monotonic() < deadline:
            time.sleep(0.001)
        if token.shutdown_requested:
            shutdown_seen.set()
        time.sleep(0.05)

    task = asyncio.create_task(executor.run("room-1", operation))
    await asyncio.sleep(0.01)

    unfinished = await executor.close(0.01)

    assert shutdown_seen.wait(0.2)
    assert unfinished == ("room-1",)
    await task


@pytest.mark.asyncio
async def test_request_room_stop_targets_only_requested_room():
    first_stopped = threading.Event()
    first_release = threading.Event()
    second_release = threading.Event()
    executor = RecordingExecutor(max_workers=2)

    def first(token):
        while not token.room_stop_requested and not first_release.is_set():
            time.sleep(0.001)
        if token.room_stop_requested:
            first_stopped.set()

    def second(_token):
        second_release.wait()

    first_task = asyncio.create_task(executor.run("room-1", first))
    second_task = asyncio.create_task(executor.run("room-2", second))
    await asyncio.sleep(0.01)

    try:
        assert executor.request_room_stop("room-1") is True
        assert executor.request_room_stop("missing") is False
        assert first_stopped.wait(0.2)
        assert not second_task.done()
    finally:
        first_release.set()
        second_release.set()
        await first_task
        await second_task
        await executor.close(1)


@pytest.mark.asyncio
async def test_cancellation_remains_cancelled_when_operation_fails_while_stopping():
    executor = RecordingExecutor(max_workers=1)

    def operation(token):
        while not token.room_stop_requested:
            time.sleep(0.001)
        raise RuntimeError("failed during stop")

    task = asyncio.create_task(executor.run("room-1", operation))
    await asyncio.sleep(0.01)
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task

    await executor.close(1)
