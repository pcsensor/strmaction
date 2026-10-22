# StrmAction Desktop：Flutter + media_kit 改造方案

> 目标：用 Flutter 重写桌面壳，保留现有 Web 前端与后端 API，用 media_kit（libmpv）替换 PySide6 + QOpenGLWidget 播放层。
>
> 原则：**先验证、再搭骨架、再做 WebView、再做播放器、最后做 UI/打包/切换**。不要一开始就重写全部 UI。

---

## 1. 范围与目标

### 1.1 要做的事

- 新建 `desktop_flutter/`，不改动现有 `desktop/`，直到新版本稳定。
- WebView 继续加载现有 React 页面，保持登录、媒体库、详情、设置等体验。
- 播放器改为 Flutter 内嵌 `media_kit` + `media_kit_video`，底层仍是 libmpv。
- 保留现有播放器交互：顶栏、底栏、三层缓冲进度条、40% 抽屉、快捷键、长按倍速、自动隐藏、全屏、播完连播、错误卡片。
- 保留防盗链请求头、302/HLS、外挂字幕、音轨/字幕切换、进度上报、自签名 HTTPS。
- macOS/Windows 双平台打包、签名、公证、安装包。

### 1.2 不做的事（首版）

- 不重写服务端 API。
- 不重写现有 Web 前端（只保留 JS Bridge 兼容层）。
- 不在首版做 Linux。
- 不在首版做自动更新、托盘、开机自启。
- 不在首版做多窗口播放器（先用单窗口路由；确有必要再评估 `desktop_multi_window`）。

### 1.3 关键原则

1. **引擎继续用 mpv**，不要换 VLC。
2. **播放器 UI 与播放引擎解耦**，先定义接口，再接 media_kit。
3. **WebView 与播放器页面分离**，避免 platform view 与视频纹理同层叠加的层级问题。
4. **所有失败必须可见**：解码、渲染、请求头、证书、进度上报失败都要有日志和 UI 提示，不能静默黑屏。
5. **保留旧桌面端一个版本**，新端稳定后再删除。

---

## 2. 目标架构

### 2.1 技术选型

| 能力 | 选型 | 说明 |
|---|---|---|
| UI / 桌面壳 | Flutter 3.x（stable） | macOS/Windows 同一套代码 |
| 播放内核 | `media_kit` + `media_kit_video` | 底层 libmpv，支持 HLS/MKV/HEVC/ASS/外挂字幕 |
| 原生库 | `media_kit_libs_video` | 自带 macOS/Windows 的 libmpv 及依赖，不再手工管 XCFramework |
| WebView | `flutter_inappwebview` | 同时支持 macOS 与 Windows，支持 JS handler、Cookie、证书回调 |
| 窗口管理 | `window_manager` | 窗口尺寸、最小尺寸、全屏、退出保存 |
| HTTP | `http` + `dart:io HttpClient` | 健康检查、进度上报、自签名证书 |
| 配置 | JSON 文件（保持旧格式） | 路径与旧版一致，便于迁移 |
| 日志 | `logging` + 自定义 Rotating File | 位置与旧版一致，脱敏 |
| 状态管理 | Riverpod 或 `ChangeNotifier` | 小团队建议 `ChangeNotifier` + 明确的服务层 |
| 图标 | `flutter_svg` + 现有 SVG 资源 | 保持视觉一致 |

> `flutter_inappwebview` 的 macOS/Windows 实现存在平台差异，Phase 0 必须先验证；若 Windows 证书/下载等能力不满足，保留 `WebViewAdapter` 抽象，换 `webview_windows` 或平台通道。

### 2.2 总体结构

```text
┌─────────────────────────────────────────────────────────────┐
│ Flutter App（单窗口，Navigator 路由）                        │
│                                                             │
│  route: /web                                                │
│  ┌───────────────────────────────────────────────────────┐  │
│  │ InAppWebView                                          │  │
│  │  - 现有 React UI                                      │  │
│  │  - 持久 Cookie / localStorage                         │  │
│  │  - 注入 StrmActionNative / pywebview.api 兼容层        │  │
│  └───────────────────────────────────────────────────────┘  │
│                          │ playItem(JSON)                    │
│                          ▼                                   │
│  route: /player                                             │
│  ┌───────────────────────────────────────────────────────┐  │
│  │ PlayerPage                                            │  │
│  │  ├── Video(controller, controls: NoVideoControls)      │  │
│  │  ├── ControlsOverlay（自定义顶栏/底栏/缓冲条/抽屉）     │  │
│  │  ├── MessageCard（结束/错误/重试/连播）                 │  │
│  │  └── KeyboardHandler（空格/方向键/长按倍速/全屏）       │  │
│  └───────────────────────────────────────────────────────┘  │
│                          │                                   │
│                          ▼                                   │
│  services/ProgressReporter（5s 心跳/Bearer/90% 已看）        │
└─────────────────────────────────────────────────────────────┘
```

### 2.3 目录结构

