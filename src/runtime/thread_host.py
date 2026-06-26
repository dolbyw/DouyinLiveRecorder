from __future__ import annotations

import asyncio
import threading
from collections.abc import Callable
from typing import Protocol


class HostedRunner(Protocol):
    async def run(self) -> None: ...

    def request_shutdown(self) -> None: ...


class ThreadedRuntimeHost:
    def __init__(self, runner_factory: Callable[[], HostedRunner]) -> None:
        self._runner_factory = runner_factory
        self._thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._runner: HostedRunner | None = None
        self._ready = threading.Event()
        self._lock = threading.Lock()
        self._failure: BaseException | None = None

    @property
    def failure(self) -> BaseException | None:
        with self._lock:
            return self._failure

    @property
    def is_alive(self) -> bool:
        with self._lock:
            return bool(self._thread and self._thread.is_alive())

    def start(self, *, timeout: float = 5.0) -> None:
        with self._lock:
            if self._thread is not None:
                raise RuntimeError("runtime host already started")
            self._thread = threading.Thread(
                target=self._thread_main,
                name="async-runtime",
                daemon=True,
            )
            self._thread.start()
        if not self._ready.wait(timeout):
            raise TimeoutError("runtime host did not become ready")

    def request_shutdown(self) -> bool:
        with self._lock:
            loop = self._loop
            runner = self._runner
            thread = self._thread
        if loop is None or runner is None or thread is None or not thread.is_alive():
            return False
        loop.call_soon_threadsafe(runner.request_shutdown)
        return True

    def join(self, *, timeout: float | None = None) -> bool:
        with self._lock:
            thread = self._thread
        if thread is None:
            return True
        thread.join(timeout)
        return not thread.is_alive()

    def _thread_main(self) -> None:
        try:
            asyncio.run(self._run())
        except BaseException as error:
            with self._lock:
                self._failure = error
            self._ready.set()

    async def _run(self) -> None:
        runner = self._runner_factory()
        with self._lock:
            self._loop = asyncio.get_running_loop()
            self._runner = runner
        self._ready.set()
        await runner.run()
