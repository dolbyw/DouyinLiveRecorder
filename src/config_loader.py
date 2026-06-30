from __future__ import annotations

import configparser
import os
import re
from pathlib import Path

from .models import (
    AccountConfig,
    AppConfig,
    AuthorizationConfig,
    CookieConfig,
    ProxyMode,
    PushConfig,
    QualityLevel,
    RecordingConfig,
    SaveType,
    UploadConfig,
    UrlConfigEntry,
)

CONFIG_SECTIONS = (
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
)
OPTIONS = {"是": True, "否": False}

COOKIE_KEYS = (
    "抖音cookie",
    "快手cookie",
    "tiktok_cookie",
    "虎牙cookie",
    "斗鱼cookie",
    "yy_cookie",
    "B站cookie",
    "小红书cookie",
    "bigo_cookie",
    "blued_cookie",
    "sooplive_cookie",
    "netease_cookie",
    "千度热播_cookie",
    "pandatv_cookie",
    "猫耳fm_cookie",
    "winktv_cookie",
    "flextv_cookie",
    "look_cookie",
    "twitcasting_cookie",
    "baidu_cookie",
    "weibo_cookie",
    "kugou_cookie",
    "twitch_cookie",
    "liveme_cookie",
    "huajiao_cookie",
    "liuxing_cookie",
    "showroom_cookie",
    "acfun_cookie",
    "changliao_cookie",
    "yinbo_cookie",
    "yingke_cookie",
    "zhihu_cookie",
    "chzzk_cookie",
    "haixiu_cookie",
    "vvxqiu_cookie",
    "17live_cookie",
    "langlive_cookie",
    "pplive_cookie",
    "6room_cookie",
    "lehaitv_cookie",
    "huamao_cookie",
    "shopee_cookie",
    "youtube_cookie",
    "taobao_cookie",
    "jd_cookie",
    "faceit_cookie",
    "migu_cookie",
    "lianjie_cookie",
    "laixiu_cookie",
    "picarto_cookie",
)

DEFAULT_PROXY_PLATFORMS = (
    "tiktok, soop, pandalive, winktv, flextv, popkontv, twitch, liveme, showroom, chzzk, shopee, shp, youtu, faceit"
)


PLATFORM_HOSTS = (
    "live.douyin.com",
    "v.douyin.com",
    "www.douyin.com",
    "live.kuaishou.com",
    "www.huya.com",
    "www.douyu.com",
    "www.yy.com",
    "live.bilibili.com",
    "www.redelight.cn",
    "www.xiaohongshu.com",
    "xhslink.com",
    "www.bigo.tv",
    "slink.bigovideo.tv",
    "app.blued.cn",
    "cc.163.com",
    "qiandurebo.com",
    "fm.missevan.com",
    "look.163.com",
    "twitcasting.tv",
    "live.baidu.com",
    "weibo.com",
    "fanxing.kugou.com",
    "fanxing2.kugou.com",
    "mfanxing.kugou.com",
    "www.huajiao.com",
    "www.7u66.com",
    "wap.7u66.com",
    "live.acfun.cn",
    "m.acfun.cn",
    "live.tlclw.com",
    "wap.tlclw.com",
    "live.ybw1666.com",
    "wap.ybw1666.com",
    "www.inke.cn",
    "www.zhihu.com",
    "www.haixiutv.com",
    "h5webcdnp.vvxqiu.com",
    "17.live",
    "www.lang.live",
    "m.pp.weimipopo.com",
    "v.6.cn",
    "m.6.cn",
    "www.lehaitv.com",
    "h.catshow168.com",
    "e.tb.cn",
    "huodong.m.taobao.com",
    "3.cn",
    "eco.m.jd.com",
    "www.miguvideo.com",
    "m.miguvideo.com",
    "show.lailianjie.com",
    "www.imkktv.com",
    "www.picarto.tv",
)

