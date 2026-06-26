from urllib.parse import urlparse

from src import spider, stream

from .base import BasePlatformAdapter, PlatformContext


class DouyinAdapter(BasePlatformAdapter):
    name = "douyin"
    display_name = "抖音直播"
    hosts = {"live.douyin.com", "v.douyin.com", "www.douyin.com"}

    def match(self, url: str) -> bool:
        return urlparse(url).hostname in self.hosts

    async def fetch(self, url: str, context: PlatformContext) -> dict:
        if "v.douyin.com" not in url and "/user/" not in url:
            return await spider.get_douyin_web_stream_data(url, context.proxy_addr, context.cookies)
        return await spider.get_douyin_app_stream_data(url, context.proxy_addr, context.cookies)

    async def select_stream(self, info: dict, quality: str, context: PlatformContext) -> dict:
        return await stream.get_douyin_stream_url(info, quality, context.proxy_addr)
