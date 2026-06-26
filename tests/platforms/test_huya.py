import pytest

from src.platforms.base import PlatformContext
from src.platforms.huya import HuyaAdapter


def test_huya_matches_canonical_host_only():
    adapter = HuyaAdapter()

    assert adapter.match("https://www.huya.com/1")
    assert not adapter.match("https://m.huya.com/1")


@pytest.mark.parametrize("quality", ["OD", "BD", "UHD"])
async def test_huya_app_qualities_use_app_result_directly(monkeypatch, quality):
    async def fake_app(url, proxy_addr=None, cookies=None):
        assert (url, proxy_addr, cookies) == ("https://www.huya.com/1", "proxy", "cookie")
        return {
            "anchor_name": "huya",
            "is_live": True,
            "flv_url": "https://live.flv",
            "record_url": "https://live.flv",
        }

    async def fake_web(*args, **kwargs):
        raise AssertionError("web probe must not handle app qualities")

    monkeypatch.setattr("src.platforms.huya.spider.get_huya_app_stream_url", fake_app)
    monkeypatch.setattr("src.platforms.huya.spider.get_huya_stream_data", fake_web)

    result = await HuyaAdapter().resolve(
        "https://www.huya.com/1", quality, PlatformContext(proxy_addr="proxy", cookies="cookie")
    )

    assert result["record_url"] == "https://live.flv"


async def test_huya_web_quality_uses_probe_then_selector(monkeypatch):
    async def fake_fetch(url, proxy_addr=None, cookies=None):
        assert (proxy_addr, cookies) == ("proxy", "cookie")
        return {"anchor_name": "huya", "is_live": False}

    async def fake_select(info, quality):
        assert quality == "HD"
        return {"anchor_name": info["anchor_name"], "is_live": False}

    monkeypatch.setattr("src.platforms.huya.spider.get_huya_stream_data", fake_fetch)
    monkeypatch.setattr("src.platforms.huya.stream.get_huya_stream_url", fake_select)

    result = await HuyaAdapter().resolve(
        "https://www.huya.com/1", "HD", PlatformContext(proxy_addr="proxy", cookies="cookie")
    )

    assert result == {"anchor_name": "huya", "is_live": False}
