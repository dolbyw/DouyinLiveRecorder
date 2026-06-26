# 阶段一请求层与工程基线 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在保持现有平台调用兼容的前提下，建立可复用、默认安全、可诊断且可关闭的 HTTP 请求层，并补齐依赖锁和基础质量门禁。

**Architecture:** `client_pool.py` 只负责按事件循环和请求用途管理客户端生命周期，`errors.py` 只负责异常分类，`async_http.py` 与 `sync_http.py` 负责兼容旧调用契约。测试使用本地 mock transport，不依赖公网；默认 TLS 校验开启，历史例外必须在调用点显式声明。

**Tech Stack:** Python 3.10+、httpx、requests、pytest、ruff、uv

---

## 文件结构

- `src/http_clients/client_pool.py`：异步客户端与同步 Session 的池键、创建、复用和幂等关闭。
- `src/http_clients/errors.py`：稳定的错误类别、请求上下文和底层异常映射。
- `src/http_clients/async_http.py`：异步请求执行内核及旧 API 兼容层。
- `src/http_clients/sync_http.py`：基于复用 Session 的同步兼容层。
- `src/http_clients/__init__.py`：公开关闭接口。
- `src/http_clients/runner.py`：在每个临时事件循环退出前关闭该循环拥有的客户端。
- `tests/http_clients/`：请求池、错误映射及同步/异步兼容行为测试。
- `pyproject.toml`、`uv.lock`：质量工具配置与可复现依赖。

### Task 1: 建立测试环境与客户端用途模型

**Files:**
- Create: `tests/http_clients/test_client_pool.py`
- Modify: `src/http_clients/client_pool.py`

- [ ] **Step 1: 写失败测试，固定用途隔离和同循环复用行为**

```python
import asyncio

from src.http_clients.client_pool import ClientPurpose, close_async_clients, get_async_client


def test_async_client_is_reused_only_for_same_purpose_and_loop():
    async def scenario():
        direct_1 = get_async_client(purpose=ClientPurpose.DIRECT)
        direct_2 = get_async_client(purpose=ClientPurpose.DIRECT)
        abroad = get_async_client(purpose=ClientPurpose.ABROAD)
        assert direct_1 is direct_2
        assert direct_1 is not abroad
        await close_async_clients()

    asyncio.run(scenario())
```

- [ ] **Step 2: 运行测试并确认因 `ClientPurpose` 缺失而失败**

Run: `& '<bundled-python>' -m pytest tests/http_clients/test_client_pool.py -q`

Expected: collection FAIL，提示无法导入 `ClientPurpose`。

- [ ] **Step 3: 最小实现按事件循环和用途建立池键**

```python
class ClientPurpose(str, Enum):
    DIRECT = "direct"
    PROXY = "proxy"
    ABROAD = "abroad"


def _async_key(purpose, proxy_addr, verify, http2):
    return (id(asyncio.get_running_loop()), purpose, proxy_addr, verify, http2)
```

将 `get_async_client()` 增加 `purpose: ClientPurpose = ClientPurpose.DIRECT`，并使用上述键保存客户端；实现 `async def close_async_clients()`，先在锁内清空池，再逐一 `await client.aclose()`。

- [ ] **Step 4: 运行测试并确认通过**

Run: `& '<bundled-python>' -m pytest tests/http_clients/test_client_pool.py -q`

Expected: `1 passed`。

- [ ] **Step 5: 增加同步复用与两类关闭幂等测试并完成实现**

测试相同键复用、不同 purpose 隔离、连续两次关闭不抛错、关闭后重新获取得到新实例。同步池键固定为 `(purpose, proxy_addr, trust_env)`；异步关闭只关闭当前池中的所有客户端。

- [ ] **Step 6: 提交检查点**

当前目录无 `.git`，执行 `git rev-parse --show-toplevel` 并记录预期的 “not a git repository”；不得擅自初始化仓库。若执行环境后来提供 Git 元数据，则提交信息使用 `refactor: add lifecycle-aware http client pool`。

