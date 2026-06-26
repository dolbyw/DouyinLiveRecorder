from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from src.initializer import check_node


class NodeExecJsRuntime:
    def __init__(self) -> None:
        self._prepared = False

    def compile_source(self, source: str):
        self._prepare()
        from execjs import _external_runtime

        return _external_runtime.node().compile(source)

    def call_script(self, script_path: Path, function_name: str, *args: Any) -> Any:
        source = script_path.read_text(encoding="utf-8")
        return self.compile_source(source).call(function_name, *args)

    def run_cli_script(self, script_path: Path, *args: str) -> str:
        self._prepare()
        result = subprocess.run(
            ["node", str(script_path), *args],
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout.strip()

    def _prepare(self) -> None:
        if self._prepared:
            return
        execute_dir = Path(os.path.split(os.path.realpath(sys.argv[0]))[0])
        node_execute_dir = execute_dir / "node"
        current_env_path = os.environ.get("PATH", "")
        node_path = str(node_execute_dir)
        path_parts = current_env_path.split(os.pathsep) if current_env_path else []
        if node_path not in path_parts:
            os.environ["PATH"] = node_path + os.pathsep + current_env_path if current_env_path else node_path
        node_ready = check_node()
        if node_ready is False:
            raise RuntimeError("Node.js is required for JavaScript execution.")
        self._prepared = True
