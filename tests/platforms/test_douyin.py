from src.platforms.base import PlatformContext
from src.platforms.douyin import DouyinAdapter


def test_douyin_matches_supported_hosts_only():
    adapter = DouyinAdapter()

    assert adapter.match("https://live.douyin.com/123")
    assert adapter.match("https://v.douyin.com/abc")
    assert adapter.match("https://www.douyin.com/user/abc")
    assert not adapter.match("https://notdouyin.com/123")


async def test_douyin_routes_room_to_web_probe_and_returns_stream_contract(monkeypatch):
    async def fake_web(url, proxy_addr=None, cookies=None):
        assert (url, proxy_addr, cookies) == ("https://live.douyin.com/1", "proxy", "cookie")
        return {"anchor_name": "主播", "status": 4}

    async def fake_select(info, quality, proxy_addr):
        assert info["anchor_name"] == "主播"
        assert (quality, proxy_addr) == ("HD", "proxy")
        return {"anchor_name": "主播", "is_live": False}

    monkeypatch.setattr("src.platforms.douyin.spider.get_douyin_web_stream_data", fake_web)
    monkeypatch.setattr("src.platforms.douyin.stream.get_douyin_stream_url", fake_select)

    result = await DouyinAdapter().resolve(
        "https://live.douyin.com/1", "HD", PlatformContext(proxy_addr="proxy", cookies="cookie")
    )

    assert result == {"anchor_name": "主播", "is_live": False}


async def test_douyin_routes_short_link_to_app_probe(monkeypatch):
    async def fake_app(url, proxy_addr=None, cookies=None):
        assert url == "https://v.douyin.com/abc"
        return {"anchor_name": "主播", "status": 4}

    async def fake_web(*args, **kwargs):
        raise AssertionError("web probe must not handle a short link")

    async def fake_select(info, quality, proxy_addr):
        return {"anchor_name": info["anchor_name"], "is_live": False}

    monkeypatch.setattr("src.platforms.douyin.spider.get_douyin_app_stream_data", fake_app)
    monkeypatch.setattr("src.platforms.douyin.spider.get_douyin_web_stream_data", fake_web)
    monkeypatch.setattr("src.platforms.douyin.stream.get_douyin_stream_url", fake_select)

    result = await DouyinAdapter().resolve("https://v.douyin.com/abc", "HD", PlatformContext())

    assert result["is_live"] is False
