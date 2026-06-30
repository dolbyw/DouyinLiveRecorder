# -*- mode: python ; coding: utf-8 -*-
from __future__ import annotations

import os
import configparser
import re
import shutil
import subprocess
import zipfile
from pathlib import Path

import requests
from PyInstaller.utils.hooks import collect_submodules


PROJECT_ROOT = Path.cwd()
BUILD_ASSET_ROOT = PROJECT_ROOT / "build" / "bundle_assets"
FFMPEG_DOWNLOAD_PAGE = "https://wweb.lanzouv.com/iHAc22ly3r3g"
FFMPEG_DOWNLOAD_PASSWORD = "eots"
FFMPEG_FALLBACK_ZIP_URL = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"
RCLONE_DOWNLOAD_URL = "https://downloads.rclone.org/rclone-current-windows-amd64.zip"


def _get_lanzou_download_link(url: str, password: str | None = None) -> str:
    headers = {
        "accept-language": "zh-CN,zh;q=0.9,en;q=0.8,en-GB;q=0.7,en-US;q=0.6",
        "Origin": "https://wweb.lanzouv.com",
        "Referer": url,
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36 Edg/121.0.0.0"
        ),
    }
    response = requests.get(url, headers=headers, timeout=30)
    response.raise_for_status()
    match = re.search(r"var skdklds = '(.*?)';", response.text)
    if match is None:
        raise RuntimeError("Unable to parse the ffmpeg download signature from Lanzou page.")

    ajax_response = requests.post(
        "https://wweb.lanzouv.com/ajaxm.php",
        headers=headers,
        data={
            "action": "downprocess",
            "sign": match.group(1),
            "p": password,
            "kd": "1",
        },
        timeout=30,
    )
    ajax_response.raise_for_status()
    payload = ajax_response.json()
    download_url = payload["dom"] + "/file/" + payload["url"]

    final_response = requests.get(download_url, headers=headers, timeout=30)
    final_response.raise_for_status()
    return final_response.url


