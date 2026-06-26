# DouyinLiveRecorder 代码改进路线图

> 交接用途：这份文档给新的 GPT-5/Codex 会话继续改代码使用。新会话应先阅读本文，再按阶段执行。不要一次性重构所有内容；每个阶段都要保持测试可运行、行为可验证。

## 当前代码现状

项目已经有较好的测试基础，最近一次完整测试命令：

```powershell
.\.venv\Scripts\python.exe -m pytest tests -q
```

结果为：

```text
301 passed
```

静态检查命令：

```powershell
.\.venv\Scripts\python.exe -m ruff check main.py src tests
```

当前约有 53 个 lint 问题，主要集中在：

- `src/spider.py`：超长硬编码 Cookie、异常链、旧类型写法、`print()` 输出。
- `src/initializer.py` / `src/utils.py` / 少量测试：导入排序、旧写法。
- 少量 `B904` 异常链问题会影响排错质量。

代码规模热点：

- `src/spider.py` 约 3000 行，包含 40+ 平台抓取逻辑。
- `main.py` 约 2000 行，混合了程序入口、配置读取、旧平台分发、录制调度、仪表盘、线程管理、兼容逻辑。

核心风险：

- `main.py` 导入时就执行初始化、检查 ffmpeg、启动线程和主循环，导致测试/复用困难。
- 新平台注册表已存在，但 `main.py::start_record()` 仍保留巨大旧分发链。
- 平台抓取与错误处理分散，抖音/TikTok 等易变平台维护成本高。
- `run_async()` 在同步兼容路径里反复创建事件循环并关闭 async client，削弱连接复用。

---

## 总体目标

把项目从“巨大入口脚本 + 兼容分发”逐步改成：

```text
main.py
  只负责入口、启动、装配、退出

runtime/
  负责配置刷新、房间调度、并发限制、停止控制

platforms/
  每个平台独立解析 URL、请求直播元数据、选择流地址

recorder/
  负责路径规划、ffmpeg 命令、录制进程、后处理

dashboard/
  负责状态存储、视图模型、Rich/plain 渲染
```

每个阶段都要满足：

- 完整测试仍通过。
- 主界面行为不退化。
- 抖音录制链路优先保持可用。
- 兼容旧平台时，先保留 fallback，不做一次性删除。

---

## 阶段一：让 `main.py` 可安全导入

### 收益

最高优先级。当前 `main.py` 在导入时执行大量副作用，阻碍测试和后续拆分。先解决入口问题，后续所有阶段都会更稳。

### 目标

把模块导入和程序运行分开：

```python
def main() -> int:
    ...
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
```

导入 `main.py` 时不得：

- 检查/安装 ffmpeg。
- 启动备份线程。
- 启动仪表盘线程。
- 进入主循环。
- 调用 `sys.exit()`。
- 修改配置文件或 URL 文件。

### 重点文件

- `main.py`
- `tests/runtime/test_main_runtime_wiring.py`
- 可新增：`tests/test_main_import.py`

### 建议步骤

1. 写失败测试：导入 `main` 不应退出。

```python
def test_import_main_has_no_startup_side_effects():
    import importlib

    module = importlib.import_module("main")

    assert hasattr(module, "main")
```

2. 将 `main.py` 底部从初始化程序开始的代码移动进 `main()`。

当前大致入口区在：

- `initial_app_config = load_app_config(...)`
- ffmpeg 检查
- 代理检测
- `while True:` 主循环

3. 保留所有现有全局函数和类，先不要顺手重构业务逻辑。

4. 把 `sys.exit(1)` / `sys.exit(-1)` 改为 `return 1` / `return -1`，只在 `if __name__ == "__main__"` 处转为进程退出码。

5. 验证：

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_main_import.py tests/runtime/test_main_runtime_wiring.py -q
.\.venv\Scripts\python.exe -m pytest tests -q
```

### 验收标准

- `import main` 不再触发 ffmpeg 检查。
- `import main` 不再启动线程。
- 完整测试通过。
- 直接运行程序的行为保持一致。

### 风险提示

这个阶段只做入口隔离，不要同时拆 `start_record()`。否则很容易把“入口副作用”和“录制逻辑变化”混在一起，排错会困难。

---

## 阶段二：收敛平台解析路径，弱化旧分发链

### 收益

非常高。当前已有 `src/platforms` 适配器和 `RegisteredPlatformProbe`，但 `main.py::start_record()` 仍然包含庞大的 `elif record_url.find(...)` 旧分发链。应逐步把平台解析逻辑迁移到适配器。

### 目标

让新运行时路径成为主路径：

```text
RoomSpec
  -> RegisteredPlatformProbe
  -> PlatformAdapter.resolve()
  -> stream_info
  -> start_record(resolved_once=stream_info)
  -> RecordingPipeline
