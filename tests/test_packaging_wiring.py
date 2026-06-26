from pathlib import Path


SPEC_PATH = Path(__file__).resolve().parents[1] / "DouyinLiveRecorder.spec"


def test_spec_restores_top_level_onedir_layout():
    source = SPEC_PATH.read_text(encoding="utf-8")

    assert 'contents_directory="."' in source


def test_spec_includes_runtime_bundle_directories():
    source = SPEC_PATH.read_text(encoding="utf-8")

    assert '(str(PROJECT_ROOT / "config"), "config")' in source
    assert '(str(_resolve_node_bundle()), "node")' in source
    assert '(str(_resolve_ffmpeg_bundle()), "ffmpeg")' in source