### Task 2: 建立分类错误模型

**Files:**
- Create: `tests/http_clients/test_errors.py`
- Modify: `src/http_clients/errors.py`

- [ ] **Step 1: 写失败参数化测试**

```python
import httpx
import pytest

from src.http_clients.errors import (
    HttpConnectError,
    HttpProxyError,
    HttpTimeoutError,
    wrap_httpx_error,
)


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        (httpx.ConnectError("refused"), HttpConnectError),
        (httpx.ProxyError("bad proxy"), HttpProxyError),
        (httpx.ReadTimeout("slow"), HttpTimeoutError),
    ],
)
def test_httpx_errors_are_classified_and_keep_cause(source, expected):
    error = wrap_httpx_error("GET", "https://example.test", source)
    assert isinstance(error, expected)
    assert error.cause is source
    assert "example.test" in str(error)
```

- [ ] **Step 2: 运行并确认因分类异常类缺失而失败**

Run: `& '<bundled-python>' -m pytest tests/http_clients/test_errors.py -q`

Expected: collection FAIL，提示无法导入分类异常。

- [ ] **Step 3: 实现异常层级和稳定类别字段**

```python
class HttpClientError(Exception):
    category = "request"


class HttpConnectError(HttpClientError):
    category = "connect"


class HttpTimeoutError(HttpClientError):
    category = "timeout"


class HttpProxyError(HttpClientError):
    category = "proxy"
```

同时增加 `HttpStatusError`、`HttpDecodeError`、`HttpJsonError`、`HttpRequestConfigError`，保留 `method`、`url`、`detail`、`cause`，并让 `wrap_httpx_error()` 按最具体类型映射。

- [ ] **Step 4: 增加状态码、解码、JSON、无效 URL 和敏感头不泄露测试**

异常字符串只包含方法、URL、类别和底层消息；API 不接收或保存请求 headers，因此 Cookie 与 Authorization 不会进入异常文本。

- [ ] **Step 5: 运行完整错误测试**

Run: `& '<bundled-python>' -m pytest tests/http_clients/test_errors.py -q`

Expected: 全部 PASS。

### Task 3: 改造异步请求兼容层并默认启用 TLS

**Files:**
- Create: `tests/http_clients/test_async_http.py`
- Modify: `src/http_clients/async_http.py`
- Modify: `src/http_clients/client_pool.py`

- [ ] **Step 1: 写失败测试，固定默认 TLS 与用途传递**

```python
from unittest.mock import AsyncMock, patch

import pytest

from src.http_clients.async_http import async_fetch_response
from src.http_clients.client_pool import ClientPurpose


@pytest.mark.asyncio
async def test_async_fetch_uses_verified_direct_client_by_default():
    response = object()
    client = AsyncMock()
    client.request.return_value = response
    with patch("src.http_clients.async_http.get_async_client", return_value=client) as factory:
        assert await async_fetch_response("GET", "https://example.test") is response
    factory.assert_called_once_with(
        purpose=ClientPurpose.DIRECT, proxy_addr=None, verify=True, http2=True
    )
```

- [ ] **Step 2: 运行并确认当前默认 `verify=False` 导致断言失败**

Run: `& '<bundled-python>' -m pytest tests/http_clients/test_async_http.py -q`

Expected: FAIL，实际调用包含 `verify=False` 或缺少 `purpose`。

- [ ] **Step 3: 最小修改公共入口默认值和用途选择**

`async_fetch_response()`、`async_req()`、`get_response_status()` 的 `verify` 默认改为 `True`；有代理时选择 `PROXY`，`abroad=True` 时优先选择 `ABROAD`，否则选择 `DIRECT`。把 `abroad` 从兼容入口传入执行内核。

- [ ] **Step 4: 增加响应形态和异常兼容测试**