OVERSEAS_PLATFORM_HOSTS = (
    "www.tiktok.com",
    "play.sooplive.co.kr",
    "m.sooplive.co.kr",
    "www.sooplive.com",
    "m.sooplive.com",
    "www.pandalive.co.kr",
    "www.winktv.co.kr",
    "www.flextv.co.kr",
    "www.ttinglive.com",
    "www.popkontv.com",
    "www.twitch.tv",
    "www.liveme.com",
    "www.showroom-live.com",
    "chzzk.naver.com",
    "m.chzzk.naver.com",
    "live.shopee.",
    ".shp.ee",
    "www.youtube.com",
    "youtu.be",
    "www.faceit.com",
)

SUPPORTED_URL_HOSTS = PLATFORM_HOSTS + OVERSEAS_PLATFORM_HOSTS

CLEAN_URL_HOSTS = (
    "live.douyin.com",
    "live.bilibili.com",
    "www.huajiao.com",
    "www.zhihu.com",
    "www.huya.com",
    "chzzk.naver.com",
    "www.liveme.com",
    "www.haixiutv.com",
    "v.6.cn",
    "m.6.cn",
    "www.lehaitv.com",
)


def ensure_config_sections(config: configparser.RawConfigParser) -> None:
    for section in CONFIG_SECTIONS:
        if section not in config.sections():
            config.add_section(section)


def load_raw_config(config_path: str, encoding: str = "utf-8-sig") -> configparser.RawConfigParser:
    config = configparser.RawConfigParser()
    if Path(config_path).exists():
        config.read(config_path, encoding=encoding)
    ensure_config_sections(config)
    return config


def write_default_config(config_path: str, config: configparser.RawConfigParser, encoding: str = "utf-8-sig") -> None:
    ensure_config_sections(config)
    path = Path(config_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding=encoding) as file:
        config.write(file)


def _read_string(
    config: configparser.RawConfigParser,
    section: str,
    option: str,
    default: str = "",
    *,
    env_name: str | None = None,
) -> str:
    if env_name:
        env_value = os.getenv(env_name)
        if env_value is not None:
            return env_value
    return config.get(section, option, fallback=default).strip()


def _read_bool(config: configparser.RawConfigParser, section: str, option: str, default: bool) -> bool:
    default_label = "是" if default else "否"
    return OPTIONS.get(_read_string(config, section, option, default_label), default)


def _read_int(config: configparser.RawConfigParser, section: str, option: str, default: int) -> int:
    try:
        return int(_read_string(config, section, option, str(default)))
    except ValueError:
        return default


def _read_min_int(
    config: configparser.RawConfigParser,
    section: str,
    option: str,
    default: int,
    minimum: int,
) -> int:
    return max(minimum, _read_int(config, section, option, default))


def _read_float(config: configparser.RawConfigParser, section: str, option: str, default: float) -> float:
    try:
        return float(_read_string(config, section, option, str(default)))
    except ValueError:
        return default


def _normalize_upload_trigger(value: str) -> str:
    normalized = value.strip().lower()
    if normalized in {"间隔", "间隔检查", "interval", "interval_check"}:
        return "间隔"
    if normalized in {"定时", "每日定时", "daily", "scheduled", "schedule"}:
        return "定时"
    return "录制结束"


def _read_upload_trigger(config: configparser.RawConfigParser) -> str:
    requested = _normalize_upload_trigger(_read_string(config, "自动上传", "上传触发模式", "录制结束"))
    enabled_sections = [
        trigger
        for trigger, section in (
            ("录制结束", "自动上传-录制结束"),
            ("定时", "自动上传-每日定时"),
            ("间隔", "自动上传-间隔检查"),
        )
        if _read_bool(config, section, "是否启用", False)
    ]
    if len(enabled_sections) == 1:
        return enabled_sections[0]
    return requested


def _read_csv(config: configparser.RawConfigParser, section: str, option: str, default: str = "") -> tuple[str, ...]:
    raw_value = _read_string(config, section, option, default)
    return tuple(item.strip() for item in raw_value.replace("，", ",").split(",") if item.strip())


def _looks_like_url(value: str) -> bool:
    return "://" in value or "." in value


