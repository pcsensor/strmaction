# StrmAction Desktop（Windows / macOS）

StrmAction 桌面端是 **PySide6 现代桌面应用（Web 浏览 + 原生硬件加速内嵌播放器 + 仿安卓伴侣 App 自制控件）**：

- 网页、登录、媒体库、详情、设置全部复用服务端现有 Web UI；
- 点击播放后，直接在主窗口**无缝切换为内嵌播放器（零外部弹窗，无需安装或打包任何播放器）**；
- 播放控件 1:1 对齐安卓伴侣 App（三层缓冲进度条、40% 侧滑选集/倍速/音轨抽屉、长按倍速、中心反馈）；
- 具备完整的**键鼠操作体系**（空格播放/暂停、方向键调进度、长按右方向键 2.0x 倍速、滚轮选集等）；
- 内嵌 libmpv 内核，把服务端下发的防盗链请求头（`User-Agent` 与 `Referer`）注入到每个 HTTP 请求，302 跨域重定向后依旧保持，绝不报 403；
- 播放进度通过现有 `/api/items/{id}/progress` 接口以 5 秒心跳上报，使用 item 级 `play_token`。

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
6. [配置与日志位置](#6-配置与日志位置)
7. [命令行参数](#7-命令行参数)
8. [播放、进度、字幕与多版本](#8-播放进度字幕与多版本)
9. [构建安装包](#9-构建安装包)
10. [安全说明](#10-安全说明)
11. [测试](#11-测试)
12. [故障排查](#12-故障排查)
13. [已知限制](#13-已知限制)
14. [目录结构](#14-目录结构)
15. [FAQ](#15-faq)

---

## 1. 它是什么 / 不是什么

### 是什么

- 一个 Windows / macOS 原生桌面程序，名字和图标都是 **StrmAction**；
- 浏览态使用 WebEngine 打开你的 StrmAction 服务器网页，负责登录、选片、详情、搜索；
- 播放态直接在窗口内部呈现**内嵌播放器**，搭配仿伴侣 App 的自制交互控件与全套键盘快捷控制；
- 底层调度操作系统原生硬件加速（Windows Direct3D / macOS Metal），并通过本地代理严格透传防盗链请求头与 5 秒心跳进度上报；
- **完全开箱即用**：零外部播放器依赖，无需手动选择或配置任何播放器路径。

### 不是什么

- **不是** 另一套媒体库客户端。桌面端没有自己的媒体库页面，所有浏览都在网页里完成；
- **不是** 视频下载器。服务端不代理视频大流量；
- **不是** 粗糙的独立悬浮弹窗。播放器与自制控件完全内嵌在桌面端主窗口；
- **不是** 外挂第三方播放器。纯 PySide6 原生播放架构，免去外部二进制文件与路径配置；
- **不是** 手机伴侣 App 的替代品。手机/电视仍用 `companion/` 里的 Android App。

---

## 2. 工作原理

```text
┌──────────────────────────────────────────────────────────────┐
│ StrmAction 桌面端（PySide6 主窗口）                           │
│ ┌──────────────────────────────────────────────────────────┐ │
│ │ QStackedWidget                                           │ │
│ │ ├─ Page 0: QWebEngineView (复用服务器完整 Web UI)        │ │
│ │ │   - 网页浏览、媒体库、详情页、搜索与用户设置           │ │
│ │ │   - 注入 QWebChannel 与 window.StrmActionNative 桥接   │ │
│ │ │        │                                               │ │
│ │ │        │ 用户点击播放 / window.StrmActionNative.playItem│ │
│ │ │        ▼                                               │ │
│ │ └─ Page 1: PlayerView (原生硬件加速内嵌播放视图)         │ │
│ │     ├── MpvVideoWidget (OpenGL FBO 渲染, 由 Qt 合成)      │ │
│ │     ├── ControlsOverlay (仿伴侣 App 顶栏、底栏、反馈徽标) │ │
│ │     │    ├── BufferedSeekBar (平滑三层缓冲进度条)        │ │
│ │     │    ├── 半透明顶部倍速指示胶囊 (不遮挡主体画面)     │ │
│ │     │    └── 3.5s 无操作自动隐藏控制栏与鼠标光标        │ │
│ │     ├── PlayerDrawer (右侧 40% 抽屉: 选集高亮/倍速/音轨) │ │
│ │     └── KeyboardHandler (按键状态机: 空格/长按右键倍速等)│ │
│ └──────────────┬───────────────────────────────────────────┘ │
└────────────────┼─────────────────────────────────────────────┘
                 │ 5秒心跳进度上报 (play_token)
                 ▼
          StrmAction 服务端
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

7. Python 校验 payload，把 CDN 直链与 headers 直接交给内嵌的 libmpv 播放内核；
8. libmpv 负责解码与渲染：
   - `http-header-fields` 让每个 HTTP 请求（含 302 跳转后、HLS 分片、Range 请求）都携带服务端下发的 `User-Agent` / `Referer`，无需本地代理；
   - `loadfile` 原生支持 `resume_ms` 起播位置；
   - 硬解走 `hwdec=auto-safe`（Windows D3D11VA / macOS VideoToolbox），画面经 `MpvRenderContext` 渲染进 `QOpenGLWidget` 的 FBO；
9. 监听播放位置与状态，按 `progress_interval_ms` 向服务端上报进度，暂停/seek/退出/播完立即补写。

> Python 不需要自己登录，也不需要拿网页 Cookie。播放鉴权由网页完成，Python 只使用 payload 里的 `play_token` 上报进度。

---

## 3. 环境要求

| 项目 | 要求 |
|---|---|
| Python | 3.10+ |
| 包管理 | [uv](https://docs.astral.sh/uv/) |
| Windows | Windows 10/11；DirectX 11+（用于原生视频硬解） |
| macOS | macOS 11+；Metal 硬件加速 |
| 播放内核 | 内置 libmpv（`libmpv-2.dll`），随包分发，**用户无需安装任何播放器** |
| 服务端 | 必须支持 `direct` 播放模式（本仓库当前版本已包含） |

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

`libmpv-2.dll`（121 MB）不入库，首次需要拉取一次：

```bash
uv run python scripts/fetch_libmpv.py
```

没有它应用仍能启动，但会回退到 Qt Multimedia：请求头注入、外挂字幕、MKV 完整格式支持都会丢失，日志里会写明「未找到 libmpv」。

### 4.2 启动

```bash
uv run strmaction-desktop
```

等价写法：

```bash
uv run python -m strmaction_desktop
```

### 4.3 直接指定服务器地址

```bash
uv run strmaction-desktop --server https://media.example.com
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
2. 填「预读缓存上限（MB）」，默认 128；
3. 点「保存并打开」；
4. 进入网页登录。无需配置任何播放器路径，纯开箱即用。

之后要改服务器地址 / 缓存上限：

- 网页「设置 → 我的播放方式 → 打开桌面端设置」；
- 或命令行 `uv run strmaction-desktop --settings`。

---

## 6. 播放架构与请求头注入（重点）

### 6.1 libmpv 播放内核 + OpenGL 渲染

当前版本使用 **PySide6 外壳 + 内嵌 libmpv**（`player/mpv_engine.py`）：

- **内核随包分发**：`libmpv-2.dll` 打包在 `src/strmaction_desktop/vendor/libmpv/`，用户无需安装播放器、无需配置路径；
- **格式完整**：libmpv 用 FFmpeg 解复用，MKV / HEVC / DTS / TrueHD / ASS 特效与外挂字幕全部支持——这些正是 Qt Multimedia 覆盖不到的部分；
- **原生硬件加速**：`hwdec=auto-safe`，Windows 走 D3D11VA、macOS 走 VideoToolbox；
- **同源图层无黑屏**：画面经 `MpvRenderContext` 渲染进 `QOpenGLWidget` 的 FBO，由 Qt 自身合成，浮层控制栏 / 右侧抽屉 / 顶部胶囊按普通子控件绘制在视频之上——不是"修好了层级"，而是层级问题不复存在。

### 6.2 HTTP 请求头注入（不再需要本地代理）

百度网盘、Alist 与 CDN 直链通常严格要求 `User-Agent` 与 `Referer`，且普遍存在 302 跨域重定向。libmpv 用 `http-header-fields` 直接解决：

1. 网页点击播放时，桌面端接收 payload，把 `headers` 逐条写入 mpv 的 `http-header-fields`；
2. mpv 的 HTTP 层对**每一个**请求附加这些头：首个请求、302 之后的新 host、Range 重连、HLS 分片全部覆盖；
3. `Range` / `If-Range` 由 demuxer 原生管理，seek 直接发字节范围请求，没有重连握手的额外延迟；
4. 证书策略跟随桌面端「允许自签名 HTTPS」开关（`tls-verify`）。

> 早期版本这里是一个 290 行的 Python 环回代理（`proxy.py`）。它存在的唯一原因写在文件头注释里——"Qt Multimedia cannot attach per-request headers to a media source"。换内核后该子系统已整体删除。

验证方式：`scripts/mpv_ua_check.py` 会起一个本地服务器并返回 302，记录 mpv 在**直连与跳转后**两个请求上实际发出的请求头。

---

## 7. 配置与日志位置

| 项目 | Windows | macOS |
|---|---|---|
| 配置 | `%APPDATA%\StrmAction\config.json` | `~/Library/Application Support/StrmAction/config.json` |
| 日志 | `%APPDATA%\StrmAction\logs\desktop.log` | `~/Library/Application Support/StrmAction/logs/desktop.log` |
| WebView Cookie/存储 | `%APPDATA%\StrmAction\webview\` | `~/Library/Application Support/StrmAction/webview/` |

配置只保存：

- `server_url`
- `cache_limit_mb`（0 = 系统默认；非 0 按 16–2048MB）
- 窗口尺寸
- 日志级别

不保存密码、Cookie、播放 URL、请求头或 `play_token`。

---

## 8. 命令行参数

```text
--server URL     设置并保存服务器地址
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

## 9. 播放、自制控件、键盘控制与进度

### 9.1 请求头与防盗链（重点）

服务端下发的 `headers` 会全部写入 mpv 的 `http-header-fields`，不只 User-Agent：

- `User-Agent` 与 `Referer`；
- `Cookie` / `Authorization`（如果配置了网盘鉴权）；
- mpv 的 HTTP 层对每个请求附加这些头，**在 302 跨域重定向到百度网盘/Alist CDN 时，新 host 的请求同样携带**，绝不触发 403 Forbidden（可用 `scripts/mpv_ua_check.py` 复现验证）；
- 通过 libmpv 的属性接口设置，不经过命令行参数，不会出现在系统进程列表里。

### 9.2 仿安卓伴侣 App 自制控件体系

播放界面彻底告别独立弹窗，采用与安卓伴侣 App 1:1 对齐的现代自制 UI：

1. **顶栏（TopBar）**：
   - 渐变半透明黑遮罩；
   - 包含返回媒体库按钮、剧集全称与集数标题。
2. **三层缓冲进度条（BufferedSeekBar）**：
   - 8px 高度全圆角白色底轨（`#3DFFFFFF`）；
   - 金橙色已播放进度填充（`#F0A94D`）；
   - 2.5px 白色高亮网络缓冲线置顶压层（`#E8FFFFFF`，分段展示命中磁盘的预读区间）；
   - 3.5×16px 纯白竖胶囊播放滑块与鼠标悬停时间 Tooltip 预览；
   - 拖拽 Seek 期间保持平滑稳定，杜绝频繁闪烁。
3. **40% 侧滑抽屉（PlayerDrawer）**：
   - 点击底栏对应按钮或快捷键从右侧顺滑滑出，占据 40% 屏幕宽度（支持滚轮）；
   - 采用深黑毛玻璃底色（`#13161F`）与左侧 16px 圆角；
   - 包含 **“选集”**（网格列表、已看标识、`▶ 播放中` 金色高亮与图标）、**“倍速”**（0.5x~3.0x 多档选择）、**“音轨与字幕”**（多音轨选择与外挂/内嵌字幕切换及关闭）。
4. **反馈动效与自动隐藏**：
   - **长按倍速指示胶囊**：位于窗口正上方顶栏下方（Y≈70px 水平居中），采用高透明磨砂胶囊风格（`rgba(0, 0, 0, 0.45)` 配金色文字），绝不遮挡视频中央人物画面与字幕；
   - 屏幕中央提供大播放/暂停脉冲动画、`+5s` / `-5s` 快进退反馈徽标；
   - 播放过程中鼠标静止 3.5 秒自动隐藏顶底控制条与鼠标指针，并内置光标状态防抖节流，杜绝鼠标漂移与卡顿。

### 9.3 全套键盘快捷键与“长按倍速”状态机

桌面端实现了精准的按键去抖与状态机，完美解决系统级按键自动重复（Auto-Repeat）导致快进狂闪的难题：

| 按键 | 功能 | 画面反馈动效 |
|---|---|---|
| **`Space`** | 播放 / 暂停切换 | 屏幕中央闪烁半透明大播放/暂停图标 |
| **`Left`** | 快退 5 秒 | 屏幕中央显示 `⏪ -5s` 徽标 |
| **`Right`（短按）** | 快进 5 秒 | 屏幕中央显示 `⏩ +5s` 徽标 |
| **`Right`（长按 ≥250ms）** | **长按 2.0x 极速播放** | 屏幕中央显示 `⚡ 2.0x 极速播放中`，松开按键立即恢复原倍速 |
| **`Up` / `Down`** | 音量调节（±5%） | 浮层提示当前音量百分比 |
| **`M`** | 静音 / 取消静音 | 切换静音状态 |
| **`F` / `F11`** | 切换全屏 / 退出全屏 | 画面贴合屏幕边缘（双击画面同理） |
| **`Esc`** | 层级退出 | 先关抽屉 -> 再退全屏 -> 退出播放返回网页 |
| **`[` / `]`** | 切换上一集 / 下一集 | 切换并展示下集标题 |
| **`C` / `S`** | 循环切换字幕轨道 | 弹出当前字幕名称提示 |
| **`A`** | 循环切换音轨 | 弹出当前音轨提示 |
| **`E` / `Tab`** | 呼出 / 收起 40% 选集侧滑抽屉 | 右侧抽屉滑入/滑出动画 |

### 9.4 进度与连播

- 使用 `play_token` 作为 Bearer；
- 默认按服务端 `progress_interval_ms`（5 秒）心跳上报；
- 暂停、seek、退出、播完立即补写；
- 90% 自动标记已看；
- 播完当前集自动无缝连播下一集（如果列表存在下集）。

---

## 10. 构建安装包

### 10.0 打包前必做：拉取 libmpv

`libmpv-2.dll`（Windows 121 MB）**不进 Git**，已在 `.gitignore` 中忽略。克隆仓库后必须先拉取，否则打包产物里没有播放内核，运行时会静默回退到 Qt Multimedia（MKV 播不了、控件被盖等症状全部复现）：

```bash
cd desktop
uv run python scripts/fetch_libmpv.py
```

脚本会自动识别当前平台并下载到 `src/strmaction_desktop/vendor/libmpv/<platform>-<arch>/`。**只需执行一次**，后续构建会直接复用。确认已就位：

```bash
ls src/strmaction_desktop/vendor/libmpv/windows-x64/libmpv-2.dll
```

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

脚本会自动用 uv 准备 `.venv`、安装依赖、生成各分辨率应用图标并调用 PyInstaller 完成一键打包。构建机与目标机均不需要额外安装播放器。

> 只想重新打包、跳过依赖安装时，可直接调用 PyInstaller：
> ```powershell
> .venv\Scripts\pyinstaller.exe packaging\strmaction-desktop.spec --noconfirm
> ```
> 加 `--clean` 可清空缓存（慢但干净，改过 spec 或 vendor 后建议加）。

### 10.2 macOS

直接执行构建脚本：

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
- 打包产物内不再包含第三方播放器二进制，Qt/PySide6 的 LGPL 义务请按官方说明处理。

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
- headers 只写入播放器的 `http-header-fields`，作用域限定在当前播放条目，不影响其他请求；
- WebView 只允许加载配置的服务器地址（外链交给系统浏览器）；
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
- libmpv 库定位、`http-header-fields` 格式化、mpv 错误码映射、`STRMACTION_DISABLE_MPV` 回退开关；
- 进度上报：payload、90% 已看、401、500 重试、client_key；
- JS Bridge 错误处理；
- WebView 导航 origin 限制；
- 桌面桥注入脚本。

需要真实 mpv 的两项验证是独立脚本（不入 pytest，因为要 GPU 上下文与解码线程）：

```bash
uv run python scripts/mpv_spike.py      # 渲染 / 控件叠加 / Qt 合成
uv run python scripts/mpv_ua_check.py   # UA 与 Referer 是否真的发出去（含 302 跳转）
```

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
| `ModuleNotFoundError: PySide6` | `uv pip install -r requirements.txt` 或 `uv pip install -e ".[dev]"` |
| 启动白屏 / 页面空白 | 检查服务器地址；确认服务器可访问；自签名证书需在设置里勾选「允许自签名 HTTPS」 |
| 播放黑屏并提示「播放失败」 | 多为片源证书/防盗链问题：勾选允许自签名；或检查服务端库级 `headers` |
| **启动后整个主界面黑屏**，日志有 `Failed to get a QRhi` / `OpenGL is not compatible with this QQuickWidget` | 有代码调用了全局 `QSurfaceFormat.setDefaultFormat()` 强制 OpenGL，QtWebEngine 的 `QQuickWidget` 因此拿不到 QRhi。GL 格式只能设在 `MpvVideoWidget` 自己身上，**不要**设为全局默认值 |
| 视频区域全黑但界面正常 | 一般是 `QWebEngineView` 与 `QOpenGLWidget` 在同一窗口里**同时可见**（此时 `context()` 为 `None`）。本项目用 `QStackedWidget` 切换不会触发；若改成同屏布局，视频需放独立窗口 |
| 每次启动都要重新登录 | 确认 `%APPDATA%\StrmAction\webview` 可写（持久化 profile） |
| 拖拽进度后回到开头 | 已修复：mpv 用 `loadfile start=` 原生起播定位 |
| 日志出现「播放后端：Qt Multimedia（未找到 libmpv）」 | `libmpv-2.dll` 缺失或路径不对；运行 `uv run python scripts/fetch_libmpv.py`，或用 `STRMACTION_LIBMPV` 指定 |
| 日志出现「mpv 渲染上下文创建失败」 | 显卡驱动 / OpenGL 不可用；先在 `scripts/mpv_spike.py` 里复现，确认 `GL 初始化后渲染上下文: True` |
| 想临时回到旧内核排查 | 设 `STRMACTION_DISABLE_MPV=1` 启动，即用 Qt Multimedia 回退路径 |
| 进度不更新 | 看 `desktop.log`；`play_token` 可能过期；重新从网页打开播放 |
| macOS 打不开 | 未公证会被 Gatekeeper 拦截；开发期右键打开，正式分发做公证 |
| 打包后找不到 assets | 必须在 `desktop/` 目录执行 `packaging/strmaction-desktop.spec` |
| PyInstaller 报 `script not found` | 从 `desktop/` 根目录运行，不要从 `packaging/` 里运行 |
| `uv` 命令不存在 | 安装 uv，或改用系统 Python + pip（不推荐） |
| 启动后没有桌面提示 | 确认服务端前端已更新；桌面桥在页面加载后注入 |

### 13.1 播放时上传速度比下载高，怎么查？

先给结论：

- StrmAction 桌面端在播放时的**唯一主动上传**是进度上报；
- 单次 payload 只有约 **100–300 字节**，默认每 **5 秒**一次；
- 实测模拟 20Hz 播放位置更新 7 秒，只有 **4 次请求、约 1.25KB**，折合 **0.0014 Mbps**；
- 内嵌播放器只接收媒体，不上传视频；
- 所以 **11 Mbps 的上传不可能是正常的进度上报**，需要按进程排查。

本次也修了一个相关 bug：`ProgressReporter` 之前会被每个 `time-pos` 事件唤醒，导致上报频率可能高于 `progress_interval_ms`；现在已改为严格按间隔上报，暂停/seek/退出/播完才立即 flush。旧构建需要重新构建桌面端。

排查顺序：

1. **按进程看流量**
   - Windows：`resmon` →「网络」→ 按「发送/接收」排序，看是 `python`、`QtWebEngineProcess` 还是其他程序；
   - macOS：活动监视器 →「网络」；或 `nettop -P`。
2. **暂停播放 / 退出桌面端**
   - 上传立刻下降 → 与播放链路有关；
   - 上传不变 → 是后台程序（网盘客户端、BT、云同步、备份、Windows Update 等）。
3. **看服务端访问日志**
   - 正常情况下 `/api/items/*/progress` 大约每 5 秒一条；
   - 如果每秒几十/几百条，说明旧版未节流或客户端异常。
4. **确认服务端是否在同一台机器**
   - 如果 StrmAction 服务端也在这台电脑上，而 `.strm` URL 指向本机的 Alist/WebDAV/反向代理，那么「上传」可能是本机在向播放器发送视频；
   - 如果服务端在 NAS/另一台机器，看是否有其他设备正在通过它拉流。
5. **看网络适配器**
   - VPN、Hyper-V、WSL、Docker、虚拟网卡会让任务管理器的总流量失真；
   - 用资源监视器按进程看，而不是只看网卡总量。
6. **确认测量口径**
   - 是看本机、路由器还是服务器？
   - 是 Mbps 还是 MB/s？
   - 路由器上的「上传」可能是别的设备产生的。

快速列出连接和进程（Windows）：

```powershell
Get-NetTCPConnection -State Established |
  Select-Object RemoteAddress, RemotePort, OwningProcess,
    @{n='Process';e={(Get-Process -Id $_.OwningProcess -ErrorAction SilentlyContinue).ProcessName}} |
  Sort-Object Process
```

如果退出 StrmAction 桌面端后上传仍然很高，基本可以确定不是桌面端播放/进度上报导致的。


日志位置见第 7 节。

---

## 14. 已知限制

- `play_token` 默认 12 小时；超长暂停后可能需要重新从网页打开；
- 托盘常驻、开机自启、自动更新暂未实现；
- macOS 公证/Windows 代码签名需要发布者证书；
- 目前只准备 Windows/macOS 打包，Linux 未测试。

---

## 15. 目录结构

```text
desktop/
├── README.md
├── CHECKLIST.md                开发/验收清单
├── pyproject.toml              依赖声明（PySide6, pywebview, httpx）
├── requirements.txt
├── requirements-dev.txt
├── uv.lock
├── run_desktop.py              PyInstaller 入口
├── src/strmaction_desktop/
│   ├── app.py                  桌面端入口与应用生命周期
│   ├── qt_window.py            PySide6 主窗口（QStackedWidget: Web + Player）
│   ├── bridge.py               JS Bridge 接口
│   ├── config.py               配置目录/读写（仅服务地址/缓存配置）
│   ├── progress.py             进度上报（5秒心跳）
│   ├── security.py             payload 校验/脱敏
│   ├── logging_setup.py
│   ├── version.py
│   ├── player/                 仿伴侣 App 自制播放控件与 libmpv 播放内核
│   │   ├── mpv_engine.py       libmpv 引擎封装 + MpvVideoWidget（OpenGL FBO 渲染）
│   │   ├── mpv_loader.py       libmpv 定位与加载（多路径查找 / DLL 目录注入）
│   │   ├── controller.py       Qt Multimedia 回退控制器（仅在无 libmpv 时使用）
│   │   ├── view.py             播放主视图（视频表面 + 控件叠加 + 抽屉）
│   │   ├── overlay.py          顶底控制栏、顶部倍速指示与中央反馈（ControlsOverlay）
│   │   ├── seekbar.py          平滑三层缓冲进度条（BufferedSeekBar）
│   │   ├── drawer.py           40% 右侧侧滑抽屉（PlayerDrawer: 选集高亮/倍速/音轨）
│   │   ├── keyboard.py         按键快捷键与长按倍速状态机
│   │   └── icons.py            SVG 矢量图标库
│   └── assets/
│       ├── error.html          连接失败页（重试 / 打开设置）
│       ├── icon.svg / png / ico / icns
├── scripts/
│   ├── make_icons.py
│   ├── build_windows.ps1       Windows 一键打包脚本
│   └── build_macos.sh          macOS 一键打包脚本
├── packaging/
│   └── strmaction-desktop.spec PyInstaller 打包规则（包含 Qt 多媒体与网页引擎）
└── tests/
    ├── test_player_ui.py       播放控件、选集高亮与键盘控制单元测试
    ├── test_mpv_engine.py      libmpv 库查找 / 请求头格式化 / 错误映射测试
    └── ...
```

---

## 16. FAQ

### Q1：现在还需要安装或下载 mpv 吗？

**用户不需要做任何事**。安装包已内置 `libmpv-2.dll`（`src/strmaction_desktop/vendor/libmpv/windows-x64/`），随应用一起分发，无需配置任何播放器路径。

如果想换成自己编译的精简版 libmpv，把库放到以下任一位置即可，查找优先级依次为：

1. 环境变量 `STRMACTION_LIBMPV`（直接指向库文件）
2. 环境变量 `STRMACTION_LIBMPV_DIR`（指向所在目录）
3. 包内 `vendor/libmpv/<平台-架构>/`
4. 用户数据目录 `%APPDATA%\StrmAction\libmpv\`

找不到 libmpv 时，桌面端会回退到 Qt Multimedia，但会失去请求头注入、外挂字幕、MKV 完整格式支持和流缓冲——不推荐。

### Q2：为什么设置里没有播放器路径配置了？

播放器完全内嵌、开箱即用，因此不再提供任何外部播放器路径配置。桌面端设置只有三项：服务器地址、预读缓存上限、允许自签名 HTTPS 证书。

### Q3：百度网盘或 Alist 的防盗链直链如何播放？

内嵌的 libmpv 会把服务端下发的 `User-Agent` 与 `Referer` 注入到每个 HTTP 请求，302 跳转到 CDN 之后依然生效；Range 寻道由 demuxer 直接发字节范围请求，不会报 403 Forbidden。

### Q4：内嵌播放器使用硬件加速吗？

是的。解码走 libmpv 的 `hwdec=auto-safe`（Windows D3D11VA / macOS VideoToolbox），画面经 `MpvRenderContext` 渲染进 `QOpenGLWidget` 的 FBO，再由 Qt 合成——所以控件不会被视频盖住，也不存在合成层黑屏问题。

### Q5：桌面端设置页里的“我的播放方式”对桌面端生效吗？

不生效。桌面端在网页层发现 `window.StrmActionNative.isDesktop()` 存在时，会自动使用 `direct` 模式交由桌面端内置原生播放器播放；该偏好只影响在普通浏览器或移动设备上访问。

### Q6：支持 Linux 吗？

源码理论上可运行，但当前只准备 Windows/macOS 的打包与验证；Linux 未做官方验证。

### Q7：能连播下一集吗？

支持。播完当前集自动连播下一集，也可通过快捷键 `[` / `]` 或 40% 选集侧滑抽屉随时选集切换，当前播放的剧集在抽屉中会带有清晰的高亮与图标指示。

### Q8：播放进度存在哪里？

服务端数据库的 `play_progress` 表，按用户隔离；桌面端以 5 秒心跳实时上报，不本地保存播放历史。

### Q9：桌面端会保存我的密码吗？

不会。登录在网页引擎内完成，Python 不接触密码，也不读取网页 Cookie。
