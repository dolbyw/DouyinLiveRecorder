from .bilibili import BilibiliAdapter
from .dispatch import DispatchResult, try_resolve
from .douyin import DouyinAdapter
from .huya import HuyaAdapter
from .registry import PlatformRegistry
from .tiktok import TikTokAdapter

default_registry = PlatformRegistry(
    [DouyinAdapter(), TikTokAdapter(), BilibiliAdapter(), HuyaAdapter()]
)

__all__ = ["DispatchResult", "PlatformRegistry", "default_registry", "try_resolve"]
