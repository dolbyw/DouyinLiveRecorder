![video_spider](https://socialify.git.ci/ihmily/DouyinLiveRecorder/image?font=Inter&forks=1&language=1&owner=1&pattern=Circuit%20Board&stargazers=1&theme=Light)

## 简介
[![Python Version](https://img.shields.io/badge/python-3.11.6-blue.svg)](https://www.python.org/downloads/release/python-3116/)
[![Supported Platforms](https://img.shields.io/badge/platforms-Windows%20%7C%20Linux-blue.svg)](https://github.com/ihmily/DouyinLiveRecorder)
[![Docker Pulls](https://img.shields.io/docker/pulls/ihmily/douyin-live-recorder?label=Docker%20Pulls&color=blue&logo=docker)](https://hub.docker.com/r/ihmily/douyin-live-recorder/tags)
![GitHub issues](https://img.shields.io/github/issues/ihmily/DouyinLiveRecorder.svg)
[![Latest Release](https://img.shields.io/github/v/release/ihmily/DouyinLiveRecorder)](https://github.com/ihmily/DouyinLiveRecorder/releases/latest)
[![Downloads](https://img.shields.io/github/downloads/ihmily/DouyinLiveRecorder/total)](https://github.com/ihmily/DouyinLiveRecorder/releases/latest)

DouyinLiveRecorder 是一款可循环值守的直播录制工具，基于 FFmpeg 实现多平台直播源录制，支持多人监控、自动转码、运行状态仪表盘、直播状态推送，以及录制完成后的自动上传。

</div>

## 已支持平台

- [x] 抖音
- [x] TikTok
- [x] 快手
- [x] 虎牙
- [x] 斗鱼
- [x] YY
- [x] B站
- [x] 小红书
- [x] bigo 
- [x] blued
- [x] SOOP(原AfreecaTV)
- [x] 网易cc
- [x] 千度热播
- [x] PandaTV
- [x] 猫耳FM
- [x] Look直播
- [x] WinkTV
- [x] TTingLive(原Flextv)
- [x] PopkonTV
- [x] TwitCasting
- [x] 百度直播
- [x] 微博直播
- [x] 酷狗直播
- [x] TwitchTV
- [x] LiveMe
- [x] 花椒直播
- [x] 流星直播
- [x] ShowRoom
- [x] Acfun
- [x] 映客直播
- [x] 音播直播
- [x] 知乎直播
- [x] CHZZK
- [x] 嗨秀直播
- [x] vv星球直播
- [x] 17Live
- [x] 浪Live
- [x] 畅聊直播
- [x] 飘飘直播
- [x] 六间房直播
- [x] 乐嗨直播
- [x] 花猫直播
- [x] Shopee
- [x] Youtube
- [x] 淘宝
- [x] 京东
- [x] Faceit
- [x] 咪咕
- [x] 连接直播
- [x] 来秀直播
- [x] Picarto
- [ ] 更多平台正在更新中

</div>

## 项目结构

```
.
└── DouyinLiveRecorder/
    ├── config/              # 配置文件目录
    ├── logs/                # 运行日志目录
    ├── backup_config/       # 配置备份目录
    ├── src/                 # 主程序源码
    │   ├── initializer.py   # 运行环境检测与初始化
    │   ├── spider.py        # 获取直播间数据
    │   ├── stream.py        # 获取直播流地址
    │   ├── utils.py         # 通用工具函数
    │   ├── logger.py        # 日志封装
    │   ├── room.py          # 直播间信息解析
    │   ├── ab_sign.py       # 抖音签名参数生成
    │   ├── uploader/        # 自动上传服务
    │   └── javascript/      # 平台解密与签名脚本
    ├── main.py              # 程序入口
    ├── ffmpeg_install.py    # FFmpeg 安装辅助脚本
    ├── demo.py              # 调用示例
    ├── msg_push.py          # 直播状态推送
    ├── index.html           # m3u8/flv 播放测试页
    ├── requirements.txt     # 运行依赖
    ├── docker-compose.yaml  # Docker Compose 配置
    ├── Dockerfile           # Docker 镜像构建文件
    ├── DouyinLiveRecorder.spec # Windows 打包配置
    ├── StopRecording.vbs    # Windows 停止录制脚本
    ...
```

</div>

## 使用说明

- 如果只想直接使用软件，可以进入 [Releases](https://github.com/ihmily/DouyinLiveRecorder/releases) 下载最新发布的 zip 压缩包，里面包含已经打包好的可执行程序。（部分安全软件可能误报，请根据实际情况判断；如果浏览器拦截下载，可以更换浏览器或手动放行。）

- 解压后，在 `config/URL_config.ini` 中添加要录制的直播间地址，一行一个地址。如果需要调整录制参数，可以修改 `config/config.ini`，推荐录制格式使用 `ts`。
- 配置完成后运行 `DouyinLiveRecorder.exe` 即可开始监控和录制。默认录制文件保存在程序同目录的 `downloads` 文件夹中。

- 如果需要录制 TikTok、SOOP 等海外平台，请在配置文件中开启代理并填写 `proxy_addr`，例如 `127.0.0.1:7890`（仅为示例，请按实际代理地址填写）。

- 如果 `URL_config.ini` 中的某个直播间暂时不想录制，又不想删除配置，可以在该行开头加上 `#`，程序会停止监测和录制该直播间。

- 软件默认录制清晰度为 `原画`。如果要单独设置某个直播间的录制画质，可以在直播间地址前加画质名称，例如 `超清,https://live.douyin.com/745964462470`，中间使用英文逗号分隔。

- 如果要长时间循环监测直播，建议把检测间隔设置得稍长一些，避免请求过于频繁导致平台限制访问。

- 要停止所有录制，Windows 平台可以运行 `StopRecording.vbs`，也可以在控制台中使用 `Ctrl+C` 中断程序。若只想停止某个直播间，请在 `URL_config.ini` 中把对应地址前加上 `#`，程序会正常结束该直播间录制并保存已有文件。
- 程序启动后会显示终端仪表盘，主界面包含直播间状态、录制时长、磁盘占用、上传状态和最近运行动态。按 `R` 可切换直播间列表显示数量，按 `U` 可查看或收起上传详情。
- 欢迎给项目点 Star，也欢迎提交 Pull Request。

### 自动上传到 WebDAV 网盘

程序支持通过 [Rclone](https://rclone.org/) 将录制完成的历史文件自动移动到 WebDAV 网盘，例如提前通过 `rclone config` 配置好的 `123pan` 远程端。上传功能默认关闭；开启后可在控制台仪表盘的健康区、配置区和运行动态中查看上传状态，按 `U` 可查看或收起上传详情。

在 `config/config.ini` 中添加或修改：

```ini
[自动上传]
是否启用自动上传 = 否
上传执行方式 = rc
上传触发模式 = 录制结束
上传源目录(不填则跟随直播保存路径) =
上传目标路径 = 123pan:/LiveBackup/
rclone可执行文件路径 =
rclone控制端口 = 5572
最小文件冷却时间 = 1h
上传并发数 = 2
检查并发数 = 2
rclone失败重试次数 = 3
应用层失败重试次数 = 3
失败后等待秒数 = 900
上传完成后删除空目录 = 是
演练模式dry-run = 否

[自动上传-录制结束]
是否启用 = 是

[自动上传-每日定时]
是否启用 = 否
每日定时上传时间 = 03:00

[自动上传-间隔检查]
是否启用 = 否
上传检查间隔(秒) = 300

[自动上传-WebDAV]
远程名称 = 123pan
WebDAV地址 =
WebDAV用户名 =
WebDAV密码 =
WebDAV厂商 = other
```

说明：

- `上传源目录` 为空时，自动跟随“直播保存路径”；如果直播保存路径也为空，则使用同目录下 `downloads`。
- `上传触发模式` 支持 `录制结束`、`定时`、`每日定时`、`间隔`、`间隔检查`。三个 `[自动上传-*]` 触发区块互斥；如果只启用一个区块，就使用该区块；如果同时启用多个区块，则按 `[自动上传]` 里的 `上传触发模式` 选择，其余区块参数不会参与本次运行。
- `[自动上传-WebDAV]` 填写完整后，程序会在上传前执行 `rclone config create <远程名称> webdav ...` 准备 remote；如果留空，则沿用已经手动配置好的 rclone remote。
- 上传使用 `rclone move`，成功后由 rclone 删除本地源文件。
- `上传执行方式 = rc` 会使用 rclone 官方 Remote Control API，并在仪表盘中显示上传进度；如本机环境不适合 RC，可改为 `上传执行方式 = 命令行` 回退到一次性命令行上传。
- `录制结束` 会在录制和转码成功后立即上传；`最小文件冷却时间` 仅用于定时/间隔扫描，避免移动仍在写入的文件。
- 123 云盘 WebDAV 建议保持 `上传并发数 = 2`、`检查并发数 = 2`。
- 首次启用前建议先设置 `演练模式dry-run = 是`，确认日志和目标路径无误后再改为 `否`。
- 程序运行中修改 `[自动上传]` 会自动热更新；目标路径、执行方式、触发模式等变更会启动新上传计划，旧计划会在等待结束或当前上传任务结束后退出。

&emsp;

直播间链接示例：

```
抖音:
https://live.douyin.com/745964462470
https://v.douyin.com/iQFeBnt/
https://live.douyin.com/yall1102  （链接+抖音号）
https://v.douyin.com/CeiU5cbX  （主播主页地址）

TikTok:
https://www.tiktok.com/@pearlgaga88/live

快手:
https://live.kuaishou.com/u/yall1102

虎牙:
https://www.huya.com/52333

斗鱼:
https://www.douyu.com/3637778?dyshid=
https://www.douyu.com/topic/wzDBLS6?rid=4921614&dyshid=

YY:
https://www.yy.com/22490906/22490906

B站:
https://live.bilibili.com/320

小红书（直播间分享地址):
http://xhslink.com/xpJpfM

bigo直播:
https://www.bigo.tv/cn/716418802

buled直播:
https://app.blued.cn/live?id=Mp6G2R

SOOP:
https://play.sooplive.co.kr/sw7love

网易cc:
https://cc.163.com/583946984

千度热播:
https://qiandurebo.com/web/video.php?roomnumber=33333

PandaTV:
https://www.pandalive.co.kr/live/play/bara0109

猫耳FM:
https://fm.missevan.com/live/868895007

Look直播:
https://look.163.com/live?id=65108820&position=3

WinkTV:
https://www.winktv.co.kr/live/play/anjer1004

FlexTV(TTinglive)::
https://www.flextv.co.kr/channels/593127/live

PopkonTV:
https://www.popkontv.com/live/view?castId=wjfal007&partnerCode=P-00117
https://www.popkontv.com/channel/notices?mcid=wjfal007&mcPartnerCode=P-00117

TwitCasting:
https://twitcasting.tv/c:uonq

百度直播:
https://live.baidu.com/m/media/pclive/pchome/live.html?room_id=9175031377&tab_category

微博直播:
https://weibo.com/l/wblive/p/show/1022:2321325026370190442592

酷狗直播:
https://fanxing2.kugou.com/50428671?refer=2177&sourceFrom=

TwitchTV:
https://www.twitch.tv/gamerbee

LiveMe:
https://www.liveme.com/zh/v/17141543493018047815/index.html

花椒直播:
https://www.huajiao.com/l/345096174

流星直播:
https://www.7u66.com/100960

ShowRoom:
https://www.showroom-live.com/room/profile?room_id=480206  （主播主页地址）

Acfun:
https://live.acfun.cn/live/179922

映客直播:
https://www.inke.cn/liveroom/index.html?uid=22954469&id=1720860391070904

音播直播:
https://live.ybw1666.com/800002949

知乎直播:
https://www.zhihu.com/people/ac3a467005c5d20381a82230101308e9 (主播主页地址)

CHZZK:
https://chzzk.naver.com/live/458f6ec20b034f49e0fc6d03921646d2

嗨秀直播:
https://www.haixiutv.com/6095106

VV星球直播:
https://h5webcdn-pro.vvxqiu.com//activity/videoShare/videoShare.html?h5Server=https://h5p.vvxqiu.com&roomId=LP115924473&platformId=vvstar

17Live:
https://17.live/en/live/6302408

浪Live:
https://www.lang.live/en-US/room/3349463

畅聊直播:
https://live.tlclw.com/106188

飘飘直播:
https://m.pp.weimipopo.com/live/preview.html?uid=91648673&anchorUid=91625862&app=plpl

六间房直播:
https://v.6.cn/634435

乐嗨直播:
https://www.lehaitv.com/8059096

花猫直播:
https://h.catshow168.com/live/preview.html?uid=19066357&anchorUid=18895331

Shopee:
https://sg.shp.ee/GmpXeuf?uid=1006401066&session=802458

Youtube:
https://www.youtube.com/watch?v=cS6zS5hi1w0

淘宝(需cookie):
https://tbzb.taobao.com/live?liveId=532359023188
https://m.tb.cn/h.TWp0HTd

京东:
https://3.cn/28MLBy-E

Faceit:
https://www.faceit.com/zh/players/Compl1/stream

连接直播:
https://show.lailianjie.com/10000258

咪咕直播:
https://www.miguvideo.com/p/live/120000541321

来秀直播:
https://www.imkktv.com/h5/share/video.html?uid=1845195&roomId=1710496

Picarto:
https://www.picarto.tv/cuteavalanche
```

&emsp;

## 🎃源码运行
使用源码运行，可参考下面的步骤。

1.首先拉取或手动下载本仓库项目代码

```bash
git clone https://github.com/ihmily/DouyinLiveRecorder.git
```

2.进入项目文件夹，安装依赖

```bash
cd DouyinLiveRecorder
```

> [!TIP]
> - 不论你是否已安装 **Python>=3.10** 环境, 都推荐使用 [**uv**](https://github.com/astral-sh/uv) 运行, 因为它可以自动管理虚拟环境和方便地管理 **Python** 版本, **不过这完全是可选的**<br />
> 使用以下命令安装
>    ```bash
>    # 在 macOS 和 Linux 上安装 uv
>    curl -LsSf https://astral.sh/uv/install.sh | sh
>    ```
>    ```powershell
>    # 在 Windows 上安装 uv
>    powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
>    ```
> - 如果安装依赖速度太慢, 你可以考虑使用国内 pip 镜像源:<br />
> 在 `pip` 命令使用 `-i` 参数指定, 如 `pip3 install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple`<br />
> 或者在 `uv` 命令 `--index` 选项指定, 如 `uv sync --index https://pypi.tuna.tsinghua.edu.cn/simple`

<details>

  <summary>如果已安装 <b>Python>=3.10</b> 环境</summary>

  - :white_check_mark: 在虚拟环境中安装 (推荐)
  
    1. 创建虚拟环境

       - 使用系统已安装的 Python, 不使用 uv
  
         ```bash
         python -m venv .venv
         ```

       - 使用 uv, 默认使用系统 Python, 你可以添加 `--python` 选项指定 Python 版本而不使用系统 Python [uv官方文档](https://docs.astral.sh/uv/concepts/python-versions/)
       
         ```bash
         uv venv
         ```
    
    2. 在终端激活虚拟环境 (在未安装 uv 或你想要手动激活虚拟环境时执行, 若已安装 uv, 可以跳过这一步, uv 会自动激活并使用虚拟环境)
   
       **Bash** 中
       ```bash
       source .venv/Scripts/activate
       ```

       **Powershell** 中
       ```powershell
       .venv\Scripts\activate.ps1
       ```
       
       **Windows CMD** 中
       ```bat
       .venv\Scripts\activate.bat
       ```

    3. 安装依赖
   
       ```bash
       # 使用 pip (若安装太慢或失败, 可使用 `-i` 指定镜像源)
       pip3 install -U pip && pip3 install -r requirements.txt
       # 或者使用 uv (可使用 `--index` 指定镜像源)
       uv sync
       # 或者
       uv pip sync requirements.txt
       ```

  - :x: 在系统 Python 环境中安装 (不推荐)
  
    ```bash
    pip3 install -U pip && pip3 install -r requirements.txt
    ```

</details>

<details>

  <summary>如果未安装 <b>Python>=3.10</b> 环境</summary>

  你可以使用 [**uv**](https://github.com/astral-sh/uv) 安装依赖
   
  ```bash
  # uv 将使用 3.10 及以上的最新 python 发行版自动创建并使用虚拟环境, 可使用 --python 选项指定 python 版本, 参见 https://docs.astral.sh/uv/reference/cli/#uv-sync--python 和 https://docs.astral.sh/uv/reference/cli/#uv-pip-sync--python
  uv sync
  # 或
  uv pip sync requirements.txt
  ```

</details>

3.安装[FFmpeg](https://ffmpeg.org/download.html#build-linux)，如果是Windows系统，这一步可跳过。对于Linux系统，执行以下命令安装

CentOS执行

```bash
yum install epel-release
yum install ffmpeg
```

Ubuntu则执行

```bash
apt update
apt install ffmpeg
```

macOS 执行

**如果已经安装 Homebrew 请跳过这一步**

```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
```

```bash
brew install ffmpeg
```

4.运行程序

```python
python main.py

```
或

```bash
uv run main.py
```

其中Linux系统请使用`python3 main.py` 运行。

&emsp;
## 🐋容器运行

在运行命令之前，请确保您的机器上安装了 [Docker](https://docs.docker.com/get-docker/) 和 [Docker Compose](https://docs.docker.com/compose/install/) 

1.快速启动

最简单方法是运行项目中的 [docker-compose.yaml](https://github.com/ihmily/DouyinLiveRecorder/blob/main/docker-compose.yaml) 文件，只需简单执行以下命令：

```bash
docker-compose up
```

可选 `-d` 在后台运行。



2.构建镜像(可选)

如果你只想简单的运行程序，则不需要做这一步。Docker镜像仓库中代码版本可能不是最新的，如果要运行本仓库主分支最新代码，可以本地自定义构建，通过修改 [docker-compose.yaml](https://github.com/ihmily/DouyinLiveRecorder/blob/main/docker-compose.yaml) 文件，如将镜像名修改为 `douyin-live-recorder:latest`，并取消 `# build: .` 注释，然后再执行

```bash
docker build -t douyin-live-recorder:latest .
docker-compose up
```

或者直接使用下面命令进行构建并启动

```bash
docker-compose -f docker-compose.yaml up
```



3.停止容器实例

```bash
docker-compose stop
```



4.注意事项

①在docker容器内运行本程序之前，请先在配置文件中添加要录制的直播间地址。

②在容器内时，如果手动中断容器运行停止录制，会导致正在录制的视频文件损坏！

**无论哪种运行方式，为避免手动中断或者异常中断导致录制的视频文件损坏的情况，推荐使用 `ts` 格式保存**。

&emsp;

## 🤖相关项目

- StreamCap: https://github.com/ihmily/StreamCap
- streamget: https://github.com/ihmily/streamget

&emsp;

## ❤️贡献者

&ensp;&ensp; [![Hmily](https://github.com/ihmily.png?size=50)](https://github.com/ihmily)
[![iridescentGray](https://github.com/iridescentGray.png?size=50)](https://github.com/iridescentGray)
[![annidy](https://github.com/annidy.png?size=50)](https://github.com/annidy)
[![wwkk2580](https://github.com/wwkk2580.png?size=50)](https://github.com/wwkk2580)
[![missuo](https://github.com/missuo.png?size=50)](https://github.com/missuo)
<a href="https://github.com/xueli12" target="_blank"><img src="https://github.com/xueli12.png?size=50" alt="xueli12" style="width:53px; height:51px;" /></a>
<a href="https://github.com/kaine1973" target="_blank"><img src="https://github.com/kaine1973.png?size=50" alt="kaine1973" style="width:53px; height:51px;" /></a>
<a href="https://github.com/yinruiqing" target="_blank"><img src="https://github.com/yinruiqing.png?size=50" alt="yinruiqing" style="width:53px; height:51px;" /></a>
<a href="https://github.com/Max-Tortoise" target="_blank"><img src="https://github.com/Max-Tortoise.png?size=50" alt="Max-Tortoise" style="width:53px; height:51px;" /></a>
[![justdoiting](https://github.com/justdoiting.png?size=50)](https://github.com/justdoiting)
[![dhbxs](https://github.com/dhbxs.png?size=50)](https://github.com/dhbxs)
[![wujiyu115](https://github.com/wujiyu115.png?size=50)](https://github.com/wujiyu115)
[![zhanghao333](https://github.com/zhanghao333.png?size=50)](https://github.com/zhanghao333)
<a href="https://github.com/gyc0123" target="_blank"><img src="https://github.com/gyc0123.png?size=50" alt="gyc0123" style="width:53px; height:51px;" /></a>

&ensp;&ensp; [![HoratioShaw](https://github.com/HoratioShaw.png?size=50)](https://github.com/HoratioShaw)
[![nov30th](https://github.com/nov30th.png?size=50)](https://github.com/nov30th)
[![727155455](https://github.com/727155455.png?size=50)](https://github.com/727155455)
[![nixingshiguang](https://github.com/nixingshiguang.png?size=50)](https://github.com/nixingshiguang)
[![1411430556](https://github.com/1411430556.png?size=50)](https://github.com/1411430556)
[![Ovear](https://github.com/Ovear.png?size=50)](https://github.com/Ovear)
&emsp;

## ⏳提交日志

- 20251024
  - 修复抖音风控无法获取数据问题
  
  - 新增soop.com录制支持
  
  - 修复bigo录制
  
- 20250127
  - 新增淘宝、京东、faceit直播录制
  - 修复小红书直播流录制以及转码问题
  - 修复畅聊、VV星球、flexTV直播录制
  - 修复批量微信直播推送
  - 新增email发送ssl和port配置
  - 新增强制转h264配置
  - 更新ffmpeg版本
  - 重构包为异步函数！

- 20241130
  - 新增shopee、youtube直播录制
  - 新增支持自定义m3u8、flv地址录制
  - 新增自定义执行脚本，支持python、bat、bash等
  - 修复YY直播、花椒直播和小红书直播录制
  - 修复b站标题获取错误
  - 修复log日志错误
- 20241030
  - 新增嗨秀直播、vv星球直播、17Live、浪Live、SOOP、畅聊直播(原时光直播)、飘飘直播、六间房直播、乐嗨直播、花猫直播等10个平台直播录制
  - 修复小红书直播录制，支持小红书作者主页地址录制直播
  - 新增支持ntfy消息推送，以及新增支持批量推送多个地址（逗号分隔多个推送地址)
  - 修复Liveme直播录制、twitch直播录制
  - 新增Windows平台一键停止录制VB脚本程序
- 20241005
  - 新增邮箱和Bark推送
  - 新增直播注释停止录制
  - 优化分段录制
  - 重构部分代码
- 20240928
  - 新增知乎直播、CHZZK直播录制
  - 修复音播直播录制
- 20240903
  - 新增抖音双屏录制、音播直播录制
  - 修复PandaTV、bigo直播录制
- 20240713
  - 新增映客直播录制
- 20240705
  - 新增时光直播录制
- 20240701
  - 修复虎牙直播录制2分钟断流问题
  - 新增自定义直播推送内容
- 20240621
  - 新增Acfun、ShowRoom直播录制
  - 修复微博录制、新增直播源线路
  - 修复斗鱼直播60帧录制
  - 修复酷狗直播录制
  - 修复TikTok部分无法解析直播源
  - 修复抖音无法录制连麦直播
- 20240510
  - 修复部分虎牙直播间录制错误
- 20240508
  - 修复花椒直播录制
  - 更改文件路径解析方式 [@kaine1973](https://github.com/kaine1973)
- 20240506
  - 修复抖音录制画质解析bug
  - 修复虎牙录制 60帧最高画质问题
  - 新增流星直播录制
- 20240427
  - 新增LiveMe、花椒直播录制
- 20240425
  - 新增TwitchTV直播录制
- 20240424
  - 新增酷狗直播录制、优化PopkonTV直播录制
- 20240423
  - 新增百度直播录制、微博直播录制
  - 修复斗鱼录制直播回放的问题
  - 新增直播源地址显示以及输出到日志文件设置
- 20240311
  - 修复海外平台录制bug，增加画质选择，增强录制稳定性
  - 修复虎牙录制bug (虎牙`一起看`频道 有特殊限制，有时无法录制)
- 20240309
  - 修复虎牙直播、小红书直播和B站直播录制
  - 新增5个直播平台录制，包括winktv、flextv、look、popkontv、twitcasting
  - 新增部分海外平台账号密码配置，实现自动登录并更新配置文件中的cookie
  - 新增自定义配置需要使用代理录制的平台
  - 新增只推送开播消息不进行录制设置
  - 修复了一些bug
- 20240209
  - 优化AfreecaTV录制，新增账号密码登录获取cookie以及持久保存
  - 修复了小红书直播因官方更新直播域名，导致无法录制直播的问题
  - 修复了更新URL配置文件的bug
  - 最后，祝大家新年快乐！

<details><summary>点击展开更多提交日志</summary>

- 20240129
  - 新增猫耳FM直播录制
- 20240127
  - 新增千度热播直播录制、新增pandaTV(韩国)直播录制
  - 新增telegram直播状态消息推送，修复了某些bug
  - 新增自定义设置不同直播间的录制画质(即每个直播间录制画质可不同)
  - 修改录制视频保存路径为 `downloads` 文件夹，并且分平台进行保存。
- 20240114
  - 新增网易cc直播录制，优化ffmpeg参数，修改AfreecaTV输入直播地址格式
  - 修改日志记录器 @[iridescentGray](https://github.com/iridescentGray)
- 20240102
  - 修复Linux上运行，新增docker配置文件
- 20231210
  - 修复录制分段bug，修复bigo录制检测bug
  - 新增自定义修改录制主播名
  - 新增AfreecaTV直播录制，修复某些可能会发生的bug
- 20231207
  - 新增blued直播录制，修复YY直播录制，新增直播结束消息推送
- 20231206
  - 新增bigo直播录制
- 20231203
  - 新增小红书直播录制（全网首发），目前小红书官方没有切换清晰度功能，因此直播录制也只有默认画质
  - 小红书录制暂时无法循环监测，每次主播开启直播，都要重新获取一次链接
  - 获取链接的方式为 将直播间转发到微信，在微信中打开后，复制页面的链接。
- 20231030
  - 本次更新只是进行修复，没时间新增功能。
  - 欢迎各位大佬提pr 帮忙更新维护
- 20230930
  - 新增抖音从接口获取直播流，增强稳定性
  - 修改快手获取直播流的方式，改用从官方接口获取
  - 祝大家中秋节快乐！
- 20230919
  - 修复了快手版本更新后录制出错的问题，增加了其自动获取cookie(~~稳定性未知~~)
  - 修复了TikTok显示正在直播但不进行录制的问题
- 20230907
  - 修复了因抖音官方更新了版本导致的录制出错以及短链接转换出错
  - 修复B站无法录制原画视频的bug
  - 修改了配置文件字段，新增各平台自定义设置Cookie
- 20230903
  - 修复了TikTok录制时报644无法录制的问题
  - 新增直播状态推送到钉钉和微信的功能，如有需要请看 [设置推送教程](https://d04vqdiqwr3.feishu.cn/docx/XFPwdDDvfobbzlxhmMYcvouynDh?from=from_copylink)
  - 最近比较忙，其他问题有时间再更新
- 20230816
  - 修复斗鱼直播（官方更新了字段）和快手直播录制出错的问题
- 20230814
  - 新增B站直播录制
  - 写了一个在线播放M3U8和FLV视频的网页源码，打开即可食用
- 20230812
  - 新增YY直播录制
- 20230808
  - 修复主播重新开播无法再次录制的问题
- 20230807
  - 新增了斗鱼直播录制
  - 修复显示录制完成之后会重新开始录制的问题
- 20230805
  - 新增了虎牙直播录制，其暂时只能用flv视频流进行录制
  - Web API 新增了快手和虎牙这两个平台的直播流解析（TikTok要代理）
- 20230804
  - 新增了快手直播录制，优化了部分代码
  - 上传了一个自动化获取抖音直播间页面Cookie的代码，可以用于录制
- 20230803
  - 通宵更新 
  - 新增了国际版抖音TikTok的直播录制，去除冗余 简化了部分代码
- 20230724	
  - 新增了一个通过抖音直播间地址获取直播视频流链接的API接口，上传即可用
  </details>
  &emsp;

## 有问题可以提issue, 我会在这里持续添加更多直播平台的录制 欢迎Star
#### 
