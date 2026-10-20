# StrmAction Desktop（Windows / macOS）

StrmAction 桌面端是 **WebView 外壳 + 本机 mpv 播放代理**：

- 网页、登录、媒体库、详情、设置全部复用服务端现有 Web UI；
- Python 不保存账号密码，也不读取网页 Cookie；
- 网页点播放后，把 `/api/play` 返回的播放数据交给 Python；
- Python 启动**本机 mpv**（独立播放窗口），自动设置服务端下发的全部请求头；
- 播放进度通过现有 `/api/items/{id}/progress` 接口上报，使用 item 级 `play_token`。

> 本机使用 `uv` 管理 Python 环境。下面命令默认都从 `desktop/` 目录执行。
>
> 完整开发/验收清单见 [`CHECKLIST.md`](CHECKLIST.md)。

---

## 目录

1. [它是什么 / 不是什么](#1-它是什么--不是什么)
2. [工作原理](#2-工作原理)
3. [环境要求](#3-环境要求)
4. [快速开始（源码运行）](#4-快速开始源码运行)
5. [第一次启动](#5-第一次启动)
6. [mpv 配置（重点）](#6-mpv-配置重点)
7. [配置与日志位置](#7-配置与日志位置)
8. [命令行参数](#8-命令行参数)
9. [播放、进度、字幕与多版本](#9-播放进度字幕与多版本)
10. [构建安装包](#10-构建安装包)
11. [安全说明](#11-安全说明)
12. [测试](#12-测试)
13. [故障排查](#13-故障排查)
14. [已知限制](#14-已知限制)
15. [目录结构](#15-目录结构)
16. [FAQ](#16-faq)

---

## 1. 它是什么 / 不是什么

### 是什么

- 一个 Windows / macOS 桌面程序，名字和图标都是 **StrmAction**；
- 用 WebView 打开你的 StrmAction 服务器网页；
- 网页负责登录、选片、详情、搜索、设置；
- Python 只负责“本机 mpv 播放”和“进度回传”。

### 不是什么

- **不是** 另一套媒体库客户端。桌面端没有自己的媒体库页面，所有浏览都在网页里完成；
- **不是** 视频下载器。播放 URL 直接交给本机 mpv，服务端不代理视频流；
- **不是** 把 mpv 画面嵌进 StrmAction 主窗口。mpv 是独立播放窗口（这是当前方案的明确选择）；
- **不是** `pip install mpv`。Python 的 `mpv` 包只是控制库；真正的播放器是 `mpv.exe` / `mpv` 可执行文件；
- **不是** 手机伴侣 App 的替代品。手机/电视仍用 `companion/` 里的 Android App。

---

## 2. 工作原理

```text
┌──────────────────────────────────────────────┐
│ StrmAction.exe / StrmAction.app（Python）     │
│                                              │
│  WebView                                     │
│    加载 https://你的服务器/                   │
│    登录、媒体库、详情、设置都复用网页          │
│         │                                    │
│         │ window.StrmActionNative.playItem() │
│         ▼                                    │
│  Python 播放代理                             │
│    - 校验 /api/play 返回的 payload            │
│    - 查找本机 mpv                            │
│    - 通过 IPC 设置 headers / 字幕 / 续播位置  │
│    - 监听播放进度                             │
│    - 用 play_token 上报进度                   │
└──────────────┬───────────────────────────────┘
               │ HTTPS
               ▼
        StrmAction 服务端
        /api/play  mode=direct
        /api/items/{id}/progress
```

一次点击播放的完整流程：

1. 网页登录，Cookie 留在 WebView；
2. 用户点播放；
3. 前端发现 `window.StrmActionNative.isDesktop() === true`；
4. 前端请求：

   ```http
   POST /api/play/42
   Content-Type: application/json

   { "mode": "direct", "media_file_id": 7 }
   ```

5. 服务端返回：

   ```json
   {
     "mode": "direct",
     "play_url": "https://pan.example.com/...",
     "headers": {
       "User-Agent": "pan.baidu.com",
       "Referer": "https://pan.baidu.com/"
     },
     "play_token": "pt_...",
     "resume_ms": 12000,
     "progress_interval_ms": 5000,
     "subtitles": [
       { "label": "简体", "url": "/api/items/42/subtitles/0?pt=pt_..." }
     ],
     "media_file_id": 7
   }
   ```

6. 前端通过 JS Bridge 执行：

   ```js
   window.StrmActionNative.playItem(JSON.stringify(payload))
   ```

7. Python 校验 payload，找到 mpv，启动进程；
8. Python 通过 mpv JSON IPC：
   - 设置完整 `http-header-fields`；
   - 从 `resume_ms` 续播；
   - 加载字幕；
9. Python 监听 `time-pos / duration / pause / eof-reached`；
10. 按 `progress_interval_ms` 上报，暂停/seek/退出/播完立即补写。

> Python 不需要自己登录，也不需要拿网页 Cookie。播放鉴权由网页完成，Python 只使用 payload 里的 `play_token` 上报进度。

---

## 3. 环境要求

| 项目 | 要求 |
|---|---|
| Python | 3.10+ |
| 包管理 | [uv](https://docs.astral.sh/uv/) |
| Windows | Windows 10/11；需要 WebView2 Runtime（Win11 通常自带） |
| macOS | macOS 11+；使用系统 WKWebView |
| 服务端 | 必须支持 `direct` 播放模式（本仓库当前版本已包含） |
| mpv | 可用系统已安装的 mpv；正式分发建议打包时自带 |

服务端还需要：

- 已更新到包含 `direct` 模式的版本；
- 前端 `frontend/dist` 已重新构建（网页里的桌面桥分支需要最新前端）。

---

## 4. 快速开始（源码运行）

### 4.1 创建环境

```bash
cd desktop
uv venv
uv pip install -e ".[dev]"
```

### 4.2 启动

```bash
uv run strmaction-desktop
```

等价写法：

```bash
uv run python -m strmaction_desktop
```

### 4.3 直接指定服务器 / mpv

```bash
uv run strmaction-desktop --server https://media.example.com
uv run strmaction-desktop --mpv "C:\tools\mpv\mpv.exe"
uv run strmaction-desktop --server http://192.168.1.10:8080 --mpv "/usr/local/bin/mpv"
```

### 4.4 只打开桌面端设置

```bash
uv run strmaction-desktop --settings
```

### 4.5 调试

```bash
uv run strmaction-desktop --debug
```

`--debug` 会开启调试日志和 WebView 调试；日志仍然不会记录播放 URL/headers/token。

---

## 5. 第一次启动

首次启动没有服务器地址，会自动打开 **桌面端设置页**：

1. 填服务器地址，例如 `https://media.example.com`；
   - 必须带 `http://` 或 `https://`；
   - 结尾的 `/` 可省略；
2. 填 mpv 路径，或让它自动检测；
   - 留空时按“配置 → 自带 → PATH → 常见安装路径”查找；
3. 点「保存并打开」；
4. 进入网页登录。

之后要改服务器地址 / mpv 路径：

- 网页「设置 → 我的播放方式 → 打开桌面端设置」；
- 或命令行 `uv run strmaction-desktop --settings`。

---

## 6. mpv 配置（重点）

### 6.1 三种使用方式

| 方式 | 适合场景 | 用户是否需要装 mpv | 做法 |
|---|---|---|---|
| A. 使用系统已安装的 mpv | 开发、个人使用 | 是 | 装 mpv，留空配置让它自动找 |
| B. 打包时自带 mpv | 正式分发给别人 | **否** | `scripts/prepare_mpv.py` + 重新构建 |
| C. 手动指定 mpv 路径 | 自定义位置 | 是 | 设置页选择，或 `--mpv` |

### 6.2 “打包时自带 mpv”是什么意思

这句话的意思是：

> **在打 EXE / .app 之前，把一份 mpv 可执行文件放进 `desktop/vendor/mpv/<平台>/`，让 PyInstaller 一起打进安装包。这样用户拿到安装包后不需要自己安装 mpv。**

`scripts/prepare_mpv.py` 只是一个“搬运工”，**不会联网下载 mpv**：

```text
你本机已有的 mpv 目录
        ↓  prepare_mpv.py 复制
desktop/vendor/mpv/windows-x64/
        ↓  PyInstaller 打包
desktop/dist/StrmAction/_internal/vendor/mpv/windows-x64/
        ↓  运行时
桌面端优先使用这个自带 mpv
```

Windows 示例：

```powershell
cd desktop
uv run python scripts/prepare_mpv.py --source C:\tools\mpv
.\scripts\build_windows.ps1
```

macOS 示例：

```bash
cd desktop
uv run python scripts/prepare_mpv.py --source /Applications/mpv.app
./scripts/build_macos.sh
```

`--source` 可以是：

- Windows：包含 `mpv.exe` 和 DLL 的**目录**（推荐）；
- macOS：`mpv.app`，或单个 `mpv` 可执行文件；
- 已经是某个 mpv 可执行文件路径也可以，但 Windows 请用目录形式，避免漏 DLL。

目录约定：

```text
desktop/vendor/mpv/
├── windows-x64/
│   ├── mpv.exe
│   └── *.dll
├── windows-arm64/
│   └── mpv.exe
├── macos-arm64/
│   └── mpv            # 或 mpv.app/Contents/MacOS/mpv
└── macos-x64/
    └── mpv
```

不提交到仓库的原因：

- 体积大；
- mpv 通常使用 GPL 许可证，再分发需要确认许可证义务；
- 不同平台/架构需要不同二进制。

仓库只保留 `vendor/mpv/README.md` 和准备脚本；二进制由构建机准备。

### 6.3 如何确认“自带 mpv”生效

构建后检查：

```text
desktop/dist/StrmAction/_internal/vendor/mpv/windows-x64/mpv.exe
```

或启动桌面端，在设置页看「已找到：...」。

注意：**配置里的 `mpv_path` 优先级高于自带 mpv**。如果你之前手动保存过 mpv 路径，想改用自带 mpv，请在设置页把 mpv 路径清空再保存。

### 6.4 查找顺序

1. 配置里的 `mpv_path`；
2. 自带：`vendor/mpv/<platform>/mpv[.exe]`（macOS 也支持 `mpv.app`）；
3. 系统 `PATH`；
4. 常见安装路径：
   - macOS：`/Applications/mpv.app/Contents/MacOS/mpv`、`/opt/homebrew/bin/mpv`、`/usr/local/bin/mpv`
   - Windows：`C:\Program Files\mpv\mpv.exe`、`%LOCALAPPDATA%\Programs\mpv\mpv.exe`

找不到时，播放会返回明确错误；可在设置页手动选择。

### 6.5 常见误区

- **“自带 mpv”不是把视频画面嵌进 StrmAction 主窗口**；仍然是独立 mpv 窗口。
- **不是 `pip install mpv`**；Python 的 `mpv` 包只是控制/绑定库，不是播放器。
- **当前 `desktop/dist/StrmAction` 里的 Windows exe 没有内置 mpv**，因为本机没有 mpv 二进制；它依赖系统已安装的 mpv。要自带，按 6.2 准备后重新构建。
- 自带 mpv 仍然受 mpv 许可证约束；正式发布前请确认 GPL/第三方许可证义务。

---

## 7. 配置与日志位置

| 项目 | Windows | macOS |
|---|---|---|
| 配置 | `%APPDATA%\StrmAction\config.json` | `~/Library/Application Support/StrmAction/config.json` |
| 日志 | `%APPDATA%\StrmAction\logs\desktop.log` | `~/Library/Application Support/StrmAction/logs/desktop.log` |
| WebView Cookie/存储 | `%APPDATA%\StrmAction\webview\` | `~/Library/Application Support/StrmAction/webview/` |

配置只保存：

- `server_url`
- `mpv_path`
- 窗口尺寸
- 日志级别

不保存密码、Cookie、播放 URL、请求头或 `play_token`。

---

## 8. 命令行参数

```text
--server URL     设置并保存服务器地址
--mpv PATH       设置并保存 mpv 路径
--settings       启动后直接打开桌面端设置
--debug          调试日志 + WebView 调试
--version        输出版本号
```

示例：

```bash
uv run strmaction-desktop --version
uv run strmaction-desktop --settings
uv run strmaction-desktop --server https://media.example.com
```

---

## 9. 播放、进度、字幕与多版本

### 请求头

服务端下发的 `headers` 会**全量**设置给 mpv，不只 User-Agent：

- `User-Agent`
- `Referer`
- `Cookie`（如果管理员配置了）
- 其他网盘需要的字段

通过 mpv IPC 设置，不放在命令行参数里，避免被同机其他进程从进程列表看到。

### 进度

- 使用 `play_token` 作为 Bearer；
- 默认按服务端 `progress_interval_ms`（一般 5 秒）上报；
- 暂停、seek、退出、播完立即补写；
- 单飞上传，失败保留最新位置重试；
- 90% 自动标记已看；
- `play_token` 过期/401 时停止上报并写日志；重新从网页打开播放即可。

### 字幕

服务端返回的 `subtitles[].url` 会拼成绝对地址，通过 mpv `sub-add` 加载；第一个默认选中，其余 `auto`。

### 多版本

网页详情页选择版本后，`media_file_id` 会随 payload 传给服务端，`direct` 响应按该版本返回；桌面端不需要自己选版本。

### 自动下一集

暂未实现。服务端返回的 `next_item_id / playlist` 已保留，后续可扩展。

---

## 10. 构建安装包

### 10.1 Windows

```powershell
cd desktop
.\scripts\build_windows.ps1
```

产物：

```text
desktop\dist\StrmAction\StrmAction.exe
desktop\dist\StrmAction\_internal\...
```

脚本会：

1. 用 uv 准备 `.venv`；
2. 安装依赖；
3. 生成图标；
4. 检查对应平台的 `vendor\mpv\<platform>`（有就一起打包，没有会提示）；
5. 调 PyInstaller。

正式分发建议：

- 先准备 `vendor/mpv/windows-x64/`；
- 代码签名，减少 SmartScreen 提示；
- 目标机器有 WebView2 Runtime（Win11 自带，Win10 可能需要安装）。

### 10.2 macOS

```bash
cd desktop
./scripts/build_macos.sh
```

产物：

```text
desktop/dist/StrmAction.app
```

正式分发需要：

- Apple Developer ID；
- `codesign` + `notarytool` 公证；
- 如打包 mpv，确认 GPL/第三方许可证合规。

示例：

```bash
codesign --deep --force --options runtime \
  --sign "Developer ID Application: Your Name (TEAMID)" \
  dist/StrmAction.app

ditto -c -k --keepParent dist/StrmAction.app dist/StrmAction.zip
xcrun notarytool submit dist/StrmAction.zip --wait ...
```

> 当前开发环境是 Windows，macOS 构建/公证未实际执行；脚本和 spec 已准备好。

### 10.3 图标

`src/strmaction_desktop/assets/icon.svg` 来自网站 favicon；已生成：

- `icon.png`（窗口/设置页）
- `icon.ico`（Windows）
- `icon.icns`（macOS）

重新生成：

```bash
uv run python scripts/make_icons.py
```

---

## 11. 安全说明

- 不保存账号密码、网页会话 Cookie；
- 播放 URL、headers、`play_token` 都是凭证：
  - 不写日志；
  - 不落盘；
  - 不放进命令行参数；
- headers 通过 mpv IPC 设置；
- IPC 使用随机命名管道（Windows）或权限 0700 的 Unix socket（macOS）；
- WebView 只允许加载配置的服务器地址和本地设置页；
- JS Bridge 只接受合法 payload，不执行任意命令；
- 生产环境请使用 HTTPS；自签名证书需要显式信任（后续可加指纹信任）；
- 日志中的 URL 会脱敏。

---

## 12. 测试

```bash
cd desktop
uv run pytest -q
```

当前覆盖：

- 配置校验/窗口尺寸；
- payload 校验与脱敏；
- mpv 查找顺序/header 格式化；
- 进度上报：payload、90% 已看、401、500 重试、client_key；
- JS Bridge 错误处理；
- WebView 导航 origin 限制；
- 桌面桥注入脚本。

服务端测试：

```bash
cd ../backend
..\.venv\Scripts\python.exe -m pytest -q     # Windows
```

前端构建：

```bash
cd ../frontend
npm run build
```

---

## 13. 故障排查

| 现象 | 原因/处理 |
|---|---|
| `ModuleNotFoundError: pywebview` | `uv pip install -r requirements.txt` 或 `uv pip install -e ".[dev]"` |
| 启动白屏 / 页面空白 | 检查服务器地址；Windows 安装 WebView2 Runtime；确认服务器可访问 |
| `未找到 mpv` | 设置页选择 mpv；或运行 `scripts/prepare_mpv.py`；或安装 mpv |
| 自带 mpv 没生效 | 配置里的 `mpv_path` 优先；清空它再保存 |
| 播放黑屏 / 403 | 检查服务端 `headers` 是否正确；确认网盘 URL 未过期 |
| 进度不更新 | 看 `desktop.log`；`play_token` 可能过期；重新从网页打开播放 |
| macOS 打不开 | 未公证会被 Gatekeeper 拦截；开发期右键打开，正式分发做公证 |
| 打包后找不到 assets | 必须在 `desktop/` 目录执行 `packaging/strmaction-desktop.spec` |
| PyInstaller 报 `script not found` | 从 `desktop/` 根目录运行，不要从 `packaging/` 里运行 |
| `uv` 命令不存在 | 安装 uv，或改用系统 Python + pip（不推荐） |
| 启动后没有桌面提示 | 确认服务端前端已更新；桌面桥在页面加载后注入 |

日志位置见第 7 节。

---

## 14. 已知限制

- 播放窗口是**独立 mpv 窗口**，暂不把视频画面嵌入 StrmAction 主窗口；
- 不依赖用户安装 mpv 时，需要构建前自带 mpv；
- 当前构建产物默认不带 mpv（仓库不提交二进制）；
- `play_token` 默认 12 小时；超长暂停后可能需要重新从网页打开；
- 暂不支持自动下一集/播放列表续播；
- 托盘常驻、开机自启、自动更新暂未实现；
- macOS 公证/Windows 代码签名需要发布者证书；
- 目前只准备 Windows/macOS 打包，Linux 未验证。

---

## 15. 目录结构

```text
desktop/
├── README.md
├── CHECKLIST.md                开发/验收清单
├── pyproject.toml
├── requirements.txt
├── requirements-dev.txt
├── uv.lock
├── run_desktop.py              PyInstaller 入口
├── src/strmaction_desktop/
│   ├── app.py                  WebView 窗口、桥注入、生命周期
│   ├── bridge.py               window.pywebview.api
│   ├── config.py               配置目录/读写
│   ├── mpv.py                  mpv 查找、启动、IPC
│   ├── playback.py             播放会话（mpv + 进度）
│   ├── progress.py             进度上报
│   ├── security.py             payload 校验/脱敏
│   ├── logging_setup.py
│   ├── version.py
│   └── assets/
│       ├── settings.html
│       ├── icon.svg / png / ico / icns
├── scripts/
│   ├── prepare_mpv.py          把 mpv 复制到 vendor/
│   ├── make_icons.py
│   ├── build_windows.ps1
│   └── build_macos.sh
├── packaging/
│   └── strmaction-desktop.spec
├── tests/
└── vendor/mpv/README.md        二进制目录约定（由构建机准备）
```

---

## 16. FAQ

### Q1：“推荐打包时自带（`scripts/prepare_mpv.py`）”到底是什么意思？

意思是：**在构建 EXE/.app 之前，把 mpv 可执行文件复制到 `vendor/mpv/<平台>/`，让 PyInstaller 一起打包**。这样最终用户不需要自己安装 mpv。`prepare_mpv.py` 只复制，不下载。

### Q2：自带 mpv 是不是把视频画面嵌进 StrmAction 窗口？

不是。当前方案是 **自带 mpv 二进制 + 独立播放窗口**。把画面嵌进主窗口需要 Qt/libmpv，属于另一个量级的改造。

### Q3：用户必须安装 mpv 吗？

- 如果构建时自带了 mpv：不需要；
- 如果没自带：需要系统已安装 mpv，或在设置页手动指定路径。

### Q4：为什么仓库里没有 `mpv.exe`？

体积大、平台/架构不同、许可证/再分发义务需要按发布方式确认。仓库只提供准备脚本和目录约定，二进制由构建机放入。

### Q5：可以 `pip install mpv` 吗？

不建议把它当成播放器。`mpv` PyPI 包只是控制库；真正播放仍需 `mpv` 可执行文件。本项目直接调 mpv 进程 + JSON IPC，所以不需要这个 Python 包。

### Q6：桌面端设置页里的“我的播放方式”对桌面端生效吗？

不生效。桌面端固定走 `direct` + 本机 mpv；该偏好只影响网页和伴侣 App。设置页会显示“当前为桌面端”的提示。

### Q7：支持 Linux 吗？

源码理论上可运行，但当前只准备 Windows/macOS 的打包与验证；Linux 未测试。

### Q8：能自动下一集吗？

暂不支持。播放响应里的 `next_item_id / playlist` 已保留，后续可以扩展。

### Q9：播放进度存在哪里？

服务端数据库的 `play_progress` 表，按用户隔离；桌面端只负责上报，不本地保存播放历史。

### Q10：桌面端会保存我的密码吗？

不会。登录在 WebView 内完成，Python 不接触密码，也不读取网页 Cookie。