覆盖文本、重定向 URL、Cookie 字典、文本与 Cookie 元组、底层分类异常转为带类别与根因的兼容字符串。`async_fetch_response()` 保持抛出分类异常。

- [ ] **Step 5: 增加可选状态检查测试**

`async_fetch_response()` 增加 `raise_for_status: bool = False`；为 `True` 时调用 `response.raise_for_status()` 并映射为 `HttpStatusError`，默认不调用以保留依赖 4xx 正文的平台行为。

- [ ] **Step 6: 运行异步请求测试**

Run: `& '<bundled-python>' -m pytest tests/http_clients/test_async_http.py -q`

Expected: 全部 PASS。

### Task 4: 统一同步请求到可复用 Session

**Files:**
- Create: `tests/http_clients/test_sync_http.py`
- Modify: `src/http_clients/sync_http.py`

- [ ] **Step 1: 写失败测试，证明无代理请求也使用池化 Session**

```python
from unittest.mock import Mock, patch

from src.http_clients.sync_http import sync_req


def test_sync_get_uses_pooled_session_without_proxy():
    response = Mock(text="ok", url="https://example.test")
    response.raise_for_status.return_value = None
    session = Mock()
    session.get.return_value = response
    with patch("src.http_clients.sync_http.get_sync_session", return_value=session) as factory:
        assert sync_req("https://example.test") == "ok"
    factory.assert_called_once()
    session.get.assert_called_once()
```

- [ ] **Step 2: 运行并确认当前无代理分支走 `urllib`，测试失败**

Run: `& '<bundled-python>' -m pytest tests/http_clients/test_sync_http.py -q`

Expected: FAIL，`get_sync_session` 未调用。

- [ ] **Step 3: 用 Session 统一 GET/POST/JSON 请求**

根据 `abroad`、代理存在性选择 purpose；`data` 与 `json_data` 原样交给 requests；传入 headers、timeout；不默认调用 `raise_for_status()`；从 `response.content` 按 `content_conding` 解码，仅在 requests 已提供可靠 `response.text` 时保持原有文本行为。

- [ ] **Step 4: 固定历史兼容行为**

增加 POST、JSON、重定向 URL、400 响应正文、指定编码、连接错误转换为带根因字符串的测试。移除不安全的全局 `ssl_context`、`urllib` opener 和相关导入。

- [ ] **Step 5: 运行同步请求测试**

Run: `& '<bundled-python>' -m pytest tests/http_clients/test_sync_http.py -q`

Expected: 全部 PASS。

### Task 5: 暴露并接入资源关闭生命周期

**Files:**
- Create: `tests/http_clients/test_public_api.py`
- Create: `tests/http_clients/test_runner.py`
- Create: `src/http_clients/runner.py`
- Modify: `src/http_clients/__init__.py`
- Modify: `main.py`

- [ ] **Step 1: 写失败测试，固定公开关闭 API**

```python
from src.http_clients import close_async_clients, close_sync_sessions


def test_close_functions_are_public():
    assert callable(close_async_clients)
    assert callable(close_sync_sessions)
```

- [ ] **Step 2: 运行并确认导入失败**

Run: `& '<bundled-python>' -m pytest tests/http_clients/test_public_api.py -q`

Expected: collection FAIL，关闭函数尚未从包导出。

- [ ] **Step 3: 从包入口导出两个关闭函数**

```python
from .client_pool import close_async_clients, close_sync_sessions

__all__ = ["close_async_clients", "close_sync_sessions"]
```

- [ ] **Step 4: 写失败测试，固定临时事件循环的清理顺序**

```python
from unittest.mock import AsyncMock, patch

from src.http_clients.runner import run_async


def test_run_async_closes_current_loop_clients_after_result():
    async def operation():
        return "ok"

    with patch(
        "src.http_clients.runner.close_async_clients_for_current_loop",
        new=AsyncMock(),
    ) as close:
        assert run_async(operation()) == "ok"
    close.assert_awaited_once_with()
```

