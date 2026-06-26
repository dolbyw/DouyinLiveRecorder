import pytest

from src.platforms.base import PlatformContext
from src.platforms.registry import PlatformRegistry


class StubAdapter:
    def __init__(self, name: str, needle: str):
        self.name = name
        self.display_name = name
        self.needle = needle

    def match(self, url: str) -> bool:
        return self.needle in url


def test_registry_returns_first_matching_adapter_and_none_for_unknown_url():
    first = StubAdapter("first", "example.com")
    second = StubAdapter("second", "example.com")
    registry = PlatformRegistry([first, second])

    assert registry.find("https://example.com/live") is first
    assert registry.find("https://other.test/live") is None


def test_registry_rejects_duplicate_adapter_name():
    registry = PlatformRegistry([StubAdapter("same", "one.test")])

    with pytest.raises(ValueError, match="same"):
        registry.register(StubAdapter("same", "two.test"))


def test_platform_context_defaults_are_safe():
    assert PlatformContext().proxy_addr is None
    assert PlatformContext().cookies is None
    assert PlatformContext().network_available is False
