import ast
import sys
import types
from pathlib import Path


MAIN_PATH = Path("main.py")


def test_main_exposes_guarded_entrypoint():
    source = MAIN_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source)

    assert any(isinstance(node, ast.FunctionDef) and node.name == "main" for node in tree.body)
    assert 'if __name__ == "__main__":' in source
    assert "raise SystemExit(main())" in source


def test_import_main_has_no_startup_side_effects():
    import importlib

    original_main = sys.modules.pop("main", None)
    original_ffmpeg_install = sys.modules.get("ffmpeg_install")

    def fail_check_ffmpeg():
        raise AssertionError("importing main must not check ffmpeg")

    fake_ffmpeg_install = types.ModuleType("ffmpeg_install")
    fake_ffmpeg_install.check_ffmpeg = fail_check_ffmpeg
    fake_ffmpeg_install.current_env_path = ""
    fake_ffmpeg_install.ffmpeg_path = ""
    sys.modules["ffmpeg_install"] = fake_ffmpeg_install

    try:
        module = importlib.import_module("main")
    finally:
        sys.modules.pop("main", None)
        if original_main is not None:
            sys.modules["main"] = original_main
        if original_ffmpeg_install is not None:
            sys.modules["ffmpeg_install"] = original_ffmpeg_install
        else:
            sys.modules.pop("ffmpeg_install", None)

    assert hasattr(module, "main")


def test_import_main_has_entrypoint():
    import importlib

    module = importlib.import_module("main")

    assert hasattr(module, "main")
