from __future__ import annotations

from dataclasses import dataclass, field

from .enums import ProxyMode, QualityLevel, SaveType


@dataclass(slots=True)
class RecordingConfig:
    language: str = "zh_cn"
    skip_proxy_check: bool = False
    save_path: str = ""
    folder_by_author: bool = True
    folder_by_time: bool = False
    folder_by_title: bool = False
    filename_by_title: bool = False
    clean_emoji: bool = True
    save_type: SaveType = SaveType.TS
    default_quality: QualityLevel = QualityLevel.ORIGIN
    use_proxy: bool = False
    proxy_mode: ProxyMode = ProxyMode.DISABLED
    proxy_address: str = ""
    max_request: int = 5
    loop_delay_seconds: int = 120
    queue_delay_seconds: int = 0
    show_loop_time: bool = False
    show_stream_url: bool = False
    split_video_by_time: bool = False
    enable_https_recording: bool = False
    disk_space_limit_gb: float = 1.0
    split_time_seconds: str = "1800"
    converts_to_mp4: bool = False
    converts_to_h264: bool = False
    delete_origin_file: bool = False
    create_time_file: bool = False
    run_script_after_record: bool = False
    custom_script: str | None = None
    proxy_platforms: tuple[str, ...] = field(default_factory=tuple)
    extra_proxy_platforms: tuple[str, ...] = field(default_factory=tuple)


@dataclass(slots=True)
class PushConfig:
    channels: str = ""
    dingtalk_api_url: str = ""
    xizhi_api_url: str = ""
    bark_api_url: str = ""
    bark_level: str = "active"
    bark_ring: str = "bell"
    dingtalk_phone_num: str = ""
    dingtalk_is_atall: bool = False
    tg_token: str = ""
    tg_chat_id: str = ""
    email_host: str = ""
    open_smtp_ssl: bool = True
    smtp_port: str = ""
    login_email: str = ""
    email_password: str = ""
    sender_email: str = ""
    sender_name: str = ""
    to_email: str = ""
    ntfy_api: str = ""
    ntfy_tags: str = "tada"
    ntfy_email: str = ""
    pushplus_token: str = ""
    push_message_title: str = "直播间状态更新通知"
    begin_push_message_text: str = ""
    over_push_message_text: str = ""
    disable_record: bool = False
    push_check_seconds: int = 1800
    begin_show_push: bool = True
    over_show_push: bool = False


@dataclass(slots=True)
class AuthorizationConfig:
    popkontv_token: str = ""


@dataclass(slots=True)
class AccountConfig:
    sooplive_username: str = ""
    sooplive_password: str = ""
    flextv_username: str = ""
    flextv_password: str = ""
    popkontv_username: str = ""
    popkontv_partner_code: str = "P-00001"
    popkontv_password: str = ""
    twitcasting_account_type: str = "normal"
    twitcasting_username: str = ""
    twitcasting_password: str = ""


@dataclass(slots=True)
class CookieConfig:
    values: dict[str, str] = field(default_factory=dict)

    def get(self, key: str, default: str = "") -> str:
        return self.values.get(key, default)


@dataclass(slots=True)
class UploadConfig:
    enabled: bool = False
    execution_mode: str = "rc"
    trigger_mode: str = "录制结束"
    daily_time: str = "03:00"
    interval_seconds: int = 300
    source_path: str = ""
    remote_path: str = "123pan:/LiveBackup/"
    rclone_path: str = ""
    rc_port: int = 5572
    min_age: str = "1h"
    transfers: int = 2
    checkers: int = 2
    rclone_retries: int = 3
    app_retries: int = 3
    retry_sleep_seconds: int = 900
    webdav_remote_name: str = ""
    webdav_url: str = ""
    webdav_username: str = ""
    webdav_password: str = ""
    webdav_vendor: str = "other"
    delete_empty_dirs: bool = True
    dry_run: bool = False


@dataclass(slots=True)
class AppConfig:
    recording: RecordingConfig
    push: PushConfig
    authorization: AuthorizationConfig
    accounts: AccountConfig
    cookies: CookieConfig
    upload: UploadConfig = field(default_factory=UploadConfig)


@dataclass(slots=True)
class UrlConfigEntry:
    quality: QualityLevel
    url: str
    name: str = ""
    is_comment: bool = False

    def to_tuple(self) -> tuple[str, str, str]:
        return (self.quality.value, self.url, self.name)
