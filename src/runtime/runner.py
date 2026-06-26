from __future__ import annotations

import asyncio
import contextlib
import signal
from collections.abc import Callable
from typing import Protocol

from .app import RuntimeApp
from .coordinator import RuntimeCoordinator

SignalCleanup = Callable[[], None]
SignalInstaller = Callable[[Callable[[], None]], SignalCleanup]


def install_shutdown_signal_handlers(callback: Callable[[], None]) -> SignalCleanup:
    loop = asyncio.get_running_loop()
    installed_on_loop: list[signal.Signals] = []
    fallback_handlers: list[tuple[signal.Signals, signal.Handlers]] = []

    for signal_number in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(signal_number, callback)
            installed_on_loop.append(signal_number)
        except NotImplementedError:
            previous = signal.getsignal(signal_number)
            fallback_handlers.append((signal_number, previous))
            signal.signal(
                signal_number,
                lambda _signum, _frame: loop.call_soon_threadsafe(callback),
            )

    def cleanup() -> None:
        for signal_number in installed_on_loop:
            loop.remove_signal_handler(signal_number)
        for signal_number, previous in fallback_handlers:
            signal.signal(signal_number, previous)

    return cleanup


class Coordinator(Protocol):
    async def run(self) -> None: ...


class Application(Protocol):
    async def shutdown(self): ...


class RuntimeRunner:
    def __init__(
        self,
        coordinator: RuntimeCoordinator | Coordinator,
        app: RuntimeApp | Application,
        *,
        install_signals: SignalInstaller = install_shutdown_signal_handlers,
    ) -> None:
        self._coordinator = coordinator
        self._app = app
        self._install_signals = install_signals
        self._shutdown_requested = asyncio.Event()

    def request_shutdown(self) -> None:
        self._shutdown_requested.set()

    async def run(self) -> None:
        cleanup_signals = self._install_signals(self.request_shutdown)
        coordinator_task = asyncio.create_task(self._coordinator.run(), name="runtime-coordinator")
        stop_task = asyncio.create_task(self._shutdown_requested.wait(), name="runtime-shutdown")
        try:
            done, _pending = await asyncio.wait(
                {coordinator_task, stop_task},
                return_when=asyncio.FIRST_COMPLETED,
            )
            if coordinator_task in done:
                await coordinator_task
            else:
                coordinator_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await coordinator_task
        finally:
            for task in (coordinator_task, stop_task):
                if not task.done():
                    task.cancel()
            await asyncio.gather(coordinator_task, stop_task, return_exceptions=True)
            try:
                await self._app.shutdown()
            finally:
                cleanup_signals()
