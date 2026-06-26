from collections.abc import Mapping
from dataclasses import dataclass

from .base import PlatformContext
from .registry import PlatformRegistry


@dataclass(frozen=True, slots=True)
class DispatchResult:
    handled: bool
    platform_name: str | None = None
    display_name: str | None = None
    stream_info: dict | None = None
    error: Exception | None = None


async def try_resolve(
    registry: PlatformRegistry,
    url: str,
    quality: str,
    *,
    proxy_addr: str | None = None,
    cookies_by_platform: Mapping[str, str | None] | None = None,
    network_available: bool = False,
) -> DispatchResult:
    adapter = registry.find(url)
    if adapter is None:
        return DispatchResult(handled=False)

    cookies = (cookies_by_platform or {}).get(adapter.name)
    context = PlatformContext(
        proxy_addr=proxy_addr,
        cookies=cookies,
        network_available=network_available,
    )
    try:
        info = await adapter.resolve(url, quality, context)
    except Exception as error:
        return DispatchResult(False, adapter.name, adapter.display_name, error=error)
    return DispatchResult(True, adapter.name, adapter.display_name, info)
