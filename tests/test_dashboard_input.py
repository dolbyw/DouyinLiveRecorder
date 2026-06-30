import time

from src.dashboard_input import DashboardInputController, DashboardKeyReader
from src.dashboard_view import RoomListMode


def test_r_toggles_room_mode_and_wakes_dashboard():
    wakes = []
    controller = DashboardInputController(on_change=lambda: wakes.append(True))

    assert controller.room_mode is RoomListMode.COMPACT
    assert controller.handle_key("r") is True
    assert controller.room_mode is RoomListMode.EXPANDED
    assert wakes == [True]
    assert controller.handle_key("R") is True
    assert controller.room_mode is RoomListMode.COMPACT


def test_other_keys_are_ignored_and_disabled_controller_cannot_toggle():
    controller = DashboardInputController(on_change=lambda: None)

    assert controller.handle_key("x") is False
    controller.disable()

    assert controller.handle_key("r") is False
    assert controller.room_mode is RoomListMode.COMPACT


def test_u_toggles_upload_detail_and_wakes_dashboard():
    wakes = []
    controller = DashboardInputController(on_change=lambda: wakes.append(True))

    assert controller.upload_detail_expanded is False
    assert controller.handle_key("u") is True
    assert controller.upload_detail_expanded is True
    assert wakes == [True]
    assert controller.handle_key("U") is True
    assert controller.upload_detail_expanded is False


def test_noninteractive_reader_does_not_start():
    controller = DashboardInputController(on_change=lambda: None)
    reader = DashboardKeyReader(
        controller,
        platform_name="win32",
        is_interactive=lambda: False,
        key_available=lambda: True,
        read_key=lambda: "r",
    )

    assert reader.start() is False


def test_reader_routes_available_r_and_stops_promptly():
    wakes = []
    keys = ["r"]
    controller = DashboardInputController(on_change=lambda: wakes.append(True))
    reader = DashboardKeyReader(
        controller,
        platform_name="win32",
        is_interactive=lambda: True,
        key_available=lambda: bool(keys),
        read_key=lambda: keys.pop(0),
    )

    assert reader.start() is True
    deadline = time.monotonic() + 1
    while not wakes and time.monotonic() < deadline:
        time.sleep(0.01)
    reader.stop()

    assert wakes == [True]
    assert controller.room_mode is RoomListMode.EXPANDED


def test_reader_failure_reports_once_and_exits():
    errors = []
    controller = DashboardInputController(on_change=lambda: None)

    def fail_read():
        raise OSError("console closed")

    reader = DashboardKeyReader(
        controller,
        platform_name="win32",
        is_interactive=lambda: True,
        key_available=lambda: True,
        read_key=fail_read,
        on_error=errors.append,
    )

    assert reader.start() is True
    deadline = time.monotonic() + 1
    while not errors and time.monotonic() < deadline:
        time.sleep(0.01)
    reader.stop()

    assert [str(error) for error in errors] == ["console closed"]