```text
desktop_flutter/
├── lib/
│   ├── main.dart
│   ├── app.dart
│   ├── core/
│   │   ├── cli_args.dart
│   │   ├── config.dart
│   │   ├── paths.dart
│   │   ├── logging.dart
│   │   ├── http_client.dart
│   │   ├── redaction.dart
│   │   └── version.dart
│   ├── models/
│   │   ├── playback_payload.dart
│   │   ├── subtitle_info.dart
│   │   ├── track_info.dart
│   │   └── progress_state.dart
│   ├── web/
│   │   ├── webview_adapter.dart
│   │   ├── inapp_webview_adapter.dart
│   │   ├── web_shell_page.dart
│   │   ├── bridge.dart
│   │   ├── bridge_script.dart
│   │   ├── navigation_guard.dart
│   │   └── certificate_policy.dart
│   ├── player/
│   │   ├── playback_engine.dart
│   │   ├── media_kit_engine.dart
│   │   ├── player_page.dart
│   │   ├── player_controller.dart
│   │   ├── widgets/
│   │   │   ├── video_surface.dart
│   │   │   ├── controls_overlay.dart
│   │   │   ├── buffered_seekbar.dart
│   │   │   ├── player_drawer.dart
│   │   │   ├── message_card.dart
│   │   │   └── icons.dart
│   │   └── input/
│   │       └── keyboard_handler.dart
│   ├── features/
│   │   ├── settings/
│   │   │   ├── settings_dialog.dart
│   │   │   └── settings_controller.dart
│   │   └── connection/
│   │       ├── connection_check.dart
│   │       └── error_page.dart
│   └── services/
│       ├── progress_reporter.dart
│       ├── window_service.dart
│       └── external_links.dart
├── assets/
│   ├── icons/
│   └── images/
├── macos/
├── windows/
├── test/
│   ├── unit/
│   ├── widget/
│   └── integration/
├── pubspec.yaml
└── README.md
```

### 2.4 旧模块 → 新模块映射

| 旧文件 | 新文件 | 说明 |
|---|---|---|
| `app.py` | `main.dart` / `app.dart` / `core/cli_args.dart` | 入口、参数、生命周期 |
| `config.py` | `core/config.dart` / `core/paths.dart` | 同路径、同 JSON 字段 |
| `logging_setup.py` | `core/logging.dart` | 同日志位置、轮转、脱敏 |
| `qt_window.py` | `web/web_shell_page.dart` / `web/bridge.dart` | WebView + Bridge |
| `security.py` | `models/playback_payload.dart` / `core/redaction.dart` | payload 校验与脱敏 |
| `progress.py` | `services/progress_reporter.dart` | 进度上报 |
| `player/view.py` | `player/player_page.dart` / `player/player_controller.dart` | 播放页状态 |
| `player/mpv_engine.py` | `player/media_kit_engine.dart` | libmpv 封装 |
| `player/mpv_loader.py` | 删除 | media_kit 负责原生库加载 |
| `player/overlay.py` | `player/widgets/controls_overlay.dart` | 顶栏/底栏/反馈 |
| `player/seekbar.py` | `player/widgets/buffered_seekbar.dart` | 三层缓冲进度条 |
| `player/drawer.py` | `player/widgets/player_drawer.dart` | 40% 抽屉 |
| `player/endcard.py` | `player/widgets/message_card.dart` | 结束/错误卡片 |
| `player/keyboard.py` | `player/input/keyboard_handler.dart` | 快捷键状态机 |
| `player/icons.py` | `player/widgets/icons.dart` / `assets/icons/` | SVG 资源 |
| `settings_dialog.py` | `features/settings/settings_dialog.dart` | 设置对话框 |
| `assets/error.html` | `features/connection/error_page.dart` | 原生错误页 |
| `scripts/build_macos.sh` / `.ps1` | `.github/workflows/` + `scripts/` | CI 构建 |

---

## 3. 分阶段实施顺序

### 依赖关系

```text
Phase 0（技术验证）
   │
   ▼
Phase 1（骨架/配置/日志/模型）
   ├──────────────┬──────────────┐
   ▼              ▼              ▼
Phase 2（WebView） Phase 3（播放引擎） Phase 5（进度上报，可并行）
   │              │
   └──────┬───────┘
          ▼
Phase 4（播放器 UI）
          ▼
Phase 6（联调/功能对齐）
          ▼
Phase 7（双平台打包/签名/公证）
          ▼
Phase 8（QA/Beta/切换）
```

> Phase 2 和 Phase 3 可以在 Phase 1 后并行；Phase 4 依赖 Phase 3 的稳定接口；Phase 5 可以提前写，用 fake engine 测试。

---

### Phase 0：技术验证（1–2 天，必须先做）

**目的：在写业务代码前，证明风险最高的四件事能work。**

1. **Flutter + media_kit 真机能播**
   - macOS arm64 / Windows x64 各建一个最小 demo。
   - 测试：4K HEVC MKV、HLS、HTTP 302、MP4。
   - 测试 `Media(url, httpHeaders: {...})` 是否让 302 后的 CDN/HLS 分片也携带 `User-Agent`/`Referer`。
   - 测试 `NativePlayer.setProperty('http-header-fields', ...)` 作为兜底。
   - 测试 `SubtitleTrack.uri` 外挂字幕、`setAudioTrack`/`setSubtitleTrack`。
   - 测试 `Video(controls: NoVideoControls)` + Flutter 控件叠加。
   - 测试 `NativePlayer.getProperty('demuxer-cache-state')` 是否能拿到 `seekable-ranges`/`raw-input-rate`。

