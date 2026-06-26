import pytest

from src.runtime import RuntimeApp


class FakeState:
    def __init__(self, events: list[str]) -> None:
        self.events = events

    def request_shutdown(self) -> None:
        self.events.append("state.shutdown")


class FakeScheduler:
    def __init__(self, events: list[str], *, fail: bool = False) -> None:
        self.events = events
        self.fail = fail

    async def stop_all(self) -> None:
        self.events.append("scheduler.stop")
        if self.fail:
            raise RuntimeError("scheduler failed")


class FakeRecordings:
    def __init__(self, events: list[str]) -> None:
        self.events = events

    def request_shutdown(self) -> None:
        self.events.append("recordings.stop")

    async def close(self, timeout: float) -> tuple[str, ...]:
        self.events.append(f"recordings.close:{timeout:g}")
        return ("room-stuck",)


@pytest.mark.asyncio
async def test_shutdown_uses_fixed_order_and_is_idempotent():
    events: list[str] = []

    async def close_http() -> None:
        events.append("http.close")

    app = RuntimeApp(
        FakeState(events),
        FakeScheduler(events),
        FakeRecordings(events),
        close_http=close_http,
    )

    first = await app.shutdown(timeout=3)
    second = await app.shutdown(timeout=3)

    assert first is second
    assert first.unfinished_recordings == ("room-stuck",)
    assert events == [
        "state.shutdown",
        "recordings.stop",
        "scheduler.stop",
        "recordings.close:3",
        "http.close",
    ]


@pytest.mark.asyncio
async def test_shutdown_closes_recordings_and_http_when_scheduler_stop_fails():
    events: list[str] = []

    async def close_http() -> None:
        events.append("http.close")

    app = RuntimeApp(
        FakeState(events),
        FakeScheduler(events, fail=True),
        FakeRecordings(events),
        close_http=close_http,
    )

    with pytest.raises(RuntimeError, match="scheduler failed"):
        await app.shutdown(timeout=2)

    assert events == [
        "state.shutdown",
        "recordings.stop",
        "scheduler.stop",
        "recordings.close:2",
        "http.close",
    ]
