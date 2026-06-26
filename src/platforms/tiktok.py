from urllib.parse import urlparse

from src import spider, stream

from .base import BasePlatformAdapter, PlatformContext, PlatformUnavailableError


class TikTokAdapter(BasePlatformAdapter):
    name = "tiktok"
    display_name = "TikTok直播"

    def match(self, url: str) -> bool:
        return urlparse(url).hostname == "www.tiktok.com"

    async def fetch(self, url: str, context: PlatformContext) -> dict:
        if not context.network_available and not context.proxy_addr:
            raise PlatformUnavailableError("TikTok requires a reachable proxy network")
        return await spider.get_tiktok_stream_data(url, context.proxy_addr, context.cookies)

    async def select_stream(self, info: dict, quality: str, context: PlatformContext) -> dict:
        return await stream.get_tiktok_stream_url(info, quality, context.proxy_addr)
