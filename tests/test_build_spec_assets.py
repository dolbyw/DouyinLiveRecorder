from __future__ import annotations

import types
import zipfile
from pathlib import Path


def load_spec_helpers() -> types.SimpleNamespace:
    spec_path = Path(__file__).resolve().parents[1] / "DouyinLiveRecorder.spec"
    source = spec_path.read_text(encoding="utf-8")
    helper_source = source.split("hiddenimports = ", maxsplit=1)[0]
    namespace: dict[str, object] = {"__file__": str(spec_path)}
    exec(helper_source, namespace)
    return types.SimpleNamespace(**namespace)


def test_copy_local_rclone_bundle_copies_executable(tmp_path):
    helpers = load_spec_helpers()
    source = tmp_path / "source"
    source.mkdir()
    (source / "rclone.exe").write_bytes(b"rclone")

    bundle_dir = helpers._copy_local_rclone_bundle(source, tmp_path / "assets")

    assert bundle_dir == tmp_path / "assets" / "rclone"
    assert (bundle_dir / "rclone.exe").read_bytes() == b"rclone"


def test_extract_rclone_zip_finds_nested_executable(tmp_path):
    helpers = load_spec_helpers()
    zip_path = tmp_path / "rclone.zip"
    with zipfile.ZipFile(zip_path, "w") as archive:
        archive.writestr("rclone-v1.70.0-windows-amd64/rclone.exe", b"rclone")

    bundle_dir = helpers._extract_rclone_zip(zip_path, tmp_path / "assets")

    assert bundle_dir == tmp_path / "assets" / "rclone"
    assert (bundle_dir / "rclone.exe").read_bytes() == b"rclone"


def test_prepare_packaged_config_sets_bundled_rclone_path(tmp_path):
    helpers = load_spec_helpers()
    source_config = tmp_path / "config"
    source_config.mkdir()
    (source_config / "config.ini").write_text(
        "[自动上传]\n"
        "是否启用自动上传 = 否\n"
        "rclone可执行文件路径 =\n",
        encoding="utf-8-sig",
    )
    (source_config / "URL_config.ini").write_text("", encoding="utf-8-sig")

    packaged_config = helpers._prepare_packaged_config(source_config, tmp_path / "assets")

    config_text = (packaged_config / "config.ini").read_text(encoding="utf-8-sig")
    assert packaged_config == tmp_path / "assets" / "config"
    assert "rclone可执行文件路径 = rclone\\rclone.exe" in config_text
    assert (packaged_config / "URL_config.ini").exists()
