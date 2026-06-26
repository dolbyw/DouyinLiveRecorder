from urllib.parse import urlparse

from src import spider, stream

from .base import BasePlatformAdapter, PlatformContext


class BilibiliAdapter(BasePlatformAdapter):
    name = "bilibili"
    display_name = "B站直播"

    def match(self, url: str) -> bool:
        return urlparse(url).hostname == "live.bilibili.com"

    async def fetch(self, url: str, context: PlatformContext) -> dict:
        return await spider.get_bilibili_room_info(url, context.proxy_addr, context.cookies)

    async def select_stream(self, info: dict, quality: str, context: PlatformContext) -> dict:
        return await stream.get_bilibili_stream_url(info, quality, context.proxy_addr, context.cookies)
