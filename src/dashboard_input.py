from __future__ import annotations

import sys
import threading
from collections.abc import Callable

from .dashboard_view import RoomListMode


class DashboardInputController:
    def __init__(self, *, on_change: Callable[[], None]) -> None:
        self._lock = threading.RLock()
        self._room_mode = RoomListMode.COMPACT
        self._upload_detail_expanded = False
        self._enabled = True
        self._on_change = on_change

    @property
    def room_mode(self) -> RoomListMode:
        with self._lock:
            return self._room_mode

    @property
    def upload_detail_expanded(self) -> bool:
        with self._lock:
            return self._upload_detail_expanded

    def handle_key(self, key: str) -> bool:
        with self._lock:
            if not self._enabled or key not in {"r", "R", "u", "U"}:
                return False
            if key in {"r", "R"}:
                self._room_mode = (
                    RoomListMode.EXPANDED
                    if self._room_mode is RoomListMode.COMPACT
                    else RoomListMode.COMPACT
                )
            else:
                self._upload_detail_expanded = not self._upload_detail_expanded
        self._on_change()
        return True

    def disable(self) -> None:
        with self._lock:
            self._enabled = False


class DashboardKeyReader:
    def __init__(
        self,
        controller: DashboardInputController,
        *,
        platform_name: str = sys.platform,
        is_interactive: Callable[[], bool] | None = None,
        key_available: Callable[[], bool] | None = None,
        read_key: Callable[[], str] | None = None,
        on_error: Callable[[Exception], None] | None = None,
    ) -> None:
        self._controller = controller
        self._platform_name = platform_name
        self._is_interactive = is_interactive or _stdin_is_interactive
        self._key_available = key_available
        self._read_key = read_key
        self._on_error = on_error or (lambda _error: None)
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> bool:
        if self._platform_name != "win32" or not self._is_interactive():
            return False
        if self._key_available is None or self._read_key is None:
            import msvcrt

            self._key_available = msvcrt.kbhit
            self._read_key = msvcrt.getwch
        if self._thread is not None and self._thread.is_alive():
            return True
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, name="dashboard-key-reader", daemon=True)
        self._thread.start()
        return True

    def stop(self) -> None:
        self._stop_event.set()
        thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=0.5)
        self._thread = None

    def _run(self) -> None:
        try:
            while not self._stop_event.is_set():
                if self._key_available is not None and self._key_available():
                    key = self._read_key() if self._read_key is not None else ""
                    self._controller.handle_key(key)
                self._stop_event.wait(0.05)
        except Exception as error:
            self._stop_event.set()
            self._on_error(error)


def _stdin_is_interactive() -> bool:
    return bool(getattr(sys.stdin, "isatty", lambda: False)())