```

`start_record()` 最终应只负责录制，不再负责平台识别和抓取。

### 重点文件

- `main.py`
- `src/platforms/base.py`
- `src/platforms/dispatch.py`
- `src/platforms/registry.py`
- `src/platforms/douyin.py`
- `src/platforms/tiktok.py`
- `src/platforms/bilibili.py`
- `src/platforms/huya.py`
- `src/runtime/platform_probe.py`
- `tests/platforms/*`
- `tests/runtime/test_main_runtime_wiring.py`

### 建议步骤

1. 先固定抖音链路测试。

新增或加强测试：

```python
async def test_douyin_adapter_returns_normalized_stream_info(monkeypatch):
    ...
    result = await DouyinAdapter().resolve(...)
    assert result["is_live"] is True
    assert result["record_url"]
    assert result["flv_url"]
```

2. 在 `main.py::start_record()` 中明确区分：

- 已有 `resolved_once`：直接跳过平台解析。
- 无 `resolved_once`：先走 registry。
- registry 未覆盖的平台：才走旧 fallback。

3. 对每个已迁移平台建立“旧分支不再命中”的文本测试。

示例：

```python
def test_registered_platforms_do_not_use_legacy_branch_when_async_runtime_active():
    source = Path("main.py").read_text(encoding="utf-8")
    assert "default_registry.find(url_tuple[1]) is not None" in source
```

4. 每次迁移 1-3 个平台，不要一次迁移 40 个。

推荐顺序：

- 抖音
- TikTok
- B站
- 虎牙
- 快手
- 斗鱼

5. 验证：

```powershell
.\.venv\Scripts\python.exe -m pytest tests/platforms tests/runtime/test_platform_probe.py tests/runtime/test_monitor.py -q
.\.venv\Scripts\python.exe -m pytest tests -q
```

### 验收标准

- 已有适配器平台优先走 registry。
- 旧 fallback 仍保留，未迁移平台不受影响。
- 抖音、TikTok、B站、虎牙平台测试通过。
- 完整测试通过。

### 风险提示

不要在这个阶段删除旧分发链。先让 registry 路径覆盖主要平台，并用测试证明新路径稳定，再计划删除。

---

## 阶段三：拆分 `src/spider.py`

### 收益

高。`src/spider.py` 太大，是平台接口变化时最大的维护成本来源。

### 目标

按平台或平台组拆分抓取逻辑，让每个模块只负责一个平台。

推荐目标结构：

```text
src/platforms/douyin/
  __init__.py
  adapter.py
  probe.py
  stream_select.py

src/platforms/tiktok/
  __init__.py
  adapter.py
  probe.py
  stream_select.py

src/platforms/common/
  headers.py
  payload.py
  errors.py
```

如果担心改动过大，可以先用较保守结构：

```text
src/platform_probes/douyin.py
src/platform_probes/tiktok.py
src/platform_probes/huya.py
```

### 重点文件

- `src/spider.py`
- `src/stream.py`
- `src/platforms/douyin.py`
- `tests/platforms/test_douyin.py`
- `tests/test_platform_payload_contract.py`

### 建议步骤

1. 先拆抖音，作为模板。

从 `src/spider.py` 移出：

- `get_douyin_web_stream_data`
- `get_douyin_app_stream_data`
- `get_douyin_stream_data`

从 `src/stream.py` 可考虑后续移出：

- `get_douyin_stream_url`

2. 在旧 `src/spider.py` 保留兼容 re-export：

```python
from src.platforms.douyin.probe import (
    get_douyin_app_stream_data,
    get_douyin_stream_data,
    get_douyin_web_stream_data,
)
```

这样旧调用不需要一次性全改。

3. 把抖音硬编码 Cookie 提取为常量，避免 2000+ 字符长行阻塞 lint。

4. 将 `print()` 改为 logger 或明确异常。

5. 验证：

```powershell
.\.venv\Scripts\python.exe -m pytest tests/platforms/test_douyin.py tests/test_platform_payload_contract.py -q
.\.venv\Scripts\python.exe -m pytest tests -q
```

### 验收标准

- 抖音抓取代码不再直接放在 `src/spider.py` 主体里。
- 旧导入路径仍可用。
- 抖音相关测试通过。
- 完整测试通过。

### 风险提示

不要同时改抖音解析逻辑和移动文件。第一步只移动代码并保持行为一致；第二步再改善异常和日志。

---

## 阶段四：优化 async/sync 边界和 HTTP 连接复用

### 收益

高，尤其是监控房间多时。

### 当前问题

`src/http_clients/client_pool.py` 已有 async client pool，但 `src/http_clients/runner.py::run_async()` 每次执行后都会关闭当前 loop 的 client。旧 `main.py` 分发链大量调用 `run_async()`，会削弱连接复用。

### 目标

- 新 runtime 路径全程 async。
- 旧兼容路径减少 `run_async()` 调用次数。
- 同一轮平台解析尽量复用同一个 event loop 和 HTTP client。

### 重点文件

- `src/http_clients/runner.py`
- `src/http_clients/client_pool.py`
- `src/runtime/platform_probe.py`
- `main.py`
- `tests/http_clients/*`
- `tests/runtime/*`

### 建议步骤

1. 先加测试锁定 async client pool 行为。

```python
async def test_async_clients_reused_within_same_loop():
    first = get_async_client(...)
    second = get_async_client(...)
    assert first is second
```

2. 对 registry 路径避免 `run_async()`；只在旧兼容线程中使用。

3. 若需要保留同步入口，新增批量 runner：

```python
def run_async_batch(factory: Callable[[], Awaitable[T]]) -> T:
    ...
```

确保一轮解析结束后再关闭 client。

4. 验证：

```powershell
.\.venv\Scripts\python.exe -m pytest tests/http_clients tests/runtime -q
.\.venv\Scripts\python.exe -m pytest tests -q
```

### 验收标准

- async runtime 不反复创建/销毁 client。
- 旧兼容路径行为不退化。
- HTTP client 测试通过。
- 完整测试通过。

### 风险提示

不要简单删除 `close_async_clients_for_current_loop()`。它负责清理资源。优化目标是减少不必要的创建/关闭，而不是泄漏连接。

---

## 阶段五：整理错误处理和日志

### 收益

中高。它不一定直接提升录制速度，但会明显提升问题定位效率。

### 当前问题

存在大量：

- `except Exception as e`
- `print(...)`
- `raise Exception(...)`
- 未使用 `raise ... from e`

这会让“接口变了、Cookie 失效、风控、未开播、不支持直播类型”混成普通异常。

### 目标

建立平台错误类型：

```python
class PlatformFetchError(RuntimeError): ...
class PlatformRiskControlError(PlatformFetchError): ...
class PlatformUnsupportedLiveError(PlatformFetchError): ...
class PlatformAuthError(PlatformFetchError): ...
```

平台层抛明确异常；runtime/main/dashboard 层统一展示。

### 重点文件

- `src/platforms/base.py`
- `src/platforms/dispatch.py`
- `src/runtime/platform_probe.py`
- `src/spider.py`
- 后续拆出的平台 probe 模块

### 建议步骤

1. 先引入异常类，不改变行为。
2. 从抖音开始替换异常：

```python
except HttpClientError as error:
    raise PlatformFetchError("Douyin web data fetch failed") from error
```

3. 把平台函数中的 `print()` 换成 `logger.warning/debug` 或抛异常。
4. 在 `RegisteredPlatformProbe` 中保留异常 cause。
5. 验证：

```powershell
.\.venv\Scripts\python.exe -m pytest tests/platforms tests/runtime/test_platform_probe.py -q
.\.venv\Scripts\python.exe -m ruff check src/platforms src/runtime/platform_probe.py
.\.venv\Scripts\python.exe -m pytest tests -q
```

### 验收标准

- 抖音解析失败时能保留原始异常链。
- 平台错误不会直接 `print()` 到控制台。
- 仪表盘仍能显示自动恢复/需处理状态。

---

## 阶段六：配置与 URL 文件刷新优化

### 收益

中等。主要改善长时间挂机稳定性和减少文件 IO 抖动。

### 当前问题

主循环每轮都会读配置和 URL 文件；还会边读边修改 URL 文件、删除重复行、注释无效链接。这些操作都集中在 `main.py` 底部主循环。

### 目标

- 基于文件 mtime 做增量刷新。
- URL 文件规范化集中写回。
- 仪表盘配置刷新复用已解析配置。

### 重点文件

- `main.py`
- `src/config_loader.py`
- `src/runtime/config.py`
- `tests/test_url_config_parser.py`
- `tests/runtime/test_runtime_config.py`

### 建议步骤

1. 新增 `ConfigFileWatcher` 或简单缓存：

```python
@dataclass
class LoadedConfigCache:
    path: Path
    mtime_ns: int
    value: AppConfig
```

2. `load_app_config()` 保持纯函数，不在内部缓存；缓存放在调用层。
3. URL 文件解析和写回分开：

```text
read -> parse -> normalize -> compute edits -> write once
```

4. 验证：

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_config_loader.py tests/test_url_config_parser.py tests/runtime/test_runtime_config.py -q
.\.venv\Scripts\python.exe -m pytest tests -q
```

### 验收标准

- 配置未变时不重复解析。
- URL 文件规范化只在有变化时写回。
- 旧配置项兼容。

---

## 阶段七：资源管理和安全边界

### 收益

中等，但成本低，适合穿插做。

### 优化项

1. `direct_download_stream()` 中 `httpx.Client(timeout=None)` 应使用上下文管理器关闭。

目标：

```python
with httpx.Client(timeout=None, follow_redirects=True) as client:
    ...
```

2. `run_script()` 当前使用 `subprocess.Popen(..., shell=True)`，需明确这是兼容模式，并新增更安全的 argv 模式或加强参数转义。

3. `RecorderProcess` 已经会优雅停止 ffmpeg，保持这部分行为，不要替换为简单 kill。

### 重点文件

- `main.py`
- `src/recorder/process.py`
- `tests/recorder/test_process.py`
- 可新增：`tests/test_direct_download.py`

### 验证

```powershell
.\.venv\Scripts\python.exe -m pytest tests/recorder tests/test_cli_ui.py -q
.\.venv\Scripts\python.exe -m pytest tests -q
```

---

## 阶段八：静态检查清理

### 收益

中等偏低，但能降低长期维护噪音。

### 当前 lint 摘要

```text
12 E501 line-too-long
9  B904 raise-without-from-inside-except
9  I001 unsorted-imports
4  B007 unused-loop-control-variable
4  UP009 utf8-encoding-declaration
4  UP042 replace-str-enum
3  B905 zip-without-explicit-strict
...
```

### 建议顺序

1. 先修 `B904`，因为它影响错误链。
2. 再修 `B007` / `B905`，风险低。
3. 再运行安全的自动修复：

```powershell
.\.venv\Scripts\python.exe -m ruff check main.py src tests --fix
```

4. 暂缓 `--unsafe-fixes`，除非有专门测试覆盖。
5. 最后处理超长硬编码 Cookie：应提取为常量或配置，而不是简单换行。

### 验证

```powershell
.\.venv\Scripts\python.exe -m ruff check main.py src tests
.\.venv\Scripts\python.exe -m pytest tests -q
```

### 验收标准

- ruff 问题数量显著下降。
- 完整测试通过。
- 不因格式清理改变平台请求行为。

---

## 推荐执行顺序

1. 阶段一：`main.py` 可安全导入。
2. 阶段二：平台解析路径收敛。
3. 阶段四：async/sync 边界和 HTTP 复用。
4. 阶段三：拆分 `spider.py`，先从抖音开始。
5. 阶段五：错误处理和日志。
6. 阶段六：配置/URL 文件刷新。
7. 阶段七：资源管理和安全边界。
8. 阶段八：静态检查清理。

这样排序的原因：

- 入口可导入是后续所有测试和拆分的基础。
- 平台解析路径收敛直接降低录制主链路复杂度。
- HTTP 复用和异步边界会影响多房间监控性能。
- `spider.py` 拆分收益高，但应建立在入口和平台路径稳定之后。
- lint 清理最后做，避免和行为重构混在一起。

---

## 新会话启动提示词建议

可以把下面这段发给新的 GPT-5/Codex 会话：

```text
请先阅读 docs/superpowers/plans/2026-06-25-codebase-improvement-roadmap.md。
按文档从“阶段一：让 main.py 可安全导入”开始实施。
要求：
1. 不要一次性重构多个阶段。
2. 每个阶段先写/更新测试，再改实现。
3. 每个阶段完成后运行文档指定的 pytest 命令。
4. 保持抖音录制链路和主界面行为不退化。
5. 当前项目完整测试基线是：.\.venv\Scripts\python.exe -m pytest tests -q，应保持通过。
```

---

## 交接检查清单

新会话开始前应确认：

- [ ] 当前工作区是否有未提交/未说明的改动。
- [ ] `.\.venv\Scripts\python.exe -m pytest tests -q` 是否通过。
- [ ] 是否从阶段一开始，而不是直接大规模拆 `spider.py`。
- [ ] 每次改动是否能用测试说明行为没有退化。
- [ ] 是否保留旧 fallback，直到新 registry 路径覆盖并验证对应平台。