def parse_url_config_entry(raw_line: str, default_quality: str = "原画") -> UrlConfigEntry | None:
    line = raw_line.strip()
    if len(line) < 18:
        return None

    is_comment = line.startswith("#")
    if is_comment:
        line = line.lstrip("#")

    split_line = [segment.strip() for segment in line.replace("，", ",").split(",")]

    if len(split_line) == 1:
        url = split_line[0]
        quality = default_quality
        name = ""
    elif len(split_line) == 2:
        if _looks_like_url(split_line[0]):
            quality = default_quality
            url, name = split_line
        else:
            quality, url = split_line
            name = ""
    else:
        quality, url, name = split_line[0], split_line[1], split_line[2]

    return UrlConfigEntry(
        quality=QualityLevel.from_raw(quality, default=QualityLevel.ORIGIN),
        url=url,
        name=name,
        is_comment=is_comment,
    )


def canonicalize_url_host(url: str) -> str:
    url_host = url.split("/")[2]
    if "live.shopee." in url_host:
        return "live.shopee."
    if ".shp.ee" in url_host:
        return ".shp.ee"
    return url_host


def normalize_url_value(url: str) -> str:
    normalized_url = url if "://" in url else f"https://{url}"
    url_host = canonicalize_url_host(normalized_url)

    if url_host in CLEAN_URL_HOSTS:
        normalized_url = normalized_url.split("?")[0]

    if "xiaohongshu" in normalized_url:
        host_id = re.search(r"&host_id=(.*?)(?=&|$)", normalized_url)
        if host_id:
            normalized_url = normalized_url.split("?")[0] + f"?host_id={host_id.group(1)}"

    return normalized_url


def is_supported_url(url: str) -> bool:
    normalized_url = normalize_url_value(url)
    url_host = canonicalize_url_host(normalized_url)
    return url_host in SUPPORTED_URL_HOSTS or any(ext in normalized_url for ext in (".flv", ".m3u8"))


def normalize_url_config_entry(entry: UrlConfigEntry) -> UrlConfigEntry | None:
    normalized_url = normalize_url_value(entry.url)
    if not is_supported_url(normalized_url):
        return None
    return UrlConfigEntry(
        quality=entry.quality,
        url=normalized_url,
        name=entry.name,
        is_comment=entry.is_comment,
    )


