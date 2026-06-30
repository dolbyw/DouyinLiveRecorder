import tempfile
import textwrap
from pathlib import Path

from src.config_loader import load_app_config, load_raw_config, write_default_config
from src.models import ProxyMode, QualityLevel, SaveType


def test_load_app_config_maps_core_sections_and_normalizes_values(monkeypatch):
    with tempfile.TemporaryDirectory(dir=".") as tmp_dir:
        config_path = Path(tmp_dir) / "config.ini"
        config_path.write_text(
            textwrap.dedent(
                """
                [录制设置]
                language(zh_cn/en) = en
                是否跳过代理检测(是/否) = 是
                视频保存格式ts|mkv|flv|mp4|mp3音频|m4a音频 = m4a音频
                原画|超清|高清|标清|流畅 = 高清
                是否使用代理ip(是/否) = 是
                代理地址 = 127.0.0.1:7890
                同一时间访问网络的线程数 = 8
                使用代理录制的平台(逗号分隔) = tiktok, showroom
                额外使用代理录制的平台(逗号分隔) = youtube， twitch

                [推送配置]
                发件人密码(授权码) = from-file

                [Authorization]
                popkontv_token = old-token

                [账号密码]
                popkontv密码 = old-password

                [Cookie]
                抖音cookie = abc
                """
            ).strip(),
            encoding="utf-8-sig",
        )

        monkeypatch.setenv("DLR_EMAIL_PASSWORD", "from-env")
        monkeypatch.setenv("DLR_POPKONTV_TOKEN", "token-from-env")
        monkeypatch.setenv("DLR_POPKONTV_PASSWORD", "password-from-env")

        app_config = load_app_config(str(config_path))

        assert app_config.recording.language == "en"
        assert app_config.recording.skip_proxy_check is True
        assert app_config.recording.save_type is SaveType.M4A
        assert app_config.recording.default_quality is QualityLevel.HD
        assert app_config.recording.proxy_mode is ProxyMode.GLOBAL
        assert app_config.recording.max_request == 8
        assert app_config.recording.proxy_platforms == ("tiktok", "showroom")
        assert app_config.recording.extra_proxy_platforms == ("youtube", "twitch")
        assert app_config.push.email_password == "from-env"
        assert app_config.authorization.popkontv_token == "token-from-env"
        assert app_config.accounts.popkontv_password == "password-from-env"
        assert app_config.cookies.get("抖音cookie") == "abc"


def test_load_app_config_maps_auto_upload_section():
    with tempfile.TemporaryDirectory(dir=".") as tmp_dir:
        config_path = Path(tmp_dir) / "config.ini"
        config_path.write_text(
            textwrap.dedent(
                """
                [自动上传]
                是否启用自动上传 = 是
                上传执行方式 = 命令行
                上传触发模式 = 间隔
                每日定时上传时间 = 04:30
                上传检查间隔(秒) = 600
                上传源目录(不填则跟随直播保存路径) = D:\\LiveRecords
                上传目标路径 = 123pan:/LiveBackup/
                rclone可执行文件路径 = C:\\Tools\\rclone\\rclone.exe
                rclone控制端口 = 5573
                最小文件冷却时间 = 2h
                上传并发数 = 2
                检查并发数 = 2
                rclone失败重试次数 = 4
                应用层失败重试次数 = 5
                失败后等待秒数 = 1200
                上传完成后删除空目录 = 否
                演练模式dry-run = 是
                """
            ).strip(),
            encoding="utf-8-sig",
        )

        app_config = load_app_config(str(config_path))

        assert app_config.upload.enabled is True
        assert app_config.upload.execution_mode == "命令行"
        assert app_config.upload.trigger_mode == "间隔"
        assert app_config.upload.daily_time == "04:30"
        assert app_config.upload.interval_seconds == 600
        assert app_config.upload.source_path == "D:\\LiveRecords"
        assert app_config.upload.remote_path == "123pan:/LiveBackup/"
        assert app_config.upload.rclone_path == "C:\\Tools\\rclone\\rclone.exe"
        assert app_config.upload.rc_port == 5573
        assert app_config.upload.min_age == "2h"
        assert app_config.upload.transfers == 2
        assert app_config.upload.checkers == 2
        assert app_config.upload.rclone_retries == 4
        assert app_config.upload.app_retries == 5
        assert app_config.upload.retry_sleep_seconds == 1200
        assert app_config.upload.delete_empty_dirs is False
        assert app_config.upload.dry_run is True


def test_auto_upload_trigger_sections_are_mutually_selected_by_trigger_mode():
    with tempfile.TemporaryDirectory(dir=".") as tmp_dir:
        config_path = Path(tmp_dir) / "config.ini"
        config_path.write_text(
            textwrap.dedent(
                """
                [自动上传]
                是否启用自动上传 = 是
                上传触发模式 = 每日定时

                [自动上传-录制结束]
                是否启用 = 是

                [自动上传-每日定时]
                是否启用 = 是
                每日定时上传时间 = 04:30

                [自动上传-间隔检查]
                是否启用 = 是
                上传检查间隔(秒) = 600
                """
            ).strip(),
            encoding="utf-8-sig",
        )

        app_config = load_app_config(str(config_path))

        assert app_config.upload.trigger_mode == "定时"
        assert app_config.upload.daily_time == "04:30"
        assert app_config.upload.interval_seconds == 300


