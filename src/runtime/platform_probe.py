from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field

from src.models import QualityLevel
from src.platforms import PlatformRegistry, try_resolve

from .models import RoomSpec
from .monitor import ProbeResult


class LegacyPlatformRequired(RuntimeError):
    pass


class PlatformProbeError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class PlatformProbeSettings:
    proxy_addr: str | None = None
    cookies_by_platform: Mapping[str, str | None] = field(default_factory=dict)
    network_available: bool = False


PlatformSettingsProvider = Callable[[RoomSpec], PlatformProbeSettings]

_QUALITY_CODES = {
    QualityLevel.ORIGIN: "OD",
    QualityLevel.BLUE: "BD",
    QualityLevel.UHD: "UHD",
    QualityLevel.HD: "HD",
    QualityLevel.SD: "SD",
    QualityLevel.LD: "LD",
}


class RegisteredPlatformProbe:
    def __init__(
        self,
        registry: PlatformRegistry,
        settings_provider: PlatformSettingsProvider,
    ) -> None:
        self._registry = registry
        self._settings_provider = settings_provider

    async def __call__(self, room: RoomSpec) -> ProbeResult:
        adapter = self._registry.find(room.url)
        if adapter is None:
            raise LegacyPlatformRequired(f"no async adapter for room: {room.url}")

        settings = self._settings_provider(room)
        dispatch = await try_resolve(
            self._registry,
            room.url,
            _QUALITY_CODES[room.quality],
            proxy_addr=settings.proxy_addr,
            cookies_by_platform=settings.cookies_by_platform,
            network_available=settings.network_available,
        )
        if dispatch.error is not None:
            label = dispatch.display_name or dispatch.platform_name or room.url
            raise PlatformProbeError(f"platform probe failed: {label}") from dispatch.error
        if not dispatch.handled:
            raise LegacyPlatformRequired(f"no async adapter handled room: {room.url}")

        payload = dict(dispatch.stream_info or {})
        payload["platform_name"] = dispatch.platform_name
        payload["display_name"] = dispatch.display_name
        return ProbeResult(is_live=bool(payload.get("is_live")), payload=payload)
