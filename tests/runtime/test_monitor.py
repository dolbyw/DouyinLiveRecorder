import asyncio

import pytest

from src.models import QualityLevel
from src.runtime import AdjustableLimiter, ProbeResult, RoomMonitor, RoomSpec


def room() -> RoomSpec:
    return RoomSpec("https://live.douyin.com/1", QualityLevel.ORIGIN)


@pytest.mark.asyncio
async def test_offline_probe_skips_recording():
    recorded = False

    async def probe(_room: RoomSpec) -> ProbeResult:
        return ProbeResult(is_live=False)

    async def record(_room: RoomSpec, _result: ProbeResult) -> None:
        nonlocal recorded
        recorded = True

    monitor = RoomMonitor(AdjustableLimiter(1), probe, record, poll_interval=1)

    result = await monitor.run_once(room())

    assert result.is_live is False
    assert recorded is False


@pytest.mark.asyncio
async def test_offline_handler_runs_after_probe_releases_limiter():
    limiter = AdjustableLimiter(1)
    active_during_offline = -1

    async def probe(_room: RoomSpec) -> ProbeResult:
        return ProbeResult(is_live=False)

    async def record(_room: RoomSpec, _result: ProbeResult) -> None:
        raise AssertionError("offline room must not record")

    async def offline(_room: RoomSpec, _result: ProbeResult) -> None:
        nonlocal active_during_offline
        active_during_offline = limiter.active_count

    monitor = RoomMonitor(limiter, probe, record, offline=offline, poll_interval=1)

    await monitor.run_once(room())

    assert active_during_offline == 0


@pytest.mark.asyncio
async def test_live_recording_runs_after_probe_releases_limiter():
    limiter = AdjustableLimiter(1)
    active_during_record = -1

    async def probe(_room: RoomSpec) -> ProbeResult:
        assert limiter.active_count == 1
        return ProbeResult(is_live=True, payload={"record_url": "https://stream.example/live.flv"})

    async def record(_room: RoomSpec, _result: ProbeResult) -> None:
        nonlocal active_during_record
        active_during_record = limiter.active_count

    monitor = RoomMonitor(limiter, probe, record, poll_interval=1)

    await monitor.run_once(room())

    assert active_during_record == 0


@pytest.mark.asyncio
async def test_success_callback_clears_error_after_healthy_cycle():
    callbacks: list[tuple[bool, int]] = []

    async def probe(_room: RoomSpec) -> ProbeResult:
        return ProbeResult(is_live=False)

    async def record(_room: RoomSpec, _result: ProbeResult) -> None:
        raise AssertionError("offline room must not record")

    async def on_success(_room: RoomSpec, result: ProbeResult) -> None:
        callbacks.append((result.is_live, len(callbacks)))

    monitor = RoomMonitor(
        AdjustableLimiter(1),
        probe,
        record,
        on_success=on_success,
        poll_interval=1,
    )

    await monitor.run_once(room())

    assert callbacks == [(False, 0)]


@pytest.mark.asyncio
async def test_cancellation_interrupts_monitor_delay():
    probed = asyncio.Event()

    async def probe(_room: RoomSpec) -> ProbeResult:
        probed.set()
        return ProbeResult(is_live=False)

    async def record(_room: RoomSpec, _result: ProbeResult) -> None:
        raise AssertionError("offline room must not record")

    monitor = RoomMonitor(AdjustableLimiter(1), probe, record, poll_interval=60)
    task = asyncio.create_task(monitor.run(room()))
    await probed.wait()
    await asyncio.sleep(0)

    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task


@pytest.mark.asyncio
async def test_probe_waits_for_pacer_before_acquiring_concurrency():
    limiter = AdjustableLimiter(1)
    events = []

    class CapturingPacer:
        async def wait_turn(self, room_id):
            events.append(f"pace:{room_id}:{limiter.active_count}")

    async def probe(_room: RoomSpec) -> ProbeResult:
        events.append(f"probe:{limiter.active_count}")
        return ProbeResult(is_live=False)

    async def record(_room: RoomSpec, _result: ProbeResult) -> None:
        raise AssertionError("offline room must not record")

    monitor = RoomMonitor(
        limiter,
        probe,
        record,
        pacer=CapturingPacer(),
        poll_interval=1,
    )

    await monitor.run_once(room())

    assert events == [f"pace:{room().room_id}:0", "probe:1"]


@pytest.mark.asyncio
async def test_probe_lifecycle_callbacks_wrap_probe_after_pacing():
    events = []

    class ImmediatePacer:
        async def wait_turn(self, _room_id):
            events.append("pace")

    async def started(_room):
        events.append("started")

    async def finished(_room):
        events.append("finished")

    async def probe(_room):
        events.append("probe")
        return ProbeResult(is_live=False)

    async def record(_room, _result):
        raise AssertionError("offline room must not record")

    monitor = RoomMonitor(
        AdjustableLimiter(1),
        probe,
        record,
        pacer=ImmediatePacer(),
        on_probe_started=started,
        on_probe_finished=finished,
        poll_interval=1,
    )

    await monitor.run_once(room())

    assert events == ["pace", "started", "probe", "finished"]


@pytest.mark.asyncio
async def test_probe_finish_callback_runs_when_probe_fails():
    finished_rooms = []

    async def probe(_room):
        raise RuntimeError("probe failed")

    async def record(_room, _result):
        raise AssertionError("failed probe must not record")

    async def finished(spec):
        finished_rooms.append(spec.room_id)

    monitor = RoomMonitor(
        AdjustableLimiter(1),
        probe,
        record,
        on_probe_finished=finished,
        poll_interval=1,
    )

    with pytest.raises(RuntimeError, match="probe failed"):
        await monitor.run_once(room())

    assert finished_rooms == [room().room_id]
