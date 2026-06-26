import asyncio

import pytest

from src.runtime import RuntimeRunner, ShutdownReport


class BlockingCoordinator:
    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.cancelled = False

    async def run(self) -> None:
        self.started.set()
        try:
            await asyncio.Event().wait()
        finally:
            self.cancelled = True


class FailingCoordinator:
    async def run(self) -> None:
        raise RuntimeError("coordinator failed")


class FakeApp:
    def __init__(self) -> None:
        self.shutdown_calls = 0

    async def shutdown(self) -> ShutdownReport:
        self.shutdown_calls += 1
        return ShutdownReport()


@pytest.mark.asyncio
async def test_signal_requests_shutdown_cancels_coordinator_and_cleans_handlers():
    installed = None
    cleanup_calls = 0

    def install(callback):
        nonlocal installed
        installed = callback

        def cleanup():
            nonlocal cleanup_calls
            cleanup_calls += 1

        return cleanup

    coordinator = BlockingCoordinator()
    app = FakeApp()
    runner = RuntimeRunner(coordinator, app, install_signals=install)
    task = asyncio.create_task(runner.run())
    await coordinator.started.wait()

    assert installed is not None
    installed()
    await task

    assert coordinator.cancelled is True
    assert app.shutdown_calls == 1
    assert cleanup_calls == 1


@pytest.mark.asyncio
async def test_coordinator_failure_shuts_down_app_then_propagates():
    app = FakeApp()
    runner = RuntimeRunner(FailingCoordinator(), app, install_signals=lambda _callback: lambda: None)

    with pytest.raises(RuntimeError, match="coordinator failed"):
        await runner.run()

    assert app.shutdown_calls == 1