2. **WebView 真机能用**
   - `flutter_inappwebview` 加载现有 React 页面。
   - Cookie 持久化：重启后仍登录。
   - JS handler：Dart ↔ JS 双向调用；`playItem` 返回 JSON。
   - 页面加载前注入 `window.StrmActionNative` 兼容层。
   - 同源导航限制、外链交给系统浏览器。
   - 自签名 HTTPS：macOS `onReceivedServerTrustAuthRequest`；Windows 如不支持，确认替代方案（证书安装/平台通道）。
   - Windows WebView2 用户数据目录、缓存目录可配置。

3. **macOS 打包**
   - `flutter build macos --release`。
   - 确认 media_kit 的 libmpv/dylib 在 `.app` 内、可加载。
   - `codesign --deep --force --options runtime` + `notarytool` 最小验证。
   - 记录 `.app` 体积、启动时间。

4. **性能/稳定性**
   - 4K 60fps、连续播放 30 分钟、seek 100 次、全屏切换、睡眠唤醒。
   - 记录 CPU/GPU/内存；确认没有明显泄漏。

**通过标准：**

- 最小 demo 能在 macOS/Windows 播放 HLS/MKV，且 headers 生效；
- WebView 能登录并保持 Cookie，Bridge 能调用；
- 自签名 HTTPS 有可行方案；
- `.app` 能签名/公证；
- 记录所有不满足项和替代方案。

**产出：** `docs/spikes/flutter-media-kit-spike.md` + 最小 demo 分支（不合并到主分支）。

> 如果 Phase 0 的 WebView 证书或 headers 不通过，先解决/换实现，不要进入 Phase 1。

---

### Phase 1：项目骨架与核心基础（2–3 天）

1. 创建 `desktop_flutter/`：
   - `flutter create --platforms=macos,windows --org com.strmaction --project-name strmaction_desktop .`
   - 设置 app id：`com.strmaction.desktop`。
   - 迁移现有图标：`icon.icns` / `icon.ico` / png。
   - macOS 最低版本 11.0；Windows 10+。

2. 依赖：

```yaml
dependencies:
  flutter:
    sdk: flutter
  media_kit: ^1.2.6
  media_kit_video: ^2.0.1
  media_kit_libs_video: ^1.0.7
  flutter_inappwebview: ^6.1.5
  window_manager: ^0.5.0
  path: ^1.9.0
  http: ^1.2.0
  logging: ^1.3.0
  args: ^2.6.0
  url_launcher: ^6.3.0
  flutter_svg: ^2.0.0
  package_info_plus: ^8.0.0
```

3. `main.dart`：
   - `WidgetsFlutterBinding.ensureInitialized()`
   - `MediaKit.ensureInitialized()`
   - `await windowManager.ensureInitialized()`
   - 读取 CLI 参数、配置、日志
   - `runApp`
   - 初始化失败要有原生错误提示，不能白屏。

