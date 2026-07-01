# 2026-07-01 项目改进方案

## 目标

围绕当前项目的执行逻辑、鲁棒性、正确性和交互便利性做小步改进。每次改动都保持低风险、可测试、可回滚，并在本文档中记录。

## 改进原则

- 优先处理已有模块边界内的问题，不做大规模重构。
- 每个行为变更先补测试，再修改实现。
- 每个改进点包含问题、方案、影响范围和验证方式。
- 保持兼容旧配置和旧调度路径，避免影响未迁移平台。

## 第一批改进范围

### 1. 录制执行器并发限制

问题：`RecordingExecutor(max_workers=4)` 目前只校验参数，实际没有限制并发录制线程数量。

方案：在 `RecordingExecutor` 内引入异步信号量，让 `max_workers` 真正限制同时运行的录制任务数。

影响范围：`src/runtime/recording.py` 和对应单元测试。

验证方式：新增测试证明第二个录制任务会等待第一个释放 worker；运行 runtime 相关测试和全量测试。

### 2. 平台探测错误上下文

问题：注册平台探测失败时，错误信息主要是平台名，用户难以判断是代理、Cookie、签名还是网络失败。

方案：在 `RegisteredPlatformProbe` 抛出的错误中保留原始异常类型和消息，仍保持现有异常链。

影响范围：`src/runtime/platform_probe.py` 和对应单元测试。

验证方式：新增测试覆盖错误消息包含平台名和根因。

### 3. URL 配置解析保留含逗号昵称

问题：`URL_config.ini` 使用逗号分割时，昵称里如果也包含逗号，当前只保留第三段，后续内容丢失。

方案：解析三段及以上配置时，将第三段之后的内容重新用逗号合并为昵称。

影响范围：`src/config_loader.py` 和 URL 配置解析测试。

验证方式：新增测试覆盖 `质量,url,主播,别名` 形式。

## 变更记录

记录格式：时间、改进点、修改文件、验证命令、结果。

- 2026-07-01 录制执行器并发限制
  - 修改文件：`src/runtime/recording.py`、`tests/runtime/test_recording_executor.py`
  - 内容：让 `RecordingExecutor(max_workers=...)` 通过异步信号量限制同时启动的录制线程数；更新测试，明确第二个房间会等待 worker 释放。
  - 验证：`.venv\Scripts\python.exe -m pytest tests\runtime\test_recording_executor.py -q`
  - 结果：`7 passed`
- 2026-07-01 平台探测错误上下文
  - 修改文件：`src/runtime/platform_probe.py`、`tests/runtime/test_platform_probe.py`
  - 内容：注册平台探测失败时，`PlatformProbeError` 现在包含平台展示名、根因异常类型和根因消息，异常链保持不变。
  - 验证：`.venv\Scripts\python.exe -m pytest tests\runtime\test_platform_probe.py -q`
  - 结果：`3 passed`
- 2026-07-01 URL 配置昵称逗号保留
  - 修改文件：`src/config_loader.py`、`tests/test_url_config_parser.py`
  - 内容：解析 `质量,URL,昵称` 形式时，如果昵称自身包含逗号，会保留第三段之后的全部内容。
  - 验证：`.venv\Scripts\python.exe -m pytest tests\test_url_config_parser.py -q`
  - 结果：`7 passed`
- 2026-07-01 第一批全量验证
  - 修改文件：无新增代码修改，仅补充验证记录。
  - 内容：对第一批改进执行静态检查和全量测试。
  - 验证：
    - `.venv\Scripts\python.exe -m ruff check src\runtime\recording.py src\runtime\platform_probe.py src\config_loader.py tests\runtime\test_recording_executor.py tests\runtime\test_platform_probe.py tests\test_url_config_parser.py`
    - `.venv\Scripts\python.exe -m pytest -q`
  - 结果：`All checks passed!`；`384 passed`
- 2026-07-01 脱敏构建与推送前验证
  - 修改文件：无新增代码修改，仅补充构建记录。
  - 内容：使用临时 spec 从 `.tmp/packaging_config` 读取脱敏配置进行 PyInstaller 构建，避免把本地 `config/config.ini` 中的 Cookie 和 `config/URL_config.ini` 中的直播间地址打进发布包。
  - 构建：
    - `.venv\Scripts\python.exe -m PyInstaller .tmp\DouyinLiveRecorder.sanitized.spec --noconfirm --clean --distpath dist --workpath build\pyinstaller-sanitized`
    - `Compress-Archive -Path dist\DouyinLiveRecorder -DestinationPath DouyinLiveRecorder-latest-win64-20260701.zip -CompressionLevel Optimal`
  - 隐私验证：检查 zip 内 `DouyinLiveRecorder/config/config.ini` 和 `DouyinLiveRecorder/config/URL_config.ini`，未发现本地 Cookie、直播间地址或主播名。
  - 代码验证：
    - `.venv\Scripts\python.exe -m ruff check main.py src\cli_ui.py src\config_loader.py src\dashboard_state.py src\dashboard_view.py src\runtime\platform_probe.py src\runtime\recording.py src\uploader\factory.py src\uploader\rc_service.py src\uploader\service.py tests\runtime\test_main_runtime_wiring.py tests\runtime\test_platform_probe.py tests\runtime\test_recording_executor.py tests\test_cli_ui.py tests\test_dashboard_view.py tests\test_url_config_parser.py tests\uploader\test_factory.py tests\uploader\test_rc_service.py`
    - `.venv\Scripts\python.exe -m pytest -q`
  - 结果：定向 ruff `All checks passed!`；全量测试 `384 passed`。全仓库 ruff 仍受历史文件影响失败，未作为本次提交门禁。
