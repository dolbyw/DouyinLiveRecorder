# PR3 平台注册表第一批迁移 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将抖音、TikTok、B站和虎牙迁移到注册表优先的平台适配器路径，并在新路径不可执行或失败时保留现有分发作为 fallback。

**Architecture:** `src/platforms/` 提供协议、上下文、四个薄适配器、有序注册表和可测试的容错分发器。适配器仅编排现有 `spider.py`/`stream.py` 函数并输出统一流信息；`main.py` 在原 `if/elif` 链前调用分发器，成功则短路，失败则自然落入原链。

**Tech Stack:** Python 3.10+、dataclasses、typing.Protocol、pytest、pytest-asyncio、ruff

---

## 文件结构

- `src/platforms/base.py`：适配器协议、调用上下文、公共解析基类和不可执行异常。
- `src/platforms/registry.py`：有序注册、重复保护和 URL 查找。
- `src/platforms/douyin.py`：抖音网页/短链探测与选流。
- `src/platforms/tiktok.py`：TikTok 代理前置条件、探测与选流。
- `src/platforms/bilibili.py`：B站房间探测与选流。
- `src/platforms/huya.py`：虎牙网页质量/App 质量双路径。
- `src/platforms/dispatch.py`：注册表优先解析、异常收敛和 fallback 决策。
- `src/platforms/__init__.py`：默认注册表和公共 API。
- `main.py`：构造平台 Cookie 上下文并在旧分发前接入新入口。
- `tests/platforms/`：基础设施、适配器和容错分发测试。
- `docs/项目优化实施路线图.md`：记录 PR3 第一批迁移完成状态。

> 当前目录没有 `.git` 元数据，以下任务使用测试通过作为检查点，不执行无法完成的 commit 步骤。若恢复仓库元数据，每个任务完成后分别提交对应文件。

### Task 1: 建立适配器契约与有序注册表

**Files:**
- Create: `src/platforms/base.py`
- Create: `src/platforms/registry.py`
- Create: `tests/platforms/test_registry.py`

- [ ] **Step 1: 写失败测试，固定匹配、顺序与重复注册行为**

```python
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
```

- [ ] **Step 2: 运行测试并确认因平台包不存在而失败**

Run: `.\.venv\Scripts\python.exe -m pytest tests/platforms/test_registry.py -q`

Expected: collection FAIL，提示 `No module named 'src.platforms'`。

- [ ] **Step 3: 实现最小契约和注册表**

```python
# src/platforms/base.py
from dataclasses import dataclass
from typing import Protocol

from src.models import normalize_platform_payload, normalize_stream_info


class PlatformUnavailableError(RuntimeError):
    """The adapter matched but cannot safely execute in the current context."""


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
```

```python
# src/platforms/registry.py
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
```

- [ ] **Step 4: 运行聚焦测试并确认通过**

Run: `.\.venv\Scripts\python.exe -m pytest tests/platforms/test_registry.py -q`

Expected: `3 passed`。

### Task 2: 用 TDD 实现抖音与 TikTok 适配器

**Files:**
- Create: `src/platforms/douyin.py`
- Create: `src/platforms/tiktok.py`
- Create: `tests/platforms/test_douyin.py`
- Create: `tests/platforms/test_tiktok.py`

- [ ] **Step 1: 写抖音失败测试，覆盖 host、网页与短链路由**

```python
from src.platforms.base import PlatformContext
from src.platforms.douyin import DouyinAdapter


def test_douyin_matches_supported_hosts_only():
    adapter = DouyinAdapter()
    assert adapter.match("https://live.douyin.com/123")
    assert adapter.match("https://v.douyin.com/abc")
    assert adapter.match("https://www.douyin.com/user/abc")
    assert not adapter.match("https://notdouyin.com/123")


async def test_douyin_routes_room_to_web_probe_and_returns_stream_contract(monkeypatch):
    async def fake_web(url, proxy_addr=None, cookies=None):
        assert (url, proxy_addr, cookies) == ("https://live.douyin.com/1", "proxy", "cookie")
        return {"anchor_name": "主播", "status": 4}

    async def fake_select(info, quality, proxy_addr):
        assert info["anchor_name"] == "主播"
        assert (quality, proxy_addr) == ("HD", "proxy")
        return {"anchor_name": "主播", "is_live": False}

    monkeypatch.setattr("src.platforms.douyin.spider.get_douyin_web_stream_data", fake_web)
    monkeypatch.setattr("src.platforms.douyin.stream.get_douyin_stream_url", fake_select)
    result = await DouyinAdapter().resolve(
        "https://live.douyin.com/1", "HD", PlatformContext(proxy_addr="proxy", cookies="cookie")
    )
    assert result["anchor_name"] == "主播"
    assert result["is_live"] is False
```