def load_app_config(config_path: str, encoding: str = "utf-8-sig") -> AppConfig:
    config = load_raw_config(config_path, encoding=encoding)

    recording = RecordingConfig(
        language=_read_string(config, "录制设置", "language(zh_cn/en)", "zh_cn"),
        skip_proxy_check=_read_bool(config, "录制设置", "是否跳过代理检测(是/否)", False),
        save_path=_read_string(config, "录制设置", "直播保存路径(不填则默认)", ""),
        folder_by_author=_read_bool(config, "录制设置", "保存文件夹是否以作者区分", True),
        folder_by_time=_read_bool(config, "录制设置", "保存文件夹是否以时间区分", False),
        folder_by_title=_read_bool(config, "录制设置", "保存文件夹是否以标题区分", False),
        filename_by_title=_read_bool(config, "录制设置", "保存文件名是否包含标题", False),
        clean_emoji=_read_bool(config, "录制设置", "是否去除名称中的表情符号", True),
        save_type=SaveType.from_raw(
            _read_string(config, "录制设置", "视频保存格式ts|mkv|flv|mp4|mp3音频|m4a音频", "ts")
        ),
        default_quality=QualityLevel.from_raw(_read_string(config, "录制设置", "原画|超清|高清|标清|流畅", "原画")),
        use_proxy=_read_bool(config, "录制设置", "是否使用代理ip(是/否)", False),
        proxy_address=_read_string(config, "录制设置", "代理地址", ""),
        max_request=max(1, _read_int(config, "录制设置", "同一时间访问网络的线程数", 5)),
        loop_delay_seconds=_read_int(config, "录制设置", "循环时间(秒)", 120),
        queue_delay_seconds=_read_int(config, "录制设置", "排队读取网址时间(秒)", 0),
        show_loop_time=_read_bool(config, "录制设置", "是否显示循环秒数", False),
        show_stream_url=_read_bool(config, "录制设置", "是否显示直播源地址", False),
        split_video_by_time=_read_bool(config, "录制设置", "分段录制是否开启", False),
        enable_https_recording=_read_bool(config, "录制设置", "是否强制启用https录制", False),
        disk_space_limit_gb=_read_float(config, "录制设置", "录制空间剩余阈值(gb)", 1.0),
        split_time_seconds=_read_string(config, "录制设置", "视频分段时间(秒)", "1800"),
        converts_to_mp4=_read_bool(config, "录制设置", "录制完成后自动转为mp4格式", False),
        converts_to_h264=_read_bool(config, "录制设置", "mp4格式重新编码为h264", False),
        delete_origin_file=_read_bool(config, "录制设置", "追加格式后删除原文件", False),
        create_time_file=_read_bool(config, "录制设置", "生成时间字幕文件", False),
        run_script_after_record=_read_bool(config, "录制设置", "是否录制完成后执行自定义脚本", False),
        custom_script=_read_string(config, "录制设置", "自定义脚本执行命令", "") or None,
        proxy_platforms=_read_csv(
            config,
            "录制设置",
            "使用代理录制的平台(逗号分隔)",
            DEFAULT_PROXY_PLATFORMS,
        ),
        extra_proxy_platforms=_read_csv(config, "录制设置", "额外使用代理录制的平台(逗号分隔)", ""),
    )
    recording.proxy_mode = ProxyMode.GLOBAL if recording.use_proxy else ProxyMode.DISABLED

    push = PushConfig(
        channels=_read_string(config, "推送配置", "直播状态推送渠道", ""),
        dingtalk_api_url=_read_string(config, "推送配置", "钉钉推送接口链接", ""),
        xizhi_api_url=_read_string(config, "推送配置", "微信推送接口链接", ""),
        bark_api_url=_read_string(config, "推送配置", "bark推送接口链接", ""),
        bark_level=_read_string(config, "推送配置", "bark推送中断级别", "active"),
        bark_ring=_read_string(config, "推送配置", "bark推送铃声", "bell"),
        dingtalk_phone_num=_read_string(config, "推送配置", "钉钉通知@对象(填手机号)", ""),
        dingtalk_is_atall=_read_bool(config, "推送配置", "钉钉通知@全体(是/否)", False),
        tg_token=_read_string(config, "推送配置", "tgapi令牌", ""),
        tg_chat_id=_read_string(config, "推送配置", "tg聊天id(个人或者群组id)", ""),
        email_host=_read_string(config, "推送配置", "SMTP邮件服务器", ""),
        open_smtp_ssl=_read_bool(config, "推送配置", "是否使用SMTP服务SSL加密(是/否)", True),
        smtp_port=_read_string(config, "推送配置", "SMTP邮件服务器端口", ""),
        login_email=_read_string(config, "推送配置", "邮箱登录账号", ""),
        email_password=_read_string(
            config,
            "推送配置",
            "发件人密码(授权码)",
            "",
            env_name="DLR_EMAIL_PASSWORD",
        ),
        sender_email=_read_string(config, "推送配置", "发件人邮箱", ""),
        sender_name=_read_string(config, "推送配置", "发件人显示昵称", ""),
        to_email=_read_string(config, "推送配置", "收件人邮箱", ""),
        ntfy_api=_read_string(config, "推送配置", "ntfy推送地址", ""),
        ntfy_tags=_read_string(config, "推送配置", "ntfy推送标签", "tada"),
        ntfy_email=_read_string(config, "推送配置", "ntfy推送邮箱", ""),
        pushplus_token=_read_string(config, "推送配置", "pushplus推送token", ""),
        push_message_title=_read_string(config, "推送配置", "自定义推送标题", "直播间状态更新通知"),
        begin_push_message_text=_read_string(config, "推送配置", "自定义开播推送内容", ""),
        over_push_message_text=_read_string(config, "推送配置", "自定义关播推送内容", ""),
        disable_record=_read_bool(config, "推送配置", "只推送通知不录制(是/否)", False),
        push_check_seconds=_read_int(config, "推送配置", "直播推送检测频率(秒)", 1800),
        begin_show_push=_read_bool(config, "推送配置", "开播推送开启(是/否)", True),
        over_show_push=_read_bool(config, "推送配置", "关播推送开启(是/否)", False),
    )

    authorization = AuthorizationConfig(
        popkontv_token=_read_string(
            config,
            "Authorization",
            "popkontv_token",
            "",
            env_name="DLR_POPKONTV_TOKEN",
        )
    )

    accounts = AccountConfig(
        sooplive_username=_read_string(config, "账号密码", "sooplive账号", ""),
        sooplive_password=_read_string(config, "账号密码", "sooplive密码", "", env_name="DLR_SOOPLIVE_PASSWORD"),
        flextv_username=_read_string(config, "账号密码", "flextv账号", ""),
        flextv_password=_read_string(config, "账号密码", "flextv密码", "", env_name="DLR_FLEXTV_PASSWORD"),
        popkontv_username=_read_string(config, "账号密码", "popkontv账号", ""),
        popkontv_partner_code=_read_string(config, "账号密码", "partner_code", "P-00001"),
        popkontv_password=_read_string(config, "账号密码", "popkontv密码", "", env_name="DLR_POPKONTV_PASSWORD"),
        twitcasting_account_type=_read_string(config, "账号密码", "twitcasting账号类型", "normal"),
        twitcasting_username=_read_string(config, "账号密码", "twitcasting账号", ""),
        twitcasting_password=_read_string(
            config,
            "账号密码",
            "twitcasting密码",
            "",
            env_name="DLR_TWITCASTING_PASSWORD",
        ),
    )

    cookies = CookieConfig(
        values={key: _read_string(config, "Cookie", key, "") for key in COOKIE_KEYS},
    )

    upload_trigger = _read_upload_trigger(config)
    legacy_daily_time = _read_string(config, "自动上传", "每日定时上传时间", "03:00")
    legacy_interval_seconds = _read_min_int(config, "自动上传", "上传检查间隔(秒)", 300, 1)
    upload = UploadConfig(
        enabled=_read_bool(config, "自动上传", "是否启用自动上传", False),
        execution_mode=_read_string(config, "自动上传", "上传执行方式", "rc"),
        trigger_mode=upload_trigger,
        daily_time=(
            _read_string(config, "自动上传-每日定时", "每日定时上传时间", legacy_daily_time)
            if upload_trigger == "定时"
            else legacy_daily_time
        ),
        interval_seconds=(
            _read_min_int(config, "自动上传-间隔检查", "上传检查间隔(秒)", legacy_interval_seconds, 1)
            if upload_trigger == "间隔"
            else legacy_interval_seconds
        ),
        source_path=_read_string(config, "自动上传", "上传源目录(不填则跟随直播保存路径)", ""),
        remote_path=_read_string(config, "自动上传", "上传目标路径", "123pan:/LiveBackup/"),
        rclone_path=_read_string(config, "自动上传", "rclone可执行文件路径", ""),
        rc_port=_read_min_int(config, "自动上传", "rclone控制端口", 5572, 1),
        min_age=_read_string(config, "自动上传", "最小文件冷却时间", "1h"),
        transfers=_read_min_int(config, "自动上传", "上传并发数", 2, 1),
        checkers=_read_min_int(config, "自动上传", "检查并发数", 2, 1),
        rclone_retries=_read_min_int(config, "自动上传", "rclone失败重试次数", 3, 0),
        app_retries=_read_min_int(config, "自动上传", "应用层失败重试次数", 3, 0),
        retry_sleep_seconds=_read_min_int(config, "自动上传", "失败后等待秒数", 900, 0),
        webdav_remote_name=_read_string(config, "自动上传-WebDAV", "远程名称", ""),
        webdav_url=_read_string(config, "自动上传-WebDAV", "WebDAV地址", ""),
        webdav_username=_read_string(config, "自动上传-WebDAV", "WebDAV用户名", ""),
        webdav_password=_read_string(config, "自动上传-WebDAV", "WebDAV密码", ""),
        webdav_vendor=_read_string(config, "自动上传-WebDAV", "WebDAV厂商", "other") or "other",
        delete_empty_dirs=_read_bool(config, "自动上传", "上传完成后删除空目录", True),
        dry_run=_read_bool(config, "自动上传", "演练模式dry-run", False),
    )

    return AppConfig(
        recording=recording,
        push=push,
        authorization=authorization,
        accounts=accounts,
        cookies=cookies,
        upload=upload,
    )
