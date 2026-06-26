import hashlib
import os
import sys
from pathlib import Path

from src.javascript.providers.node_runtime import NodeExecJsRuntime
from src.javascript.native_handlers import try_call_native_script


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _read(relative_path: str) -> str:
    return (PROJECT_ROOT / relative_path).read_text(encoding="utf-8")


def test_src_init_has_no_node_side_effects():
    source = _read("src/__init__.py")

    assert "check_node()" not in source
    assert "os.environ[" not in source
    assert 'JS_SCRIPT_PATH = current_dir / "javascript"' in source


def test_spider_and_room_use_javascript_runtime_helpers():
    spider_source = _read("src/spider.py")
    room_source = _read("src/room.py")

    assert "execjs.compile(" not in spider_source
    assert "execjs.compile(" not in room_source
    assert '["node",' not in spider_source
    assert "from .javascript import call_js_file, compile_js" in spider_source
    assert "from .javascript import call_js_file" in room_source
    assert 'call_js_file("x-bogus.js"' in room_source
    assert "compile_js(func_ub9)" in spider_source
    assert 'call_js_file("liveme.js"' in spider_source
    assert 'call_js_file("laixiu.js"' in spider_source
    assert 'run_js_cli_file("migu.js"' in spider_source


def test_javascript_runtime_has_provider_boundary():
    runtime_source = _read("src/javascript/runtime.py")
    node_provider_source = _read("src/javascript/providers/node_runtime.py")

    assert "def get_js_runtime()" in runtime_source
    assert "MiniRacerRuntime.try_create()" in runtime_source
    assert "NodeExecJsRuntime()" in runtime_source
    assert "def run_js_cli_file" in runtime_source
    assert "try_call_native_script" in runtime_source
    assert "def compile_source" in node_provider_source
    assert "def call_script" in node_provider_source
    assert "def run_cli_script" in node_provider_source
    assert "_external_runtime.node().compile(source)" in node_provider_source


def test_node_runtime_prepare_accepts_check_node_none(monkeypatch):
    runtime = NodeExecJsRuntime()
    entrypoint = PROJECT_ROOT / "main.py"
    monkeypatch.setattr(sys, "argv", [str(entrypoint)])
    monkeypatch.setenv("PATH", "")
    monkeypatch.setattr("src.javascript.providers.node_runtime.check_node", lambda: None)

    runtime._prepare()

    assert runtime._prepared is True
    assert os.environ["PATH"].startswith(str(PROJECT_ROOT / "node"))


def test_native_taobao_sign_matches_md5_contract():
    payload = '5655b7041ca049730330701082886efd&1719411639403&12574478&{"componentKey":"demo"}'

    handled, result = try_call_native_script("taobao-sign.js", "sign", payload)

    assert handled is True
    assert result == hashlib.md5(payload.encode("utf-8")).hexdigest()


def test_native_laixiu_sign_returns_expected_shape():
    handled, result = try_call_native_script("laixiu.js", "sign", "ignored")

    assert handled is True
    assert isinstance(result["timestamp"], int)
    assert isinstance(result["imei"], str)
    assert len(result["imei"]) == 32
    assert result["inputString"].startswith(f'web{result["imei"]}{result["timestamp"]}')
    assert result["requestId"] == hashlib.md5(result["inputString"].encode("utf-8")).hexdigest()