def _download_ffmpeg_bundle(target_root: Path) -> Path:
    target_root.mkdir(parents=True, exist_ok=True)
    bundle_dir = target_root / "ffmpeg"
    ffmpeg_exe = bundle_dir / "ffmpeg.exe"
    if ffmpeg_exe.exists():
        return bundle_dir

    zip_file_path = target_root / "ffmpeg-bundle.zip"
    try:
        show_result = subprocess.run(
            [
                "winget",
                "show",
                "--id",
                "Gyan.FFmpeg",
                "--exact",
                "--accept-source-agreements",
                "--disable-interactivity",
            ],
            check=True,
            capture_output=True,
        )
        show_stdout = show_result.stdout.decode("utf-8", errors="replace")
        match = re.search(r"Installer Url:\s*(https?://\S+\.zip)", show_stdout)
        if match is None:
            raise RuntimeError("Unable to parse ffmpeg installer url from winget output.")
        subprocess.run(
            [
                "curl.exe",
                "-Lk",
                "-sS",
                match.group(1),
                "-o",
                str(zip_file_path),
            ],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception:
        try:
            download_url = FFMPEG_FALLBACK_ZIP_URL
            requests.get(download_url, stream=True, timeout=15).close()
        except Exception:
            download_url = _get_lanzou_download_link(FFMPEG_DOWNLOAD_PAGE, FFMPEG_DOWNLOAD_PASSWORD)

        with requests.get(download_url, stream=True, timeout=60) as response:
            response.raise_for_status()
            with open(zip_file_path, "wb") as zip_file:
                for chunk in response.iter_content(1024 * 1024):
                    if chunk:
                        zip_file.write(chunk)

    if bundle_dir.exists():
        shutil.rmtree(bundle_dir)
    with zipfile.ZipFile(zip_file_path, "r") as zip_ref:
        zip_ref.extractall(target_root)
    zip_file_path.unlink(missing_ok=True)

    if not ffmpeg_exe.exists():
        extracted_ffmpeg = next(target_root.rglob("ffmpeg.exe"), None)
        if extracted_ffmpeg is None:
            raise RuntimeError("ffmpeg bundle download completed, but ffmpeg.exe was not found after extraction.")
        extracted_root = extracted_ffmpeg.parent
        bundle_dir.mkdir(parents=True, exist_ok=True)
        for executable_name in ("ffmpeg.exe", "ffplay.exe", "ffprobe.exe"):
            candidate = extracted_root / executable_name
            if candidate.exists():
                shutil.copy2(candidate, bundle_dir / executable_name)

    if not ffmpeg_exe.exists():
        raise RuntimeError("ffmpeg bundle download completed, but ffmpeg.exe was not found after extraction.")
    return bundle_dir


def _copy_local_ffmpeg_bundle(source_dir: Path, target_root: Path) -> Path:
    bundle_dir = target_root / "ffmpeg"
    bundle_dir.mkdir(parents=True, exist_ok=True)

    for executable_name in ("ffmpeg.exe", "ffplay.exe", "ffprobe.exe"):
        direct_candidate = source_dir / executable_name
        bin_candidate = source_dir / "bin" / executable_name
        source_file = direct_candidate if direct_candidate.exists() else bin_candidate
        if source_file.exists():
            shutil.copy2(source_file, bundle_dir / executable_name)

    if not (bundle_dir / "ffmpeg.exe").exists():
        raise RuntimeError(f"ffmpeg.exe was not found in {source_dir}")
    return bundle_dir


def _resolve_ffmpeg_bundle() -> Path:
    explicit_dir = os.environ.get("DLR_FFMPEG_DIR")
    if explicit_dir:
        return _copy_local_ffmpeg_bundle(Path(explicit_dir), BUILD_ASSET_ROOT)

    try:
        where_result = subprocess.run(
            ["where", "ffmpeg"],
            check=True,
            capture_output=True,
        )
        system_ffmpeg = Path(os.fsdecode(where_result.stdout).splitlines()[0]).resolve().parent
        return _copy_local_ffmpeg_bundle(system_ffmpeg, BUILD_ASSET_ROOT)
    except Exception:
        pass

    repo_bundle = PROJECT_ROOT / "ffmpeg"
    if (repo_bundle / "ffmpeg.exe").exists():
        return repo_bundle
    return _download_ffmpeg_bundle(BUILD_ASSET_ROOT)


def _resolve_node_bundle() -> Path:
    repo_bundle = PROJECT_ROOT / "node"
    if (repo_bundle / "node.exe").exists():
        return repo_bundle
    raise RuntimeError("node/node.exe is missing. Please restore the bundled Node.js runtime before packaging.")


def _copy_local_rclone_bundle(source_dir: Path, target_root: Path) -> Path:
    bundle_dir = target_root / "rclone"
    bundle_dir.mkdir(parents=True, exist_ok=True)

    source_file = source_dir / "rclone.exe"
    if not source_file.exists():
        source_file = source_dir / "bin" / "rclone.exe"
    if not source_file.exists():
        raise RuntimeError(f"rclone.exe was not found in {source_dir}")

    shutil.copy2(source_file, bundle_dir / "rclone.exe")
    return bundle_dir


def _extract_rclone_zip(zip_file_path: Path, target_root: Path) -> Path:
    bundle_dir = target_root / "rclone"
    if bundle_dir.exists():
        shutil.rmtree(bundle_dir)

    extract_root = target_root / "rclone_extract"
    if extract_root.exists():
        shutil.rmtree(extract_root)
    extract_root.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(zip_file_path, "r") as zip_ref:
        zip_ref.extractall(extract_root)

    extracted_rclone = next(extract_root.rglob("rclone.exe"), None)
    if extracted_rclone is None:
        raise RuntimeError("rclone bundle download completed, but rclone.exe was not found after extraction.")

    bundle_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(extracted_rclone, bundle_dir / "rclone.exe")
    shutil.rmtree(extract_root)
    return bundle_dir


def _download_rclone_bundle(target_root: Path) -> Path:
    target_root.mkdir(parents=True, exist_ok=True)
    bundle_dir = target_root / "rclone"
    if (bundle_dir / "rclone.exe").exists():
        return bundle_dir

    zip_file_path = target_root / "rclone-current-windows-amd64.zip"
    with requests.get(RCLONE_DOWNLOAD_URL, stream=True, timeout=60) as response:
        response.raise_for_status()
        with open(zip_file_path, "wb") as zip_file:
            for chunk in response.iter_content(1024 * 1024):
                if chunk:
                    zip_file.write(chunk)

    try:
        return _extract_rclone_zip(zip_file_path, target_root)
    finally:
        zip_file_path.unlink(missing_ok=True)


def _resolve_rclone_bundle() -> Path:
    explicit_dir = os.environ.get("DLR_RCLONE_DIR")
    if explicit_dir:
        return _copy_local_rclone_bundle(Path(explicit_dir), BUILD_ASSET_ROOT)

    repo_bundle = PROJECT_ROOT / "rclone"
    if (repo_bundle / "rclone.exe").exists():
        return repo_bundle

    return _download_rclone_bundle(BUILD_ASSET_ROOT)


def _prepare_packaged_config(source_config_dir: Path, target_root: Path) -> Path:
    packaged_config_dir = target_root / "config"
    if packaged_config_dir.exists():
        shutil.rmtree(packaged_config_dir)
    shutil.copytree(source_config_dir, packaged_config_dir)

    config_path = packaged_config_dir / "config.ini"
    config = configparser.RawConfigParser()
    config.optionxform = str
    config.read(config_path, encoding="utf-8-sig")
    if not config.has_section("自动上传"):
        config.add_section("自动上传")
    config.set("自动上传", "rclone可执行文件路径", r"rclone\rclone.exe")
    with open(config_path, "w", encoding="utf-8-sig") as config_file:
        config.write(config_file)
    return packaged_config_dir


hiddenimports = ["execjs"]
hiddenimports += collect_submodules("src.platforms")

a = Analysis(
    ["main.py"],
    pathex=[str(PROJECT_ROOT)],
    binaries=[],
    datas=[
        (str(_prepare_packaged_config(PROJECT_ROOT / "config", BUILD_ASSET_ROOT)), "config"),
        (str(PROJECT_ROOT / "i18n"), "i18n"),
        (str(PROJECT_ROOT / "src" / "javascript"), "src/javascript"),
        (str(PROJECT_ROOT / "index.html"), "."),
        (str(PROJECT_ROOT / "StopRecording.vbs"), "."),
        (str(_resolve_node_bundle()), "node"),
        (str(_resolve_ffmpeg_bundle()), "ffmpeg"),
        (str(_resolve_rclone_bundle()), "rclone"),
    ],
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="DouyinLiveRecorder",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    contents_directory=".",
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="DouyinLiveRecorder",
)
