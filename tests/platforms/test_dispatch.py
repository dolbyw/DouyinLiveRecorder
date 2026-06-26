from src.platforms import default_registry
from src.platforms.base import BasePlatformAdapter
from src.platforms.dispatch import try_resolve
from src.platforms.registry import PlatformRegistry


def test_default_registry_contains_the_four_first_batch_adapters():
    assert default_registry.find("https://live.douyin.com/1").name == "douyin"
    assert default_registry.find("https://www.tiktok.com/@a/live").name == "tiktok"
    assert default_registry.find("https://live.bilibili.com/1").name == "bilibili"
    assert default_registry.find("https://www.huya.com/1").name == "huya"


async def test_unknown_url_is_not_handled():
    result = await try_resolve(PlatformRegistry(), "https://other.test/1", "HD")

    assert result.handled is False
    assert result.stream_info is None
    assert result.error is None


async def test_offline_result_is_handled_without_fallback():
    class OfflineAdapter(BasePlatformAdapter):
        name = "offline"
        display_name = "离线平台"

        def match(self, url):
            return True

        async def fetch(self, url, context):
            return {"anchor_name": "a", "is_live": False}

        async def select_stream(self, info, quality, context):
            return info

    result = await try_resolve(PlatformRegistry([OfflineAdapter()]), "https://offline.test", "HD")

    assert result.handled is True
    assert result.stream_info["is_live"] is False


async def test_adapter_exception_requests_fallback():
    class BrokenAdapter(BasePlatformAdapter):
        name = "broken"
        display_name = "故障平台"

        def match(self, url):
            return True

        async def fetch(self, url, context):
            raise RuntimeError("boom")

        async def select_stream(self, info, quality, context):
            return info

    result = await try_resolve(PlatformRegistry([BrokenAdapter()]), "https://broken.test", "HD")

    assert result.handled is False
    assert result.platform_name == "broken"
    assert result.display_name == "故障平台"
    assert isinstance(result.error, RuntimeError)


async def test_dispatch_builds_platform_specific_context():
    class ContextAdapter(BasePlatformAdapter):
        name = "context"
        display_name = "上下文平台"

        def match(self, url):
            return True

        async def fetch(self, url, context):
            assert context.proxy_addr == "proxy"
            assert context.cookies == "cookie"
            assert context.network_available is True
            return {"anchor_name": "a", "is_live": False}

        async def select_stream(self, info, quality, context):
            return info

    result = await try_resolve(
        PlatformRegistry([ContextAdapter()]),
        "https://context.test",
        "HD",
        proxy_addr="proxy",
        cookies_by_platform={"context": "cookie"},
        network_available=True,
    )

    assert result.handled is True
