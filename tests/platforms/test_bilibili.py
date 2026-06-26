from src.platforms.base import PlatformContext
from src.platforms.bilibili import BilibiliAdapter


def test_bilibili_matches_live_host_only():
    adapter = BilibiliAdapter()

    assert adapter.match("https://live.bilibili.com/1")
    assert not adapter.match("https://www.bilibili.com/video/1")


async def test_bilibili_propagates_url_quality_proxy_and_cookie(monkeypatch):
    async def fake_fetch(url, proxy_addr=None, cookies=None):
        assert (url, proxy_addr, cookies) == ("https://live.bilibili.com/1", "proxy", "cookie")
        return {"anchor_name": "up", "live_status": False, "room_url": url}

    async def fake_select(info, video_quality, proxy_addr, cookies):
        assert info["room_url"] == "https://live.bilibili.com/1"
        assert (video_quality, proxy_addr, cookies) == ("UHD", "proxy", "cookie")
        return {"anchor_name": info["anchor_name"], "is_live": False}

    monkeypatch.setattr("src.platforms.bilibili.spider.get_bilibili_room_info", fake_fetch)
    monkeypatch.setattr("src.platforms.bilibili.stream.get_bilibili_stream_url", fake_select)

    result = await BilibiliAdapter().resolve(
        "https://live.bilibili.com/1", "UHD", PlatformContext(proxy_addr="proxy", cookies="cookie")
    )

    assert result == {"anchor_name": "up", "is_live": False}