def test_auto_upload_uses_enabled_trigger_section_when_only_one_is_enabled():
    with tempfile.TemporaryDirectory(dir=".") as tmp_dir:
        config_path = Path(tmp_dir) / "config.ini"
        config_path.write_text(
            textwrap.dedent(
                """
                [自动上传]
                是否启用自动上传 = 是

                [自动上传-间隔检查]
                是否启用 = 是
                上传检查间隔(秒) = 900
                """
            ).strip(),
            encoding="utf-8-sig",
        )

        app_config = load_app_config(str(config_path))

        assert app_config.upload.trigger_mode == "间隔"
        assert app_config.upload.interval_seconds == 900


def test_auto_upload_maps_webdav_section():
    with tempfile.TemporaryDirectory(dir=".") as tmp_dir:
        config_path = Path(tmp_dir) / "config.ini"
        config_path.write_text(
            textwrap.dedent(
                """
                [自动上传-WebDAV]
                远程名称 = 123pan
                WebDAV地址 = https://webdav.example.com/dav
                WebDAV用户名 = user@example.com
                WebDAV密码 = plain-password
                WebDAV厂商 = other
                """
            ).strip(),
            encoding="utf-8-sig",
        )

        app_config = load_app_config(str(config_path))

        assert app_config.upload.webdav_remote_name == "123pan"
        assert app_config.upload.webdav_url == "https://webdav.example.com/dav"
        assert app_config.upload.webdav_username == "user@example.com"
        assert app_config.upload.webdav_password == "plain-password"
        assert app_config.upload.webdav_vendor == "other"


def test_missing_auto_upload_section_uses_disabled_safe_defaults():
    with tempfile.TemporaryDirectory(dir=".") as tmp_dir:
        config_path = Path(tmp_dir) / "config.ini"
        config_path.write_text("[录制设置]\n直播保存路径(不填则默认) = D:\\Records", encoding="utf-8-sig")

        app_config = load_app_config(str(config_path))

        assert app_config.upload.enabled is False
        assert app_config.upload.execution_mode == "rc"
        assert app_config.upload.trigger_mode == "录制结束"
        assert app_config.upload.daily_time == "03:00"
        assert app_config.upload.interval_seconds == 300
        assert app_config.upload.source_path == ""
        assert app_config.upload.remote_path == "123pan:/LiveBackup/"
        assert app_config.upload.rclone_path == ""
        assert app_config.upload.rc_port == 5572
        assert app_config.upload.min_age == "1h"
        assert app_config.upload.transfers == 2
        assert app_config.upload.checkers == 2
        assert app_config.upload.rclone_retries == 3
        assert app_config.upload.app_retries == 3
        assert app_config.upload.retry_sleep_seconds == 900
        assert app_config.upload.delete_empty_dirs is True
        assert app_config.upload.dry_run is False
        assert app_config.upload.webdav_remote_name == ""
        assert app_config.upload.webdav_url == ""
        assert app_config.upload.webdav_username == ""
        assert app_config.upload.webdav_password == ""
        assert app_config.upload.webdav_vendor == "other"


def test_auto_upload_numeric_values_use_safe_minimums():
    with tempfile.TemporaryDirectory(dir=".") as tmp_dir:
        config_path = Path(tmp_dir) / "config.ini"
        config_path.write_text(
            textwrap.dedent(
                """
                [自动上传]
                上传检查间隔(秒) = 0
                rclone控制端口 = 0
                上传并发数 = -9
                检查并发数 = -1
                rclone失败重试次数 = -2
                应用层失败重试次数 = -3
                失败后等待秒数 = -10
                """
            ).strip(),
            encoding="utf-8-sig",
        )

        app_config = load_app_config(str(config_path))

        assert app_config.upload.interval_seconds == 1
        assert app_config.upload.rc_port == 1
        assert app_config.upload.transfers == 1
        assert app_config.upload.checkers == 1
        assert app_config.upload.rclone_retries == 0
        assert app_config.upload.app_retries == 0
        assert app_config.upload.retry_sleep_seconds == 0


def test_write_default_config_ensures_all_required_sections():
    with tempfile.TemporaryDirectory(dir=".") as tmp_dir:
        config_path = Path(tmp_dir) / "config.ini"
        config = load_raw_config(str(config_path))

        write_default_config(str(config_path), config)
        written = load_raw_config(str(config_path))

        assert set(written.sections()) == {
            "录制设置",
            "推送配置",
            "Cookie",
            "Authorization",
            "账号密码",
            "自动上传",
            "自动上传-录制结束",
            "自动上传-每日定时",
            "自动上传-间隔检查",
            "自动上传-WebDAV",
        }


def test_missing_network_concurrency_uses_safe_default_of_five():
    with tempfile.TemporaryDirectory(dir=".") as tmp_dir:
        config_path = Path(tmp_dir) / "config.ini"
        config_path.write_text("[录制设置]\n循环时间(秒) = 300", encoding="utf-8-sig")

        app_config = load_app_config(str(config_path))

        assert app_config.recording.max_request == 5


def test_non_positive_network_concurrency_uses_safe_minimum():
    with tempfile.TemporaryDirectory(dir=".") as tmp_dir:
        config_path = Path(tmp_dir) / "config.ini"
        config_path.write_text(
            "[录制设置]\n同一时间访问网络的线程数 = -1",
            encoding="utf-8-sig",
        )

        app_config = load_app_config(str(config_path))

        assert app_config.recording.max_request == 1
