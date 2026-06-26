from dataclasses import dataclass
from typing import Protocol

from src.models import normalize_platform_payload, normalize_stream_info


class PlatformUnavailableError(RuntimeError):
    """The matched adapter cannot execute in the current context."""


@dataclass(frozen=True, slots=True)
class PlatformContext:
    proxy_addr: str | None = None
    cookies: str | None = None
    network_available: bool = False


class PlatformAdapter(Protocol):
    name: str
    display_name: str

    def match(self, url: str) -> bool: ...

    async def fetch(self, url: str, context: PlatformContext) -> dict: ...

    def normalize(self, raw_data: dict | None) -> dict: ...

    async def select_stream(self, info: dict, quality: str, context: PlatformContext) -> dict: ...

    async def resolve(self, url: str, quality: str, context: PlatformContext) -> dict: ...


class BasePlatformAdapter:
    def normalize(self, raw_data: dict | None) -> dict:
        return normalize_platform_payload(raw_data)

    async def resolve(self, url: str, quality: str, context: PlatformContext) -> dict:
        raw_data = await self.fetch(url, context)
        info = self.normalize(raw_data)
        result = await self.select_stream(info, quality, context)
        return normalize_stream_info(result)