4. 核心模块：
   - `core/paths.dart`：保持旧路径
     - macOS：`~/Library/Application Support/StrmAction/`
     - Windows：`%APPDATA%\StrmAction\`
     - 子目录：`logs/`、`webview/`、`webview-cache/`
   - `core/config.dart`：同旧 JSON 字段
     - `server_url`、`cache_limit_mb`、`allow_self_signed_https`、`window_width`、`window_height`、`log_level`
     - 校验/归一化规则与 `desktop/config.py` 一致
     - 原子写入（tmp + rename）
   - `core/logging.dart`：文件轮转（2MB × 3），控制台 + 文件；debug 模式开 DEBUG。
   - `core/redaction.dart`：URL 只保留 scheme+host；headers/token 全部打码。
   - `core/http_client.dart`：5s/3s 超时，支持 `badCertificateCallback`。
   - `models/playback_payload.dart`：严格校验，字段与 `security.py` 一致：
     - `item_id`、`play_url`（仅 http/https）、`headers`（≤32）、`play_token`（正则）、`resume_ms`、`progress_interval_ms`（2–60s）、`subtitles`、`title`、`series_title`、`playlist`、`next_item_id`、`next_title`、`current_index`、`duration_ms`。

5. 单元测试：
   - 配置读写/归一化/旧配置迁移；
   - payload 校验/非法输入；
   - 脱敏；
   - 日志初始化（临时目录）。

**验收：** 新 app 能启动，读取旧配置，写日志；无 WebView/播放也能跑测试。

---

### Phase 2：WebView 壳与 Bridge（4–6 天）

1. `WebViewAdapter` 抽象：
   - `load(Uri)`、`reload()`、`evaluateJavascript(String)`、`dispose()`；
   - `Stream<WebViewEvent>`：加载成功/失败、导航请求、证书请求、窗口创建。
   - 这样将来换 Windows 实现不影响业务层。

2. `InAppWebViewAdapter`：
   - 持久化设置：`incognito: false`、`cacheEnabled: true`、`javaScriptEnabled: true`、`useShouldOverrideUrlLoading: true`。
   - 持久 Cookie；Windows WebView2 用户数据目录指向 `%APPDATA%\StrmAction\webview2`。
   - `shouldOverrideUrlLoading`：
     - 允许同源、`file:`、`data:`、`about:blank`；
     - 外链 `url_launcher` 打开系统浏览器；
     - `onCreateWindow` 返回 `false`，禁止弹窗。
   - 自签名：
     - macOS `onReceivedServerTrustAuthRequest`：`allow_self_signed_https` 为 true 时 `PROCEED`，否则 `CANCEL`。
     - Windows 若无回调：平台通道/证书安装方案（Phase 0 已验证）。
   - 加载失败/服务器不可达：显示 Flutter `ErrorPage`，带“重试/设置”，不要停在 Chromium 错误页。

3. Bridge 兼容层（关键）：
   - 在 `DocumentStart` 注入 `UserScript`，保留现有前端可识别的对象：
     - `window.StrmActionNative = { isDesktop, version, playItem, stopPlayback, openSettings, quit }`
     - `window.pywebview.api = { isDesktop, version, playItem, stopPlayback, openSettings, get_settings, save_settings, retryConnection, getConnectionError, quit }`
     - `window._strmaction_api = api`
     - `window._strmaction_bridge`（可选）
   - `isDesktop()` 同步返回 true；其他方法返回 Promise。
   - JS → Dart 使用 `window.flutter_inappwebview.callHandler('strmaction', method, args)`；
   - Dart → JS 使用 `evaluateJavascript` 派发：
     - `pywebviewready`
     - `strmaction:desktop-ready`
     - `strmaction:request-play`（`detail.itemId`）
     - `strmaction:progress-updated`
   - 每个方法返回 JSON 字符串，格式与旧实现一致：`{"ok": true}` / `{"ok": false, "error": "..."}`。
   - Bridge 未就绪时，`playItem` 返回明确错误，不要静默失败。

4. 设置与连接检查：
   - `SettingsDialog`：服务器地址、缓存上限、允许自签名；校验错误就地显示。
   - 保存后：
     - 若服务器地址没变：不重载 WebView，保持 React 状态；
     - 若变了：重新加载；
     - 同时更新播放器的 cache/TLS 设置。
   - 连接检查：
     - `GET {server}/api/health`，5s 超时，`X-StrmAction-Companion: 1`；
     - 在后台 isolate/异步执行，不阻塞 UI；
     - 失败显示错误页，重试成功后加载服务器。
   - 首次启动无配置：自动打开设置；未配置时不能进入空白 WebView。

5. WebView 生命周期：
   - 播放器页面打开时**不要销毁 WebView**，用 `IndexedStack` 或路由覆盖保留；
   - 返回网页时恢复同一个 `InAppWebView`，登录态/React 状态不丢。

**验收：**
- 重启后仍登录；
- 网页可浏览、外链走系统浏览器；
- `playItem` 能从网页调到 Dart 并返回；
- 设置可从网页打开、保存、热生效；
- 自签名 HTTPS 可选通过；
- 服务器不可达时显示错误页并可重试。

---

### Phase 3：播放引擎封装（3–5 天）

1. 定义接口 `PlaybackEngine`：
   - 状态流：`position`、`duration`、`paused`、`speed`、`bufferedRanges`、`networkSpeed`、`loading`、`tracks`、`error`、`completed`。
   - 方法：`load(payload)`、`play`、`pause`、`seek`、`setSpeed`、`setVolume`、`setVolumeRelative`、`setAudioTrack`、`setSubtitleTrack`、`addSubtitles`、`dispose`。
   - UI 只依赖接口，不直接依赖 media_kit。

2. `MediaKitEngine`：
   - `Player` + `VideoController` 每个播放页创建一次，退出时 `dispose()`。
   - 初始化：
     ```dart
     final player = Player();
     final controller = VideoController(
       player,
       configuration: const VideoControllerConfiguration(
         enableHardwareAcceleration: true,
       ),
     );
     ```
   - 播放：
     ```dart
     await player.open(
       Media(url, httpHeaders: payload.headers),
       play: false,
     );
     // 等待 render/video 初始化后 seek 到 resume
     await player.seek(Duration(milliseconds: payload.resumeMs));
     await player.play();
     ```
     若 media_kit 对 `httpHeaders` 的 302/HLS 覆盖不完整，额外在 `open` 前：
     ```dart
     final native = player.platform as NativePlayer;
     await native.setProperty('http-header-fields', formatHeaders(payload.headers));
     ```
   - 缓存/TLS/解码：
     ```dart
     await native.setProperty('cache', cacheLimitMb > 0 ? 'yes' : 'no');
     await native.setProperty('demuxer-max-bytes', '${cacheLimitMb}MiB');
     await native.setProperty('demuxer-max-back-bytes', '${max(1, cacheLimitMb ~/ 4)}MiB');
     await native.setProperty('tls-verify', tlsVerify ? 'yes' : 'no');
     await native.setProperty('hwdec', 'auto-safe');
     ```
   - 轨道：
     - `player.stream.tracks` → 映射 `Tracks.audio`/`Tracks.subtitle`；
     - `player.stream.track` → 当前选中；
     - `setAudioTrack(AudioTrack)` / `setSubtitleTrack(SubtitleTrack.no()/track)`。
   - 外挂字幕：
     - 对 payload.subtitles 逐个 `SubtitleTrack.uri(url, title: label)`；
     - 第一个设为当前，其余保留在轨道列表；
     - 注意：`setSubtitleTrack` 是“选中”，不是“追加”；如需保留多个外挂轨道，使用 media_kit 的 playlist/`addSubtitle` 能力或 `NativePlayer.command(['sub-add', ...])`，Phase 0 验证。
   - 缓冲/网速：
     - 每 500ms 读取：
       ```dart
       final raw = await native.getProperty('demuxer-cache-state');
       ```
     - 解析 `seekable-ranges` → `[(start,end)]`，合并 0.1s 内的区间；
     - 解析 `raw-input-rate` 作为网速；
     - 失败时退回 `player.stream.buffer`（只画当前位置到 buffer 的单段）。
   - 错误：
     - `player.stream.error` 统一映射为中文；
     - 15s 内没有 `videoParams`/首帧 → 主动报“视频输出初始化失败”；
     - 不要静默黑屏；错误卡片提供“重试/返回”。

**验收：**
- 本地 MP4、HLS、MKV/HEVC 可播；
- 带 `User-Agent`/`Referer` 的 302 直链可播；
- 外挂字幕、音轨/字幕切换可用；
- 暂停/seek/倍速/音量可用；
- 缓冲区间和网速有数据；
- 错误能在 UI 显示。

---

### Phase 4：播放器 UI（6–8 天）

1. `PlayerPage`：
   - 背景黑；`Video(controller: ..., controls: NoVideoControls)`；
   - `Stack` 上叠加 `ControlsOverlay`、`PlayerDrawer`、`MessageCard`；
   - 屏幕适配：`LayoutBuilder` + `MediaQuery.devicePixelRatio`；小窗/全屏都正常。

2. ControlsOverlay：
   - 顶栏：返回、标题、剧集标题、倍速胶囊；
   - 底栏：
     - 播放/暂停、上一集/下一集；
     - 当前时间 / 总时长；
     - 倍速按钮；
     - 选集、音轨字幕、全屏；
     - 音量/静音、网速；
   - 中央反馈：播放/暂停脉冲、`+5s`/`-5s`、`2.0x`、音量百分比；
   - 自动隐藏：3.5s 无操作隐藏顶底栏 + 鼠标指针；鼠标移动/点击恢复；
   - 抽屉打开时不自动隐藏。

3. BufferedSeekBar：
   - 8px 圆角轨道 `#3DFFFFFF`；
   - 已播放 `#F0A94D`；
   - 2.5px 缓冲线 `#E8FFFFFF`，支持多区间；
   - 3.5×16 白色滑块；
   - 拖拽时暂停位置更新、显示时间 tooltip；
   - 释放时 seek；
   - 用 `GestureDetector` + `CustomPainter` 实现，不用第三方 seekbar。

