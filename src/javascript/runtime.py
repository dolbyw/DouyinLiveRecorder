from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any, Protocol

from src import JS_SCRIPT_PATH

from .native_handlers import try_call_native_script
from .providers.mini_racer_runtime import MiniRacerRuntime
from .providers.node_runtime import NodeExecJsRuntime


class CompiledJavaScript(Protocol):
    def call(self, function_name: str, *args: Any) -> Any: ...


class JavaScriptRuntime(Protocol):
    def compile_source(self, source: str) -> CompiledJavaScript: ...

    def call_script(self, script_path: Path, function_name: str, *args: Any) -> Any: ...

    def run_cli_script(self, script_path: Path, *args: str) -> str: ...


def read_js_script(script_name: str) -> str:
    return (JS_SCRIPT_PATH / script_name).read_text(encoding="utf-8")


@lru_cache(maxsize=1)
def get_js_runtime() -> JavaScriptRuntime:
    runtime_name = os.getenv("DLR_JS_RUNTIME", "").strip().lower()
    if runtime_name == "mini_racer":
        runtime = MiniRacerRuntime.try_create()
        if runtime is not None:
            return runtime
    return NodeExecJsRuntime()


def compile_js(source: str) -> CompiledJavaScript:
    return get_js_runtime().compile_source(source)


def call_js_file(script_name: str, function_name: str, *args: Any) -> Any:
    handled, native_result = try_call_native_script(script_name, function_name, *args)
    if handled:
        return native_result
    return get_js_runtime().call_script(JS_SCRIPT_PATH / script_name, function_name, *args)


def run_js_cli_file(script_name: str, *args: str) -> str:
    return get_js_runtime().run_cli_script(JS_SCRIPT_PATH / script_name, *args)
