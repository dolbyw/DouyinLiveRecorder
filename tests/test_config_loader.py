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


def test_write_default_config_ensures_all_required_sections():
    with tempfile.TemporaryDirectory(dir=".") as tmp_dir:
        config_path = Path(tmp_dir) / "config.ini"
        config = load_raw_config(str(config_path))

        write_default_config(str(config_path), config)
        written = load_raw_config(str(config_path))

        assert set(written.sections()) == {"录制设置", "推送配置", "Cookie", "Authorization", "账号密码"}


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
