from __future__ import annotations

import os
import threading
from collections.abc import Callable


class ShutdownControl:
    def __init__(self, *, force_exit: Callable[[int], None] = os._exit) -> None:
        self._force_exit = force_exit
        self._requested = False
        self._lock = threading.RLock()

    @property
    def requested(self) -> bool:
        with self._lock:
            return self._requested

    def request(self) -> bool:
        with self._lock:
            if not self._requested:
                self._requested = True
                return True
        self._force_exit(130)
        return False