4. PlayerDrawer：
   - 右侧 40% 宽，左侧 16px 圆角，`#13161F` 背景；
   - 左侧半透明遮罩，点击关闭；
   - 三个 tab：
     - 选集：网格、已看、当前高亮、滚动；
     - 倍速：0.5x–3.0x；
     - 音轨与字幕：内嵌/外挂、关闭字幕、当前选中；
   - 动画：`AnimatedPositioned`/`SlideTransition`，200–250ms。

5. MessageCard：
   - 播放结束：显示“下一集”+5s 倒计时，倒计时结束触发 `nextEpisodeRequested`；
   - 错误：显示原因 + 重试/返回；
   - 半透明深色圆角卡片，样式与旧版一致。

6. KeyboardHandler：
   - 与旧版完全一致：
     - Space：播放/暂停（忽略 repeat）
     - Left：-5s
     - Right：短按 +5s；按住 ≥250ms 进入 2.0x，松开恢复
     - Up/Down：音量 ±5
     - M：静音
     - F/F11：全屏
     - Esc：抽屉 → 全屏 → 返回网页
     - `[` / `]`：上一集/下一集
     - C/S：循环字幕
     - A：循环音轨
     - E/Tab：抽屉
   - 用 `Focus(onKeyEvent:)` + `HardwareKeyboard`；`KeyRepeatEvent` 统一忽略（右方向键必须忽略，避免 seek 风暴）。
   - 播放页打开时主动 `FocusScope.requestFocus`，避免 WebView 抢焦点。

7. 全屏/窗口：
   - `window_manager.setFullScreen(true/false)`；
   - 双击画面切换；
   - F/F11 切换；
   - Esc 按层级退出；
   - 退出全屏时恢复窗口尺寸。

**验收：**
- 与旧版视觉/交互对齐；
- 所有快捷键可用；
- 4K 播放时 UI 不卡顿；
- 抽屉/自动隐藏/全屏/连播/错误卡片正常。

