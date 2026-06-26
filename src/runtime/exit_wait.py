from __future__ import annotations

import ctypes
import os
import sys
from collections.abc import Callable
from ctypes import wintypes


def _console_is_interactive() -> bool:
    return bool(sys.stdin is not None and sys.stdin.isatty())


def _read_console_key() -> str:
    if os.name == "nt":
        import msvcrt

        return msvcrt.getwch()
    return input()


def _windows_console_available() -> bool:
    try:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.GetStdHandle.argtypes = [wintypes.DWORD]
        kernel32.GetStdHandle.restype = wintypes.HANDLE
        kernel32.GetConsoleMode.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        kernel32.GetConsoleMode.restype = wintypes.BOOL
        handle = kernel32.GetStdHandle(-10)
        invalid_handle = ctypes.c_void_p(-1).value
        if handle in (None, 0, invalid_handle):
            return False
        mode = wintypes.DWORD()
        return bool(kernel32.GetConsoleMode(handle, ctypes.byref(mode)))
    except (AttributeError, OSError):
        return False


def wait_for_exit_key(
    *,
    platform_name: str | None = None,
    is_interactive: Callable[[], bool] | None = None,
    console_available: Callable[[], bool] | None = None,
    read_key: Callable[[], str] | None = None,
) -> bool:
    platform = platform_name or os.name
    if platform == "nt":
        can_read = (console_available or _windows_console_available)()
    else:
        can_read = (is_interactive or _console_is_interactive)()
    if not can_read:
        return False
    try:
        (read_key or _read_console_key)()
    except (EOFError, OSError):
        return False
    return True
