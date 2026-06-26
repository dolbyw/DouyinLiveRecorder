import ast
from pathlib import Path


def start_record_source() -> str:
    source = Path("main.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    function = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "start_record")
    return ast.get_source_segment(source, function) or ""


def test_main_uses_registry_before_legacy_douyin_branch():
    source = Path("main.py").read_text(encoding="utf-8")
    registry_call = source.index("try_resolve(")
    legacy_branch = source.index('record_url.find("douyin.com/")')

    assert registry_call < legacy_branch
    assert "if dispatch_result.handled:" in source
    assert 'elif record_url.find("douyin.com/")' in source
    assert "dispatch_result.error is not None" in source


def test_start_record_uses_registered_platform_helper_before_legacy_branches():
    source = start_record_source()

    helper_call = source.index("resolve_registered_platform_once(")
    legacy_branches = [
        source.index('record_url.find("douyin.com/")'),
        source.index('record_url.find("https://www.tiktok.com/")'),
        source.index('record_url.find("https://www.huya.com/")'),
        source.index('record_url.find("https://live.bilibili.com/")'),
    ]

    assert all(helper_call < branch for branch in legacy_branches)
    assert "elif record_url.find(" in source
