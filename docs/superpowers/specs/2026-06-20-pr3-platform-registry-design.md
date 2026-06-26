# PR3 平台注册表第一批迁移设计

## 目标

将抖音、TikTok、B站和虎牙四个平台迁移到可独立测试的平台适配器与注册表，同时保留 `main.py` 中的旧平台分发作为回退路径。迁移后，新路径继续复用现有 `src/spider.py` 和 `src/stream.py`，不改变录制管线及其余平台行为。

## 范围

本次包含：

- 新增平台适配器协议、调用上下文和注册表；
- 实现抖音、TikTok、B站、虎牙四个适配器；
- 在 `main.py` 中加入注册表优先、旧逻辑回退的分发入口；
- 为 URL 匹配、注册表、适配器调用、虎牙质量分支、TikTok 代理约束及回退行为补充测试；
- 更新项目优化路线图中的 PR3 进展。

本次不包含：

- 重写或拆分 `src/spider.py`、`src/stream.py`；
- 删除其他平台的旧分发逻辑；
- 抽离代理计算、信号量管理或录制管线；
- 引入平台专属请求客户端或更复杂的插件生命周期。

## 方案选择

采用“薄适配器 + 显式上下文 + 旧逻辑回退”。每个平台适配器只协调已有探测函数、归一化函数和选流函数。相比数据驱动函数表，该方案能清楚表达虎牙的质量分支和 TikTok 的代理前置条件；相比完整平台服务层，该方案控制了 PR3 的回归范围。

## 架构

新增 `src/platforms/` 包：

- `base.py`：定义 `PlatformAdapter` 协议、`PlatformContext` 和无法执行新路径时使用的异常；
- `registry.py`：维护有序适配器集合，提供注册和按 URL 查找能力；
- `douyin.py`、`tiktok.py`、`bilibili.py`、`huya.py`：四个平台的薄适配器；
- `__init__.py`：构建并导出默认注册表及公共类型。

`PlatformContext` 只携带本次调用需要的数据：代理地址、平台 Cookie，以及 TikTok 判断网络前置条件所需的标记。适配器不读取 `main.py` 全局变量。

适配器统一提供异步操作：

- `match(url) -> bool`：判断 URL 是否属于平台；
- `fetch(url, context) -> dict`：调用现有 `spider.py` 探测函数；
- `normalize(raw_data) -> dict`：调用统一平台结果归一化入口；
- `select_stream(info, quality, context) -> dict`：调用现有 `stream.py` 或返回已有选流结果；
- `resolve(url, quality, context) -> dict`：按 `fetch -> normalize -> select_stream` 串联前三步，并保证最终结果符合 `StreamInfo` 字典契约。

注册表保持注册顺序，拒绝同一适配器类型重复注册。`find(url)` 返回第一个匹配适配器；未命中时返回 `None`。默认注册表包含且只包含本次迁移的四个平台。

## 平台行为

### 抖音

- 匹配 `live.douyin.com`、`v.douyin.com` 和 `www.douyin.com`；
- 普通直播间 URL 调用 `get_douyin_web_stream_data()`；短链或用户页调用 `get_douyin_app_stream_data()`；
- 归一化后调用 `get_douyin_stream_url()`。

### TikTok

- 匹配 `www.tiktok.com`；
- 仅当全局代理或当前调用代理可用时调用 `get_tiktok_stream_data()`；
- 前置条件不满足时抛出“新路径不可执行”异常，由主分发入口回退到旧逻辑；
- 归一化后调用 `get_tiktok_stream_url()`。

### B站

- 匹配 `live.bilibili.com`；
- 调用 `get_bilibili_room_info()`；
- 归一化后调用 `get_bilibili_stream_url()`，传递质量、代理和 Cookie。

### 虎牙

- 匹配 `www.huya.com`；
- `OD`、`BD`、`UHD` 质量直接调用 `get_huya_app_stream_url()`，其返回值作为最终流信息；
- 其他质量调用 `get_huya_stream_data()`，归一化后再调用 `get_huya_stream_url()`。

## 主流程与回退

`main.py` 提供一个可独立测试的适配器分发辅助函数。每次轮询先用默认注册表查找 URL：

1. 未命中时返回“未处理”，继续执行现有平台 `if/elif`；
2. 命中时在现有信号量保护范围内构造上下文并执行适配器；
3. 得到正常结果（包括未开播）时返回“已处理”，不再调用旧平台逻辑；
4. 适配器抛出异常或报告前置条件不满足时记录警告并返回“未处理”，随后执行旧逻辑。

为避免重复请求，“未开播”不属于失败，也不触发回退。旧四平台分支在 PR3 中保留，作为显式 fallback；其余平台分支保持原状。

## 错误处理

- 适配器不吞掉探测或选流异常；
- 主分发入口统一捕获适配器异常，日志包含平台名、URL 和回退动作；
- 注册表匹配本身不执行网络操作；
- 最终结果使用 `normalize_stream_info()` 收口，避免适配器泄漏平台私有形状；
- 回退路径沿用现有错误处理和重试行为。

## 测试

采用测试驱动开发，覆盖：

- 四个平台 URL 的正向与反向匹配；
- 注册、重复注册、注册顺序和 URL 查找；
- 四个适配器向已有探测及选流函数传递正确参数；
- 抖音网页与短链/用户页分支；
- 虎牙 App 质量与网页质量分支；
- TikTok 有代理和无代理两种行为；
- 未开播结果被视为成功处理；
- 适配器异常触发旧逻辑回退；
- 未注册平台直接进入旧逻辑；
- 四个平台最终输出满足 `StreamInfo` 契约；
- 完整 `pytest` 与 `ruff check` 回归。

## 验收标准

- 默认注册表能够识别并返回四个平台适配器；
- 四个平台可通过新入口完成探测与选流；
- 新路径正常返回时不会重复执行旧请求；
- 新路径失败时旧分发仍可用；
- 其余平台行为不变；
- 新增测试、完整测试与静态检查通过；
- 路线图准确记录 PR3 第一批迁移状态和后续清理条件。