再增加一个相同结构的测试，传入 `https://v.douyin.com/abc`，只允许 `get_douyin_app_stream_data()` 被调用。

- [ ] **Step 2: 运行抖音测试并确认因模块缺失而失败**

Run: `.\.venv\Scripts\python.exe -m pytest tests/platforms/test_douyin.py -q`

Expected: collection FAIL，提示无法导入 `DouyinAdapter`。

- [ ] **Step 3: 实现抖音适配器并通过测试**

```python
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
```

Run: `.\.venv\Scripts\python.exe -m pytest tests/platforms/test_douyin.py -q`

Expected: all tests PASS。

- [ ] **Step 4: 写 TikTok 失败测试，覆盖代理约束与正常调用**

```python
import pytest

from src.platforms.base import PlatformContext, PlatformUnavailableError
from src.platforms.tiktok import TikTokAdapter


async def test_tiktok_rejects_context_without_reachable_network():
    with pytest.raises(PlatformUnavailableError, match="proxy"):
        await TikTokAdapter().resolve("https://www.tiktok.com/@name/live", "HD", PlatformContext())


async def test_tiktok_uses_existing_probe_and_selector(monkeypatch):
    async def fake_fetch(url, proxy_addr=None, cookies=None):
        return {"anchor_name": "creator", "is_live": False}

    async def fake_select(info, quality, proxy_addr):
        return {"anchor_name": info["anchor_name"], "is_live": False, "quality": quality}

    monkeypatch.setattr("src.platforms.tiktok.spider.get_tiktok_stream_data", fake_fetch)
    monkeypatch.setattr("src.platforms.tiktok.stream.get_tiktok_stream_url", fake_select)
    context = PlatformContext(proxy_addr="proxy", cookies="cookie", network_available=True)
    result = await TikTokAdapter().resolve("https://www.tiktok.com/@name/live", "HD", context)
    assert result == {"anchor_name": "creator", "is_live": False, "quality": "HD"}
```

- [ ] **Step 5: 运行 RED、实现 TikTok 适配器、再运行 GREEN**

Run: `.\.venv\Scripts\python.exe -m pytest tests/platforms/test_tiktok.py -q`

Expected before implementation: collection FAIL。

```python
from urllib.parse import urlparse

from src import spider, stream

from .base import BasePlatformAdapter, PlatformContext, PlatformUnavailableError


class TikTokAdapter(BasePlatformAdapter):
    name = "tiktok"
    display_name = "TikTok直播"

    def match(self, url: str) -> bool:
        return urlparse(url).hostname == "www.tiktok.com"

    async def fetch(self, url: str, context: PlatformContext) -> dict:
        if not context.network_available and not context.proxy_addr:
            raise PlatformUnavailableError("TikTok requires a reachable proxy network")
        return await spider.get_tiktok_stream_data(url, context.proxy_addr, context.cookies)

    async def select_stream(self, info: dict, quality: str, context: PlatformContext) -> dict:
        return await stream.get_tiktok_stream_url(info, quality, context.proxy_addr)
```

Run: `.\.venv\Scripts\python.exe -m pytest tests/platforms/test_tiktok.py -q`

Expected after implementation: all tests PASS。

### Task 3: 用 TDD 实现 B站与虎牙适配器

**Files:**
- Create: `src/platforms/bilibili.py`
- Create: `src/platforms/huya.py`
- Create: `tests/platforms/test_bilibili.py`
- Create: `tests/platforms/test_huya.py`

- [ ] **Step 1: 写 B站失败测试并确认 RED**

```python
from src.platforms.base import PlatformContext
from src.platforms.bilibili import BilibiliAdapter


async def test_bilibili_propagates_url_quality_proxy_and_cookie(monkeypatch):
    async def fake_fetch(url, proxy_addr=None, cookies=None):
        assert (proxy_addr, cookies) == ("proxy", "cookie")
        return {"anchor_name": "up", "live_status": False, "room_url": url}

    async def fake_select(info, video_quality, proxy_addr, cookies):
        assert (video_quality, proxy_addr, cookies) == ("UHD", "proxy", "cookie")
        return {"anchor_name": info["anchor_name"], "is_live": False}

    monkeypatch.setattr("src.platforms.bilibili.spider.get_bilibili_room_info", fake_fetch)
    monkeypatch.setattr("src.platforms.bilibili.stream.get_bilibili_stream_url", fake_select)
    result = await BilibiliAdapter().resolve(
        "https://live.bilibili.com/1", "UHD", PlatformContext(proxy_addr="proxy", cookies="cookie")
    )
    assert result["anchor_name"] == "up"
    assert result["is_live"] is False
```

Run: `.\.venv\Scripts\python.exe -m pytest tests/platforms/test_bilibili.py -q`

