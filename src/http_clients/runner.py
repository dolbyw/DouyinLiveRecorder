from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import TypeVar

from .client_pool import close_async_clients_for_current_loop

ResultT = TypeVar("ResultT")
BatchResultT = TypeVar("BatchResultT")


def run_async(awaitable: Awaitable[ResultT]) -> ResultT:
    async def execute() -> ResultT:
        try:
            return await awaitable
        finally:
            await close_async_clients_for_current_loop()

    return asyncio.run(execute())


def run_async_batch(*factories: Callable[[], Awaitable[BatchResultT]]) -> tuple[BatchResultT, ...]:
    async def execute() -> tuple[BatchResultT, ...]:
        try:
            results = []
            for factory in factories:
                results.append(await factory())
            return tuple(results)
        finally:
            await close_async_clients_for_current_loop()

    return asyncio.run(execute())
