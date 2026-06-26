import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from src.http_clients.runner import run_async, run_async_batch


def test_run_async_closes_current_loop_clients_after_result():
    async def operation():
        return "ok"

    with patch(
        "src.http_clients.runner.close_async_clients_for_current_loop",
        new=AsyncMock(),
    ) as close:
        assert run_async(operation()) == "ok"

    close.assert_awaited_once_with()


def test_run_async_closes_current_loop_clients_after_error():
    async def operation():
        raise RuntimeError("boom")

    with patch(
        "src.http_clients.runner.close_async_clients_for_current_loop",
        new=AsyncMock(),
    ) as close:
        with pytest.raises(RuntimeError, match="boom"):
            run_async(operation())

    close.assert_awaited_once_with()


def test_run_async_batch_reuses_one_loop_and_closes_once():
    async def first():
        return ("first", id(asyncio.get_running_loop()))

    async def second():
        return ("second", id(asyncio.get_running_loop()))

    with patch(
        "src.http_clients.runner.close_async_clients_for_current_loop",
        new=AsyncMock(),
    ) as close:
        results = run_async_batch(first, second)

    assert results[0][0] == "first"
    assert results[1][0] == "second"
    assert results[0][1] == results[1][1]
    close.assert_awaited_once_with()


def test_run_async_batch_closes_current_loop_clients_after_error():
    async def first():
        return "ok"

    async def second():
        raise RuntimeError("boom")

    with patch(
        "src.http_clients.runner.close_async_clients_for_current_loop",
        new=AsyncMock(),
    ) as close:
        with pytest.raises(RuntimeError, match="boom"):
            run_async_batch(first, second)

    close.assert_awaited_once_with()
