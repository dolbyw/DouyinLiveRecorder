import asyncio
import threading

import pytest

from src.runtime import ThreadedRuntimeHost


class BlockingRunner:
    def __init__(self) -> None:
        self.started = threading.Event()
        self._stop: asyncio.Event | None = None

    async def run(self) -> None:
        self._stop = asyncio.Event()
        self.started.set()
        await self._stop.wait()

    def request_shutdown(self) -> None:
        assert self._stop is not None
        self._stop.set()


class FailingRunner:
    async def run(self) -> None:
        raise RuntimeError("runner failed")

    def request_shutdown(self) -> None:
        pass


def test_host_starts_once_and_delivers_thread_safe_shutdown():
    runner = BlockingRunner()
    host = ThreadedRuntimeHost(lambda: runner)

    host.start(timeout=1)
    assert runner.started.wait(1)
    assert host.is_alive is True

    with pytest.raises(RuntimeError, match="already started"):
        host.start(timeout=1)

    assert host.request_shutdown() is True
    assert host.join(timeout=1) is True
    assert host.is_alive is False
    assert host.failure is None


def test_host_exposes_runner_failure():
    host = ThreadedRuntimeHost(FailingRunner)

    host.start(timeout=1)
    assert host.join(timeout=1) is True

    assert isinstance(host.failure, RuntimeError)
    assert str(host.failure) == "runner failed"
