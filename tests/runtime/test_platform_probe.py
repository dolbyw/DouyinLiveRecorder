import pytest

from src.models import QualityLevel
from src.platforms import PlatformRegistry
from src.runtime import (
    LegacyPlatformRequired,
    PlatformProbeError,
    PlatformProbeSettings,
    RegisteredPlatformProbe,
    RoomSpec,
)


class FakeAdapter:
    name = "fake"
    display_name = "Fake Live"

    def __init__(self, result=None, error: Exception | None = None) -> None:
        self.result = result or {"is_live": False}
        self.error = error
        self.quality = None
        self.context = None

    def match(self, url: str) -> bool:
        return "fake.example" in url

    async def resolve(self, _url, quality, context):
        self.quality = quality
        self.context = context
        if self.error:
            raise self.error
        return self.result


@pytest.mark.asyncio
async def test_registered_probe_converts_quality_and_context_to_probe_result():
    adapter = FakeAdapter({"is_live": True, "record_url": "https://stream.example/live.flv"})
    registry = PlatformRegistry([adapter])
    settings = PlatformProbeSettings(
        proxy_addr="http://127.0.0.1:7890",
        cookies_by_platform={"fake": "cookie=value"},
        network_available=True,
    )
    probe = RegisteredPlatformProbe(registry, lambda _room: settings)
    room = RoomSpec("https://fake.example/1", QualityLevel.HD)

    result = await probe(room)

    assert adapter.quality == "HD"
    assert adapter.context.proxy_addr == settings.proxy_addr
    assert adapter.context.cookies == "cookie=value"
    assert adapter.context.network_available is True
    assert result.is_live is True
    assert result.payload["record_url"] == "https://stream.example/live.flv"
    assert result.payload["platform_name"] == "fake"
    assert result.payload["display_name"] == "Fake Live"


@pytest.mark.asyncio
async def test_unmatched_url_requires_legacy_platform_path():
    probe = RegisteredPlatformProbe(PlatformRegistry(), lambda _room: PlatformProbeSettings())

    with pytest.raises(LegacyPlatformRequired, match="no async adapter"):
        await probe(RoomSpec("https://legacy.example/1", QualityLevel.ORIGIN))


@pytest.mark.asyncio
async def test_adapter_failure_is_preserved_as_platform_probe_error():
    adapter = FakeAdapter(error=RuntimeError("network failed"))
    probe = RegisteredPlatformProbe(PlatformRegistry([adapter]), lambda _room: PlatformProbeSettings())

    with pytest.raises(PlatformProbeError, match="Fake Live") as captured:
        await probe(RoomSpec("https://fake.example/1", QualityLevel.ORIGIN))

    assert isinstance(captured.value.__cause__, RuntimeError)