Expected: collection FAIL。

- [ ] **Step 2: 实现 B站适配器并确认 GREEN**

```python
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
```

Run: `.\.venv\Scripts\python.exe -m pytest tests/platforms/test_bilibili.py -q`

Expected: all tests PASS。

- [ ] **Step 3: 写虎牙失败测试，分别固定 App 和网页路径**

```python
import pytest

from src.platforms.base import PlatformContext
from src.platforms.huya import HuyaAdapter


@pytest.mark.parametrize("quality", ["OD", "BD", "UHD"])
async def test_huya_app_qualities_use_app_result_directly(monkeypatch, quality):
    async def fake_app(url, proxy_addr=None, cookies=None):
        return {
            "anchor_name": "huya",
            "is_live": True,
            "flv_url": "https://live.flv",
            "record_url": "https://live.flv",
        }

    monkeypatch.setattr("src.platforms.huya.spider.get_huya_app_stream_url", fake_app)
    result = await HuyaAdapter().resolve(
        "https://www.huya.com/1", quality, PlatformContext(proxy_addr="proxy", cookies="cookie")
    )
    assert result["record_url"] == "https://live.flv"


async def test_huya_web_quality_uses_probe_then_selector(monkeypatch):
    async def fake_fetch(url, proxy_addr=None, cookies=None):
        return {"anchor_name": "huya", "is_live": False}

    async def fake_select(info, quality):
        assert quality == "HD"
        return {"anchor_name": "huya", "is_live": False}

    monkeypatch.setattr("src.platforms.huya.spider.get_huya_stream_data", fake_fetch)
    monkeypatch.setattr("src.platforms.huya.stream.get_huya_stream_url", fake_select)
    result = await HuyaAdapter().resolve("https://www.huya.com/1", "HD", PlatformContext())
    assert result["is_live"] is False
```

Run: `.\.venv\Scripts\python.exe -m pytest tests/platforms/test_huya.py -q`

Expected: collection FAIL。

- [ ] **Step 4: 实现虎牙适配器并确认 GREEN**

```python
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
```

Run: `.\.venv\Scripts\python.exe -m pytest tests/platforms/test_huya.py -q`

Expected: all tests PASS。

### Task 4: 建立默认注册表和容错分发器

**Files:**
- Create: `src/platforms/dispatch.py`
- Create: `src/platforms/__init__.py`
- Create: `tests/platforms/test_dispatch.py`
- Modify: `tests/platforms/test_registry.py`

- [ ] **Step 1: 写失败测试，固定默认注册和三种分发结果**

```python
from src.platforms import default_registry
from src.platforms.base import BasePlatformAdapter, PlatformContext
from src.platforms.dispatch import try_resolve
from src.platforms.registry import PlatformRegistry


def test_default_registry_contains_the_four_first_batch_adapters():
    assert default_registry.find("https://live.douyin.com/1").name == "douyin"
    assert default_registry.find("https://www.tiktok.com/@a/live").name == "tiktok"
    assert default_registry.find("https://live.bilibili.com/1").name == "bilibili"
    assert default_registry.find("https://www.huya.com/1").name == "huya"


async def test_unknown_url_is_not_handled():
    result = await try_resolve(PlatformRegistry(), "https://other.test/1", "HD")
    assert result.handled is False
    assert result.stream_info is None


async def test_offline_result_is_handled_without_fallback():
    class OfflineAdapter(BasePlatformAdapter):
        name = "offline"
        display_name = "离线平台"
        def match(self, url): return True
        async def fetch(self, url, context): return {"anchor_name": "a", "is_live": False}
        async def select_stream(self, info, quality, context): return info

    result = await try_resolve(PlatformRegistry([OfflineAdapter()]), "https://offline.test", "HD")
    assert result.handled is True
    assert result.stream_info["is_live"] is False


async def test_adapter_exception_requests_fallback():
    class BrokenAdapter(BasePlatformAdapter):
        name = "broken"
        display_name = "故障平台"
        def match(self, url): return True
        async def fetch(self, url, context): raise RuntimeError("boom")
        async def select_stream(self, info, quality, context): return info

    result = await try_resolve(PlatformRegistry([BrokenAdapter()]), "https://broken.test", "HD")
    assert result.handled is False
    assert isinstance(result.error, RuntimeError)
```

- [ ] **Step 2: 运行测试并确认 RED**

Run: `.\.venv\Scripts\python.exe -m pytest tests/platforms/test_dispatch.py -q`

Expected: collection FAIL，提示 `dispatch` 或 `default_registry` 缺失。

- [ ] **Step 3: 实现容错分发器与默认注册表**

