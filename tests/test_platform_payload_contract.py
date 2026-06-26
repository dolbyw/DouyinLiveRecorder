import json

import pytest

from src.models import make_stream_info, normalize_platform_payload
from src.http_clients.errors import HttpConnectError
from src.spider import (
    get_bilibili_room_info,
    get_huya_app_stream_url,
    get_kuaishou_stream_data,
    get_liveme_stream_url,
    get_netease_stream_data,
    get_pandatv_stream_data,
    get_twitchtv_stream_data,
)


def test_normalize_platform_payload_maps_live_status_and_keeps_extras():
    payload = normalize_platform_payload(
        {
            "anchor_name": "主播A",
            "live_status": True,
            "room_url": "https://live.bilibili.com/1",
            "title": "测试标题",
        }
    )

    assert payload["anchor_name"] == "主播A"
    assert payload["is_live"] is True
    assert payload["live_status"] is True
    assert payload["room_url"] == "https://live.bilibili.com/1"
    assert payload["title"] == "测试标题"


def test_make_stream_info_keeps_known_and_extra_fields():
    payload = make_stream_info(
        {
            "anchor_name": "主播B",
            "is_live": False,
            "play_url_list": [{"url": "https://example.test/live.m3u8"}],
        },
        quality="OD",
    )

    assert payload["anchor_name"] == "主播B"
    assert payload["is_live"] is False
    assert payload["quality"] == "OD"
    assert payload["play_url_list"] == [{"url": "https://example.test/live.m3u8"}]


@pytest.mark.asyncio
async def test_get_bilibili_room_info_returns_normalized_probe_shape(monkeypatch):
    async def fake_async_req(url, *args, **kwargs):
        if "room_init" in url:
            return json.dumps({"data": {"uid": 42, "live_status": 1}})
        if "Master/info" in url:
            return json.dumps({"data": {"info": {"uname": "主播C"}}})
        raise AssertionError(url)

    async def fake_get_bilibili_room_info_h5(url, proxy_addr=None, cookies=None):
        return "B站开播"

    monkeypatch.setattr("src.spider.async_req", fake_async_req)
    monkeypatch.setattr("src.spider.get_bilibili_room_info_h5", fake_get_bilibili_room_info_h5)

    result = await get_bilibili_room_info("https://live.bilibili.com/123")

    assert result["anchor_name"] == "主播C"
    assert result["is_live"] is True
    assert result["live_status"] is True
    assert result["room_url"] == "https://live.bilibili.com/123"
    assert result["title"] == "B站开播"


@pytest.mark.asyncio
async def test_get_kuaishou_stream_data_failure_path_returns_normalized_shape(monkeypatch):
    async def fake_async_req(*args, **kwargs):
        raise RuntimeError("network down")

    monkeypatch.setattr("src.spider.async_req", fake_async_req)

    result = await get_kuaishou_stream_data("https://live.kuaishou.com/u/test")

    assert result["anchor_name"] == ""
    assert result["is_live"] is False
    assert result["type"] == 1


@pytest.mark.asyncio
async def test_get_huya_app_stream_url_returns_normalized_live_shape(monkeypatch):
    async def fake_async_req(url, *args, **kwargs):
        if "cache.php" in url:
            return json.dumps(
                {
                    "data": {
                        "profileInfo": {"nick": "虎牙主播"},
                        "realLiveStatus": "ON",
                        "liveData": {"introduction": "虎牙标题"},
                        "stream": {
                            "baseSteamInfoList": [
                                {
                                    "sCdnType": "TX",
                                    "sStreamName": "live123",
                                    "sFlvUrl": "http://flv.example.test/live",
                                    "sFlvAntiCode": "a=1&ctype=tars_mp&fs=bhct",
                                    "sHlsUrl": "http://m3u8.example.test/live",
                                    "sHlsAntiCode": "b=2",
                                }
                            ]
                        },
                    }
                }
            )
        raise AssertionError(url)

    monkeypatch.setattr("src.spider.async_req", fake_async_req)

    result = await get_huya_app_stream_url("https://www.huya.com/123456")

    assert result["anchor_name"] == "虎牙主播"
    assert result["is_live"] is True
    assert result["title"] == "虎牙标题"
    assert result["record_url"].startswith("https://")
    assert result["play_url_list"][0]["cdn_type"] == "TX"


