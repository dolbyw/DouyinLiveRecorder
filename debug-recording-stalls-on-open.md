# Debug Session: recording-stalls-on-open
- **Status**: [OPEN]
- **Issue**: Windows 下打开正在录制的文件后，文件大小停止增长，但主界面仍显示“正在录制”
- **Debug Server**: http://127.0.0.1:7777/event
- **Log File**: .dbg/trae-debug-log-recording-stalls-on-open.ndjson

## Reproduction Steps
1. 启动 `dist/DouyinLiveRecorder/DouyinLiveRecorder.exe`
2. 使用抖音直播间地址触发录制
3. 在录制过程中打开当前正在写入的分段文件
4. 观察文件大小、ffmpeg 子进程状态和主界面录制状态

## Hypotheses & Verification
| ID | Hypothesis | Likelihood | Effort | Evidence |
|----|------------|------------|--------|----------|
| A | 打开文件后播放器或系统对当前 `.ts` 文件加了独占/阻塞访问，导致 ffmpeg 写入失败退出 | High | Med | Rejected (本轮用 MPC-HC 复现时，打开后文件仍持续增长) |
| B | ffmpeg 实际已经退出，但主线程没有及时 `poll()` / 清理 `recording` 集合，导致界面显示滞后 | High | Low | Pending |
| C | 分段录制或后处理线程在打开文件后进入异常分支，主循环未同步错误状态 | Med | Med | Pending |
| D | 文件仍在写入，但资源管理器或播放器缓存导致看到的文件大小不刷新 | Low | Low | More Likely |
| E | 打开文件触发 Windows 文件共享异常，ffmpeg 卡住未退出，主界面因此持续认为在录制 | Med | Med | Rejected (本轮用 MPC-HC 复现时未出现卡住) |

## Log Evidence
- 用户补充：此前触发问题的软件为 `MPC-HC`
- 本轮复现反馈：使用 `MPC-HC` 打开当前录制文件后，文件仍“持续增长”
- 当前未再次复现“文件停止增长但界面仍显示录制”的症状

## Verification Conclusion
- 当前没有拿到再次复现的运行时异常证据
- “打开文件必然导致录制中断”这一类强因果假设暂不成立
- 剩余更值得关注的是“偶发条件触发”或“文件大小观察存在缓存/对象切换误判”
