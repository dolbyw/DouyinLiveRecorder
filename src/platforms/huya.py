from urllib.parse import urlparse

from src import spider, stream
from src.models import normalize_stream_info

from .base import BasePlatformAdapter, PlatformContext


class HuyaAdapter(BasePlatformAdapter):
    name = "huya"
    display_name = "虎牙直播"
    app_qualities = {"OD", "BD", "UHD"}

    def match(self, url: str) -> bool:
        return urlparse(url).hostname == "www.huya.com"

    async def fetch(self, url: str, context: PlatformContext) -> dict:
        return await spider.get_huya_stream_data(url, context.proxy_addr, context.cookies)

    async def select_stream(self, info: dict, quality: str, context: PlatformContext) -> dict:
        return await stream.get_huya_stream_url(info, quality)

    async def resolve(self, url: str, quality: str, context: PlatformContext) -> dict:
        if quality in self.app_qualities:
            result = await spider.get_huya_app_stream_url(url, context.proxy_addr, context.cookies)
            return normalize_stream_info(result)
        return await super().resolve(url, quality, context)