@pytest.mark.asyncio
async def test_get_netease_stream_data_returns_normalized_probe_shape(monkeypatch):
    async def fake_async_req(url, *args, **kwargs):
        return (
            '<script id="__NEXT_DATA__" type="application/json" crossorigin="anonymous">'
            + json.dumps(
                {
                    "props": {
                        "pageProps": {
                            "roomInfoInitData": {
                                "nickname": "网易主播",
                                "live": {
                                    "status": 1,
                                    "nickname": "网易主播",
                                    "title": "网易标题",
                                    "quickplay": {
                                        "resolution": {"high": {"cdn": {"main": "https://example.test/live.flv"}}}
                                    },
                                    "sharefile": "https://example.test/live.m3u8",
                                },
                            },
                        }
                    }
                }
            )
            + "</script></body>"
        )

    monkeypatch.setattr("src.spider.async_req", fake_async_req)

    result = await get_netease_stream_data("https://cc.163.com/123")

    assert result["anchor_name"] == "网易主播"
    assert result["is_live"] is True
    assert result["title"] == "网易标题"
    assert result["m3u8_url"] == "https://example.test/live.m3u8"
    assert "stream_list" in result


@pytest.mark.asyncio
async def test_get_pandatv_stream_data_returns_normalized_live_shape(monkeypatch):
    async def fake_async_req(url, *args, **kwargs):
        if "member/bj" in url:
            return json.dumps(
                {
                    "bjInfo": {
                        "id": "anchor-1",
                        "nick": "Panda主播",
                    },
                    "media": {"dummy": True},
                }
            )
        if "live/play" in url:
            return json.dumps({"PlayList": {"hls": [{"url": "https://example.test/panda/master.m3u8"}]}})
        raise AssertionError(url)

    async def fake_get_play_url_list(*args, **kwargs):
        return ["https://example.test/panda/720p.m3u8", "https://example.test/panda/480p.m3u8"]

    monkeypatch.setattr("src.spider.async_req", fake_async_req)
    monkeypatch.setattr("src.spider.get_play_url_list", fake_get_play_url_list)

    result = await get_pandatv_stream_data("https://www.pandalive.co.kr/live/anchor-1")

    assert result["anchor_name"] == "Panda主播-anchor-1"
    assert result["is_live"] is True
    assert result["m3u8_url"] == "https://example.test/panda/master.m3u8"
    assert result["play_url_list"][0] == "https://example.test/panda/720p.m3u8"


@pytest.mark.asyncio
async def test_get_twitchtv_stream_data_returns_normalized_live_shape(monkeypatch):
    async def fake_async_req(url, *args, **kwargs):
        if "gql.twitch.tv" in url:
            return json.dumps(
                {
                    "data": {
                        "streamPlaybackAccessToken": {
                            "value": "token-1",
                            "signature": "sig-1",
                        }
                    }
                }
            )
        raise AssertionError(url)

    async def fake_get_twitchtv_room_info(url, token, proxy_addr=None, cookies=None):
        return "Twitch主播-login", True

    async def fake_get_play_url_list(*args, **kwargs):
        return ["https://example.test/twitch/source.m3u8"]

    monkeypatch.setattr("src.spider.async_req", fake_async_req)
    monkeypatch.setattr("src.spider.get_twitchtv_room_info", fake_get_twitchtv_room_info)
    monkeypatch.setattr("src.spider.get_play_url_list", fake_get_play_url_list)

    result = await get_twitchtv_stream_data("https://www.twitch.tv/tester")

    assert result["anchor_name"] == "Twitch主播-login"
    assert result["is_live"] is True
    assert result["m3u8_url"].startswith("https://usher.ttvnw.net/api/channel/hls/tester.m3u8?")
    assert result["play_url_list"] == ["https://example.test/twitch/source.m3u8"]


@pytest.mark.asyncio
async def test_get_liveme_stream_url_returns_empty_list_on_http_client_error(monkeypatch):
    async def fake_async_req(*args, **kwargs):
        raise HttpConnectError("GET", "https://live.liveme.com/live/queryinfosimple", "connection refused")

    monkeypatch.setattr(
        "src.spider.call_js_file",
        lambda *args, **kwargs: {
            "lm_s_sign": "demo-sign",
            "tongdun_black_box": "demo-box",
            "os": "ios",
            "foo": "bar",
        },
    )
    monkeypatch.setattr("src.spider.async_req", fake_async_req)

    result = await get_liveme_stream_url("https://www.liveme.com/zh/v/17141543493018047815/index.html")

    assert result == []
