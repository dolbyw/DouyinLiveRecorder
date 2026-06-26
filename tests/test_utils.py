import pytest

from src.utils import trace_error_decorator


def test_trace_error_decorator_keeps_sync_success_value():
    @trace_error_decorator
    def sample():
        return {"ok": True}

    assert sample() == {"ok": True}


def test_trace_error_decorator_returns_empty_list_for_sync_exception():
    @trace_error_decorator
    def sample():
        raise RuntimeError("boom")

    assert sample() == []


@pytest.mark.asyncio
async def test_trace_error_decorator_returns_empty_list_for_async_exception():
    @trace_error_decorator
    async def sample():
        raise RuntimeError("boom")

    assert await sample() == []


@pytest.mark.asyncio
async def test_trace_error_decorator_keeps_async_success_value():
    @trace_error_decorator
    async def sample():
        return {"ok": True}

    assert await sample() == {"ok": True}
