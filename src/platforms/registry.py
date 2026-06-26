from collections.abc import Iterable

from .base import PlatformAdapter


class PlatformRegistry:
    def __init__(self, adapters: Iterable[PlatformAdapter] = ()) -> None:
        self._adapters: list[PlatformAdapter] = []
        for adapter in adapters:
            self.register(adapter)

    def register(self, adapter: PlatformAdapter) -> None:
        if any(item.name == adapter.name for item in self._adapters):
            raise ValueError(f"platform adapter already registered: {adapter.name}")
        self._adapters.append(adapter)

    def find(self, url: str) -> PlatformAdapter | None:
        return next((adapter for adapter in self._adapters if adapter.match(url)), None)