```python
# src/platforms/dispatch.py
from dataclasses import dataclass
from collections.abc import Mapping

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
    context = PlatformContext(proxy_addr=proxy_addr, cookies=cookies, network_available=network_available)
    try:
        info = await adapter.resolve(url, quality, context)
    except Exception as error:
        return DispatchResult(False, adapter.name, adapter.display_name, error=error)
    return DispatchResult(True, adapter.name, adapter.display_name, info)
```

```python
# src/platforms/__init__.py
from .bilibili import BilibiliAdapter
from .dispatch import DispatchResult, try_resolve
from .douyin import DouyinAdapter
from .huya import HuyaAdapter
from .registry import PlatformRegistry
from .tiktok import TikTokAdapter

default_registry = PlatformRegistry([DouyinAdapter(), TikTokAdapter(), BilibiliAdapter(), HuyaAdapter()])

__all__ = ["DispatchResult", "PlatformRegistry", "default_registry", "try_resolve"]
```

- [ ] **Step 4: 运行平台测试并确认通过**

Run: `.\.venv\Scripts\python.exe -m pytest tests/platforms -q`

Expected: all tests PASS。

### Task 5: 在 main.py 接入注册表优先路径

**Files:**
- Modify: `main.py`
- Create: `tests/platforms/test_main_wiring.py`

- [ ] **Step 1: 写静态接线失败测试，避免导入具有启动副作用的 main.py**

```python
from pathlib import Path


def test_main_uses_registry_before_legacy_douyin_branch():
    source = Path("main.py").read_text(encoding="utf-8")
    registry_call = source.index("try_resolve(")
    legacy_branch = source.index('record_url.find("douyin.com/")')
    assert registry_call < legacy_branch
    assert "if dispatch_result.handled:" in source
    assert "elif record_url.find(\"douyin.com/\")" in source
```

- [ ] **Step 2: 运行测试并确认因接线不存在而失败**

Run: `.\.venv\Scripts\python.exe -m pytest tests/platforms/test_main_wiring.py -q`

Expected: FAIL，提示找不到 `try_resolve(`。

- [ ] **Step 3: 添加导入和注册表优先调用**

在 `main.py` 导入区增加：

```python
from src.platforms import default_registry, try_resolve
```

在 `port_info = []` 后、旧抖音分支前增加：

```python
cookies_by_platform = {
    "douyin": dy_cookie,
    "tiktok": tiktok_cookie,
    "bilibili": bili_cookie,
    "huya": hy_cookie,
}
with semaphore:
    dispatch_result = run_async(
        try_resolve(
            default_registry,
            record_url,
            record_quality,
            proxy_addr=proxy_address,
            cookies_by_platform=cookies_by_platform,
            network_available=bool(global_proxy or proxy_address),
        )
    )

if dispatch_result.error is not None:
    logger.warning(
        f"平台注册表路径失败，将回退旧分发: {dispatch_result.display_name} | "
        f"{record_url} | {dispatch_result.error}"
    )

if dispatch_result.handled:
    platform = dispatch_result.display_name or "未知平台"
    port_info = dispatch_result.stream_info or {}
```

将紧随其后的旧抖音 `if` 改成 `elif`，使已处理结果短路、失败或未命中结果进入原完整 `if/elif` 链。不要删除四个平台旧分支。

- [ ] **Step 4: 运行接线测试、语法编译和平台测试**

Run: `.\.venv\Scripts\python.exe -m pytest tests/platforms -q`

Expected: all tests PASS。

Run: `.\.venv\Scripts\python.exe -m py_compile main.py src/platforms/*.py`

Expected: exit code 0，无输出。

### Task 6: 更新路线图并执行完整回归

**Files:**
- Modify: `docs/项目优化实施路线图.md`

- [ ] **Step 1: 更新 PR3 当前进展与验收状态**

在 PR3 小节加入明确结果：四个第一批平台已注册；新入口正常结果会短路旧逻辑；异常、前置条件不足或未命中会 fallback；旧分支暂不删除，待运行验证期后另行清理。阶段三验收仍保留“主分发明显缩短”的后续观察项，避免把代码存在误写成生产验证完成。

- [ ] **Step 2: 运行完整测试**

Run: `.\.venv\Scripts\python.exe -m pytest -q`

Expected: all tests PASS，且无 collection error 或 warning。

- [ ] **Step 3: 运行 Ruff**

Run: `.\.venv\Scripts\python.exe -m ruff check main.py src tests`

Expected: `All checks passed!`。

- [ ] **Step 4: 检查本次改动范围**

Run: `Get-ChildItem src\platforms,tests\platforms -Recurse | Select-Object FullName`

Expected: 仅出现本计划列出的平台注册表、适配器、分发器和测试文件；现有 `spider.py`、`stream.py` 无行为性重写。
