from src.http_clients import close_async_clients, close_sync_sessions


def test_close_functions_are_public():
    assert callable(close_async_clients)
    assert callable(close_sync_sessions)