---

### Phase 5：进度上报（2–3 天，可与 Phase 4 并行）

按 `desktop/progress.py` 逐条移植：

- URL：`{server}/api/items/{item_id}/progress`
- Header：
  - `User-Agent: StrmActionDesktop/{version}`
  - `Authorization: Bearer {play_token}`
- 间隔：`clamp(progress_interval_ms / 1000, 2, 60)` 秒；
- 单飞 + 合并：只保留最新位置，不因 `time-pos` 高频唤醒；
- `update(position, duration)` 只置 dirty，不唤醒；
- `request_flush()` / `finish()` / 暂停 / seek / 退出 立即发送；
- `finished`：位置/时长 ≥ 0.9 时置 true，位置归 0；
- `client_key: desktop-{session}-{sequence}`；
- 401/403：停止上报，触发“凭证失效，请重新打开播放”；
- 其他 ≥400：保留 dirty，下个周期重试；
- 网络异常：保留 dirty，不崩溃；
- 超时：5s，连接 3s；
- `verify_ssl` 跟随配置；
- App 退出/返回网页前 `stop(flush: true)`，最多等 4s。

**测试：** 用本地 mock server 验证 5s 心跳、暂停/seek 立即 flush、90% 已看、401、500 重试、退出 flush。

**验收：** 服务端日志约每 5 秒一条，无请求风暴；退出后最后一次进度已写入。

---

### Phase 6：联调与功能对齐（3–5 天）

1. 完整链路：
   - 网页点击播放 → `/api/play` → Bridge `playItem` → payload 校验 → 打开播放页 → media_kit 起播 → 进度上报；
   - 返回网页 → flush 进度 → 派发 `strmaction:progress-updated`；
   - 下一集/上一集 → 派发 `strmaction:request-play` → 网页重新请求播放 → 新 payload；
   - 播完 → 5s 倒计时 → 自动下一集；
   - 401/403 → 停止上报 + 提示；
   - 结束/错误卡片重试。

2. 配置/窗口：
   - 启动恢复窗口尺寸；最小 900×640；
   - 播放页全屏不影响网页窗口尺寸；
   - 关闭窗口保存尺寸 + flush 进度 + dispose player + dispose WebView。

3. 兼容性：
   - 保留 `window.StrmActionNative` / `pywebview` 兼容层，前端不需要改；
   - 如果前端后续要清理，单独提 PR，迁移到 `window.StrmActionDesktop`，新老桌面端并行一个版本。

4. 边界：
   - 无效 payload、过期 token、服务器 404/500；
   - 片源 403/404、302 到 CDN、HLS 分片；
   - 自签名证书；
   - 音频设备切换、静音；
   - 代理/VPN/IPv6；
   - 睡眠唤醒后恢复；
   - 多显示器/不同 DPI。

**验收：** 与旧版功能清单逐项对齐；关键路径无回归。

---

### Phase 7：双平台打包、签名、公证（3–5 天）

#### macOS

- `flutter build macos --release`
- 检查 `.app`：
  - `Contents/Frameworks/` 内有 media_kit 的 libmpv 及依赖；
  - `otool -L` 确认 `@rpath` 可解析；
  - `codesign --verify --deep --strict`。
- 签名：
  - 先签嵌套 dylib/framework，再签 `.app`；
  - `codesign --force --options runtime --timestamp --sign "Developer ID Application: ..."`；
  - `xcrun notarytool submit ... --wait`；
  - `xcrun stapler staple`。
- DMG：`create-dmg` 或 `hdiutil`。
- 干净 Mac 上验证 Gatekeeper、首次启动、播放、登录。

#### Windows

- `flutter build windows --release`
- 安装包：Inno Setup / WiX / MSIX。
- 依赖：
  - WebView2 Runtime（Evergreen bootstrapper 或检测已安装）；
  - VC++ Runtime；
  - media_kit DLL。
- 签名：`signtool`。
- 干净 Windows 10/11 验证安装、播放、升级/卸载。

#### CI

- GitHub Actions：
  - macOS runner：`flutter test` + `flutter build macos --release` + 签名/公证（secrets）；
  - Windows runner：`flutter test` + `flutter build windows --release` + 安装包；
- 缓存 Flutter SDK / pub / Gradle（如未来 Android）。
- 产物：`.dmg`、`.exe`/`.msi`、测试报告、体积报告。

**验收：** 干净机器可安装、启动、登录、播放；签名/公证通过；包体记录在案。

---

### Phase 8：QA、Beta、切换（1–2 周）

1. 测试矩阵：
   - macOS 11/14/26/27，arm64；Windows 10/11 x64；
   - 4K HEVC、AV1、H.264、MKV、HLS、MP4；
   - 带 headers 的 302/CDN；自签名；代理；
   - 外挂字幕、多音轨、多字幕、ASS；
   - 长按倍速、全屏、抽屉、自动隐藏；
   - 睡眠/唤醒、音频设备切换、多显示器/DPI；
   - 长时间播放 2h、内存/句柄泄漏。

