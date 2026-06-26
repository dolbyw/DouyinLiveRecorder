from src.runtime.shutdown import ShutdownControl


def test_first_request_starts_graceful_shutdown_without_forcing():
    forced = []
    control = ShutdownControl(force_exit=forced.append)

    assert control.request() is True
    assert control.requested is True
    assert forced == []


def test_second_request_forces_interrupted_exit():
    forced = []
    control = ShutdownControl(force_exit=forced.append)

    control.request()

    assert control.request() is False
    assert forced == [130]
