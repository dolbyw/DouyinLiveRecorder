from __future__ import annotations

from pathlib import Path
from typing import Any


class MiniRacerRuntime:
    @classmethod
    def try_create(cls) -> MiniRacerRuntime | None:
        try:
            from py_mini_racer import MiniRacer  # type: ignore
        except ImportError:
            return None
        return cls(MiniRacer)

    def __init__(self, mini_racer_cls) -> None:
        self._mini_racer_cls = mini_racer_cls

    def compile_source(self, source: str):
        ctx = self._mini_racer_cls()
        ctx.eval(source)
        return _MiniRacerCompiledScript(ctx)

    def call_script(self, script_path: Path, function_name: str, *args: Any) -> Any:
        return self.compile_source(script_path.read_text(encoding="utf-8")).call(function_name, *args)

    def run_cli_script(self, script_path: Path, *args: str) -> str:
        raise RuntimeError(
            f"CLI JavaScript execution is not supported by MiniRacerRuntime: {script_path.name}"
        )


class _MiniRacerCompiledScript:
    def __init__(self, ctx) -> None:
        self._ctx = ctx

    def call(self, function_name: str, *args: Any) -> Any:
        return self._ctx.call(function_name, *args)