2. 与旧版对比：
   - 启动时间、首帧时间、seek 延迟、CPU/GPU、内存、包体；
   - 记录差异，超过阈值要优化。

3. Beta：
   - 先内部/小范围用户；
   - 收集日志（脱敏）、崩溃、播放失败样本；
   - 保留旧版下载入口，随时回滚。

4. 切换：
   - 新版本稳定后，更新 README/发布脚本；
   - 旧 `desktop/` 移到 `legacy/` 或保留一个 release；
   - 删除 Python 桌面端依赖前，确认无用户仍在使用旧配置/旧包。

---

## 4. 关键设计细节

### 4.1 请求头与 302/HLS

- 首选 `Media(url, httpHeaders: payload.headers)`；
- 若 302 后/HLS 分片丢失，使用：
  ```dart
  final native = player.platform as NativePlayer;
  await native.setProperty(
    'http-header-fields',
    headers.entries.map((e) => '${e.key}: ${e.value}').join(','),
  );
  await player.open(Media(url), play: false);
  ```
- 头字段名不能包含 `,`/`:`；值不能含换行；与旧版 `_format_headers` 一致；
- 必须用本地 302 测试服务器验证“首个请求 + 跳转后 + HLS 分片”都带头。

### 4.2 缓冲区间与网速

- 每 500ms：
  ```dart
  final raw = await native.getProperty('demuxer-cache-state');
  final map = jsonDecode(raw) as Map<String, dynamic>;
  ```
- `seekable-ranges` → 多区间；`raw-input-rate` → bytes/s；
- 解析失败时退回 `player.stream.buffer`；
- 不要把整个区间固定从 0 开始；按旧版 `_merge_ranges` 合并。

### 4.3 起播与 resume

- 不要 `open` 后立即 `seek`；等 `VideoController` / `videoParams` 就绪；
- 推荐：
  ```dart
  await player.open(Media(url, httpHeaders: headers), play: false);
  await player.stream.videoParams.firstWhere((p) => p.w > 0);
  if (resumeMs > 0) await player.seek(Duration(milliseconds: resumeMs));
  await player.play();
  ```
- 若 media_kit 的 `open` 已经自动播放，先 `pause` 再 seek，避免闪一下第一帧。

### 4.4 错误处理

- `player.stream.error` → 中文提示；
- 15s 无首帧/无 `videoParams` → “视频输出初始化失败”，提供重试；
- `Media` 打开失败 → “无法打开片源（链接过期/防盗链/证书）”；
- 音频设备失败 → “音频设备初始化失败”；
- 不要出现“只有黑屏没有提示”。

### 4.5 WebView Bridge 契约

Dart 侧 handler：

```dart
await controller.addJavaScriptHandler(
  handlerName: 'strmaction',
  callback: (args) async {
    final method = args[0] as String;
    final payload = args.length > 1 ? args[1] : null;
    switch (method) {
      case 'playItem': ...
      case 'stopPlayback': ...
      case 'openSettings': ...
      case 'get_settings': ...
      case 'save_settings': ...
      case 'retryConnection': ...
      case 'getConnectionError': ...
      case 'quit': ...
    }
  },
);
```

JS 兼容层要点：

- `isDesktop()` 同步 `true`；
- `version()` 同步返回版本；
- `playItem(payloadJson)` 返回 Promise；
- 所有返回 JSON 字符串；
- 注入时机：`DocumentStart`；若失败，`onLoadStop` 再注入一次；
- 派发 `pywebviewready` 与 `strmaction:desktop-ready`。

### 4.6 Cookie、证书与自签名

- macOS：
  - `WKWebView` 默认持久化；不要用 incognito；
  - `onReceivedServerTrustAuthRequest` 根据配置接受/拒绝；
- Windows：
  - WebView2 用户数据目录固定到 `%APPDATA%\StrmAction\webview2`；
  - 若插件不支持证书回调，Phase 0 确定方案（平台通道/证书安装/改用 `webview_windows`）；
- 旧 QtWebEngine 的 Cookie 不能迁移，用户首次需要重新登录；在发布说明中写明。

### 4.7 配置与日志路径

保持旧路径，避免用户重新配置：

- macOS：`~/Library/Application Support/StrmAction/config.json`、`logs/desktop.log`
- Windows：`%APPDATA%\StrmAction\config.json`、`logs\desktop.log`
- 旧字段保持不变；新增字段必须可选且有默认值。

### 4.8 安全

- 不记录播放 URL/headers/token；
- URL 日志只保留 scheme+host；
- Bridge 只接受合法 payload；
- WebView 只允许配置的服务器源；外链走系统浏览器；
- 生产环境 HTTPS；自签名需显式开关；
- 发布包不包含调试符号/明文密钥。

---

## 5. 测试与验收清单

### 5.1 功能

