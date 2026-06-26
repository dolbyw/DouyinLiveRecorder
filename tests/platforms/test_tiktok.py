import pytest

from src.platforms.base import PlatformContext, PlatformUnavailableError
from src.platforms.tiktok import TikTokAdapter


def test_tiktok_matches_canonical_host_only():
    adapter = TikTokAdapter()

    assert adapter.match("https://www.tiktok.com/@name/live")
    assert not adapter.match("https://tiktok.example/@name/live")


async def test_tiktok_rejects_context_without_reachable_network():
    with pytest.raises(PlatformUnavailableError, match="proxy"):
        await TikTokAdapter().resolve("https://www.tiktok.com/@name/live", "HD", PlatformContext())


async def test_tiktok_uses_existing_probe_and_selector(monkeypatch):
    async def fake_fetch(url, proxy_addr=None, cookies=None):
        assert (proxy_addr, cookies) == ("proxy", "cookie")
        return {"anchor_name": "creator", "is_live": False}

    async def fake_select(info, quality, proxy_addr):
        assert proxy_addr == "proxy"
        return {"anchor_name": info["anchor_name"], "is_live": False, "quality": quality}

    monkeypatch.setattr("src.platforms.tiktok.spider.get_tiktok_stream_data", fake_fetch)
    monkeypatch.setattr("src.platforms.tiktok.stream.get_tiktok_stream_url", fake_select)
    context = PlatformContext(proxy_addr="proxy", cookies="cookie", network_available=True)

    result = await TikTokAdapter().resolve("https://www.tiktok.com/@name/live", "HD", context)

    assert result == {"anchor_name": "creator", "is_live": False, "quality": "HD"}
