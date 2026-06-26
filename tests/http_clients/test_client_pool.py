import asyncio

from src.http_clients.client_pool import (
    ClientPurpose,
    close_async_clients,
    close_async_clients_for_current_loop,
    close_sync_sessions,
    get_async_client,
    get_sync_session,
)


def test_async_client_is_reused_only_for_same_purpose_and_loop():
    async def scenario():
        direct_1 = get_async_client(purpose=ClientPurpose.DIRECT)
        direct_2 = get_async_client(purpose=ClientPurpose.DIRECT)
        abroad = get_async_client(purpose=ClientPurpose.ABROAD)

        assert direct_1 is direct_2
        assert direct_1 is not abroad

        await close_async_clients_for_current_loop()
        replacement = get_async_client(purpose=ClientPurpose.DIRECT)
        assert replacement is not direct_1
        await close_async_clients()
        await close_async_clients()

    asyncio.run(scenario())


def test_async_clients_are_isolated_between_event_loops():
    async def acquire_and_close():
        client = get_async_client(purpose=ClientPurpose.DIRECT)
        await close_async_clients_for_current_loop()
        return client

    first = asyncio.run(acquire_and_close())
    second = asyncio.run(acquire_and_close())

    assert first is not second


def test_sync_session_reuse_is_keyed_by_purpose_and_close_is_idempotent():
    direct_1 = get_sync_session(purpose=ClientPurpose.DIRECT)
    direct_2 = get_sync_session(purpose=ClientPurpose.DIRECT)
    abroad = get_sync_session(purpose=ClientPurpose.ABROAD)

    assert direct_1 is direct_2
    assert direct_1 is not abroad

    close_sync_sessions()
    close_sync_sessions()
    replacement = get_sync_session(purpose=ClientPurpose.DIRECT)
    assert replacement is not direct_1
    close_sync_sessions()
