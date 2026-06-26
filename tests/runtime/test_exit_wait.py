from src.runtime.exit_wait import wait_for_exit_key


def test_interactive_wait_reads_exactly_one_key():
    calls = []

    waited = wait_for_exit_key(
        platform_name="posix",
        is_interactive=lambda: True,
        read_key=lambda: calls.append("read") or "x",
    )

    assert waited is True
    assert calls == ["read"]


def test_noninteractive_wait_returns_without_reading():
    def fail_if_read():
        raise AssertionError("read_key must not be called")

    assert wait_for_exit_key(platform_name="posix", is_interactive=lambda: False, read_key=fail_if_read) is False


def test_closed_input_returns_without_hanging():
    def closed_input():
        raise EOFError

    assert wait_for_exit_key(platform_name="posix", is_interactive=lambda: True, read_key=closed_input) is False


def test_windows_console_handle_reads_key_even_when_python_stdin_is_not_tty():
    calls = []

    waited = wait_for_exit_key(
        platform_name="nt",
        is_interactive=lambda: False,
        console_available=lambda: True,
        read_key=lambda: calls.append("read") or "x",
    )

    assert waited is True
    assert calls == ["read"]


def test_windows_without_console_handle_returns_without_reading():
    def fail_if_read():
        raise AssertionError("read_key must not be called")

    waited = wait_for_exit_key(
        platform_name="nt",
        is_interactive=lambda: True,
        console_available=lambda: False,
        read_key=fail_if_read,
    )

    assert waited is False
