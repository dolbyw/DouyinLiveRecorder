import asyncio

import pytest

from src.runtime.limiter import AdjustableLimiter


def test_limiter_rejects_non_positive_limit():
    with pytest.raises(ValueError, match="greater than zero"):
        AdjustableLimiter(0)


@pytest.mark.asyncio
async def test_limiter_blocks_above_limit_and_reports_metrics():
    limiter = AdjustableLimiter(1)
    await limiter.acquire()
    waiter = asyncio.create_task(limiter.acquire())
    await asyncio.sleep(0)

    assert limiter.limit == 1
    assert limiter.active_count == 1
    assert limiter.waiting_count == 1
    assert not waiter.done()

    await limiter.release()
    await waiter
    await limiter.release()

    assert limiter.active_count == 0
    assert limiter.waiting_count == 0


@pytest.mark.asyncio
async def test_limiter_context_manager_releases_after_error():
    limiter = AdjustableLimiter(1)

    with pytest.raises(RuntimeError, match="boom"):
        async with limiter:
            assert limiter.active_count == 1
            raise RuntimeError("boom")

    assert limiter.active_count == 0


@pytest.mark.asyncio
async def test_expanding_limit_wakes_a_waiter():
    limiter = AdjustableLimiter(1)
    await limiter.acquire()
    waiter = asyncio.create_task(limiter.acquire())
    await asyncio.sleep(0)

    await limiter.set_limit(2)
    await asyncio.wait_for(waiter, timeout=1)

    assert limiter.active_count == 2
    await limiter.release()
    await limiter.release()


@pytest.mark.asyncio
async def test_shrinking_limit_does_not_revoke_active_permits():
    limiter = AdjustableLimiter(2)
    await limiter.acquire()
    await limiter.acquire()
    await limiter.set_limit(1)
    waiter = asyncio.create_task(limiter.acquire())

    await limiter.release()
    await asyncio.sleep(0)
    assert not waiter.done()

    await limiter.release()
    await asyncio.wait_for(waiter, timeout=1)
    assert limiter.active_count == 1
    await limiter.release()


@pytest.mark.asyncio
async def test_cancelling_waiter_does_not_leak_capacity():
    limiter = AdjustableLimiter(1)
    await limiter.acquire()
    waiter = asyncio.create_task(limiter.acquire())
    await asyncio.sleep(0)

    waiter.cancel()
    with pytest.raises(asyncio.CancelledError):
        await waiter

    assert limiter.waiting_count == 0
    assert limiter.active_count == 1
    await limiter.release()