- [ ] **Step 5: 实现统一异步运行边界**

```python
def run_async(awaitable):
    async def execute():
        try:
            return await awaitable
        finally:
            await close_async_clients_for_current_loop()

    return asyncio.run(execute())
```

客户端池增加只移除并关闭当前循环键的 `close_async_clients_for_current_loop()`。它与全量 `close_async_clients()` 都必须幂等。

- [ ] **Step 6: 机械替换主程序的临时事件循环入口**

在 `main.py` 导入 `run_async`，将全部 `asyncio.run(` 替换为 `run_async(`。运行 `rg -n "asyncio\.run" main.py`，预期无匹配；不得修改协程参数或平台分支逻辑。同步 Session 仍由 `atexit` 兜底关闭。

- [ ] **Step 7: 运行公开 API、runner 与池生命周期测试**

Run: `& '<bundled-python>' -m pytest tests/http_clients/test_public_api.py tests/http_clients/test_runner.py tests/http_clients/test_client_pool.py -q`

Expected: 全部 PASS，且无未关闭客户端警告。

### Task 6: 锁定依赖并建立质量门禁

**Files:**
- Modify: `pyproject.toml`
- Create: `uv.lock`

- [ ] **Step 1: 检测可用运行时**

使用 Codex 工作区依赖提供的 Python 绝对路径运行 `-m pytest --version`。运行 `Get-Command uv`；若系统未提供 uv，使用 bundled Python 执行 `-m pip install uv` 仅安装到工作区运行环境，再使用 `python -m uv`。

- [ ] **Step 2: 补齐异步测试依赖和 Ruff 范围**

在 `[dependency-groups].dev` 增加 `pytest-asyncio>=0.24.0`。配置 pytest 的 `asyncio_mode = "auto"`；Ruff 初始检查范围由命令显式限定为 `src/http_clients tests/http_clients`，避免格式化无关历史文件。

- [ ] **Step 3: 生成锁文件**

Run: `uv lock`

Expected: exit 0，并生成 `uv.lock`。

- [ ] **Step 4: 使用锁文件同步并运行阶段一门禁**

Run: `uv sync --group dev`

Expected: exit 0。

Run: `uv run ruff check src/http_clients tests/http_clients`

Expected: exit 0。

Run: `uv run ruff format --check src/http_clients tests/http_clients`

Expected: exit 0。

Run: `uv run pytest -q`

Expected: 全部测试 PASS，无网络访问和资源泄漏警告。

- [ ] **Step 5: TLS 例外审计**

Run: `rg -n "verify\s*=\s*False|CERT_NONE|check_hostname\s*=\s*False" src main.py`

Expected: 只允许已确认的平台调用点显式 `verify=False`；HTTP 客户端公共入口、同步 SSL 上下文中不得出现不安全默认值。

### Task 7: 阶段验收与文档回写

**Files:**
- Modify: `docs/项目优化实施路线图.md`

- [ ] **Step 1: 运行完整新鲜验证**

依次重新运行 lock 同步、限定 Ruff check、限定 Ruff format check、完整 pytest，以及 TLS 例外审计；记录退出码与测试数量。

- [ ] **Step 2: 对照设计逐条验收**

检查连接复用、用途隔离、事件循环隔离、默认 TLS、分类错误、兼容返回、幂等关闭、锁文件和质量门禁九项，每一项必须有测试或命令输出证据。

- [ ] **Step 3: 更新路线图阶段一状态**

仅在 Step 1 和 Step 2 全部满足后，在阶段一产出下增加完成日期、验证命令和仍保留的显式 TLS 例外；如有未满足项，保持阶段未完成并记录具体缺口。

- [ ] **Step 4: Git 状态说明**

再次运行 `git rev-parse --show-toplevel`。若仍不是 Git 仓库，在交付说明中列出该限制，不声称已提交；不得执行 `git init`。