- [ ] 首次启动设置服务器
- [ ] 登录并保持 Cookie
- [ ] 媒体库/详情/搜索/设置
- [ ] 点击播放 → 内嵌播放器
- [ ] 带 UA/Referer 的 302 直链
- [ ] HLS、MKV、HEVC、4K
- [ ] 暂停/播放/seek/倍速/音量/静音
- [ ] 外挂字幕、内嵌字幕、音轨切换
- [ ] 三层缓冲条、网速
- [ ] 顶栏/底栏/自动隐藏/鼠标隐藏
- [ ] 40% 抽屉（选集/倍速/音轨字幕）
- [ ] 快捷键 + 长按右方向键 2.0x
- [ ] 全屏/Esc 层级
- [ ] 播完 5s 连播
- [ ] 错误/重试/返回
- [ ] 进度 5s 心跳、暂停/seek/退出 flush、90% 已看
- [ ] 返回网页后刷新继续观看
- [ ] 自签名 HTTPS
- [ ] 窗口尺寸恢复/最小尺寸
- [ ] 干净机器安装/签名/公证

### 5.2 平台矩阵

| 平台 | 版本 | 架构 |
|---|---|---|
| macOS | 11/14/26/27 | arm64 |
| Windows | 10/11 | x64 |

### 5.3 性能

- 首帧 < 2s（正常网络）
- 4K 60fps 播放 CPU/GPU 可接受
- 连续 2h 无内存/句柄持续增长
- seek 100 次无崩溃/卡死
- 包体记录（目标 < 200MB）

---

## 6. 风险与对策

| 风险 | 影响 | 对策 |
|---|---|---|
| `flutter_inappwebview` Windows 证书/下载能力不足 | 自签名/下载失败 | Phase 0 验证；抽象 `WebViewAdapter`；必要时换 `webview_windows` 或平台通道 |
| media_kit 的 `httpHeaders` 对 302/HLS 覆盖不完整 | 403 无法播放 | Phase 0 用本地 302 服务器验证；兜底 `http-header-fields` |
| `demuxer-cache-state` 在 media_kit 中不可用 | 三层缓冲退化为单段 | 已确认 `NativePlayer.getProperty` 可用；保留 `stream.buffer` 兜底 |
| 外挂多字幕轨道 API 限制 | 只能选一个外挂字幕 | 先用 `SubtitleTrack.uri` 逐个验证；必要时 `sub-add` 命令 |
| macOS 签名/公证失败 | 无法分发 | Phase 0 最小公证；CI 自动化；逐层签名 |
| WebView platform view 与视频纹理层级 | 控件被盖/黑屏 | 播放页独立路由，播放时 WebView 不可见；不要同层叠加 |
| 键盘 auto-repeat | 长按右键 seek 风暴 | 忽略 `KeyRepeatEvent`；按旧版状态机移植 |
| 旧 Cookie 不能迁移 | 用户需重新登录 | 发布说明；保留旧版一个版本 |
| media_kit/libmpv 版本升级 | 行为变化 | 锁定版本；升级前跑完整播放回归 |
| 包体过大 | 下载/安装成本 | `--split-debug-info`、release 构建、移除未用资源；记录体积 |

---

## 7. 排期与人力（粗略）

| 阶段 | 1 人 | 2 人 |
|---|---|---|
| Phase 0 技术验证 | 1–2 天 | 1 天 |
| Phase 1 骨架 | 2–3 天 | 1–2 天 |
| Phase 2 WebView/Bridge | 4–6 天 | 2–3 天 |
| Phase 3 播放引擎 | 3–5 天 | 2–3 天 |
| Phase 4 播放器 UI | 6–8 天 | 3–4 天 |
| Phase 5 进度上报 | 2–3 天 | 1–2 天 |
| Phase 6 联调 | 3–5 天 | 2–3 天 |
| Phase 7 打包/签名 | 3–5 天 | 2–3 天 |
| Phase 8 QA/Beta | 1–2 周 | 1 周 |
| **合计** | **6–8 周** | **4–5 周** |

> 前提：1 名熟悉 Flutter 的开发者；如果团队没有 Flutter 经验，Phase 1–4 需要额外 1–2 周学习/踩坑。

---

## 8. 上线与回滚

1. **并行发布**：旧 `desktop/` 保持可用；新 `desktop_flutter/` 先内测。
2. **配置兼容**：新端读取旧 `config.json`；不破坏旧端。
3. **登录迁移**：Cookie 不通用，首次登录；发布说明写清楚。
4. **灰度**：先小范围用户，收集日志；关键指标：首帧时间、播放失败率、进度上报成功率、崩溃率。
5. **回滚**：保留旧安装包与旧下载入口；新端严重问题时切回。
6. **清理**：稳定 1–2 个版本后，删除 `desktop/` 或移到 `legacy/`，更新 README/CI/发布脚本。

---

## 9. 建议的第一周任务（可直接执行）

1. 建 `desktop_flutter/`，搭最小 Flutter app。
2. 跑通 media_kit 播放一个 HLS + 一个 MKV，截图记录。
3. 用本地 302 服务器验证 `Media.httpHeaders` / `http-header-fields`。
4. 用 `flutter_inappwebview` 加载现有 Web UI，验证登录 Cookie 与 `addJavaScriptHandler`。
5. 写一页最小 `PlayerPage`：Video + 一个半透明按钮，证明控件叠加。
6. 产出 Phase 0 报告；通过后再进入 Phase 1。
