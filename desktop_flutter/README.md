# StrmAction Desktop（Flutter + media_kit）

这是 StrmAction 桌面端的 Flutter 重构版本：

- Flutter 桌面壳，复用现有服务端 Web UI；
- WebView 负责登录、媒体库、详情、设置；
- media_kit（libmpv）负责内嵌视频播放；
- 云服务器下发的 `User-Agent` / `Referer` 会附加到媒体请求；
- 支持缓存预算、TLS、音轨/字幕、外挂字幕、5 秒进度上报；
- 播放器 UI 按旧版 Qt 播放器复刻。

旧版 `desktop/` 暂时保留，待新版本验证稳定后再切换。

## 环境要求

| 项目 | 要求 |
|---|---|
| Flutter | 3.47+ / Dart 3.13+ |
| macOS | macOS 11+，Xcode 15+ |
| Windows | Windows 10/11，Visual Studio 2022（Desktop development with C++） |
| Windows 构建 | NuGet CLI（构建脚本会自动下载） |
| Windows 运行 | WebView2 Runtime（Win10/11 通常已自带） |

## 运行

从 `desktop_flutter/` 目录执行：

```bash
flutter pub get
flutter run -d macos       # macOS
flutter run -d windows     # Windows
```

命令行参数：

```text
--server URL     设置并保存服务器地址
--settings       启动后打开设置
--debug          调试日志
--version        输出版本号
```

## 构建

### Windows

```powershell
cd desktop_flutter
.\scripts\build_windows.ps1
```

产物：

```text
dist/StrmAction-Windows/StrmAction.exe
dist/StrmAction-Windows.zip
```

脚本会自动准备 NuGet、执行 analyze/test、构建 release，并把 exe 重命名为 `StrmAction.exe`。

### macOS

```bash
cd desktop_flutter
chmod +x scripts/build_macos.sh
./scripts/build_macos.sh
```

产物：

```text
build/macos/Build/Products/Release/StrmAction.app
dist/StrmAction-macOS.zip
```

签名/公证：

```bash
CODESIGN_IDENTITY="Developer ID Application: Your Name (TEAMID)" \
NOTARY_PROFILE="strmaction-notary" \
./scripts/build_macos.sh
```

> 正式分发前请在 macOS 上验证 `codesign --verify --deep --strict`、`spctl` 和公证结果。

## 关键实现

### 请求头（UA / Referer）

播放时使用：

```dart
Media(
  payload.playUrl,
  httpHeaders: payload.headers,
  start: payload.resumeMs > 0 ? Duration(milliseconds: payload.resumeMs) : null,
)
```

media_kit 会把 `httpHeaders` 写入 libmpv 的 `http-header-fields`，对首个请求、302 后的请求以及 HLS 分片生效。工程内已用本地 302 测试服务器验证过。

### 缓存与 TLS

通过 `NativePlayer` 设置：

```dart
await platform.setProperty('cache', cacheLimitMb > 0 ? 'yes' : 'no');
await platform.setProperty('demuxer-max-bytes', '${cacheLimitMb}MiB');
await platform.setProperty('demuxer-max-back-bytes', '${max(1, cacheLimitMb ~/ 4)}MiB');
await platform.setProperty('tls-verify', tlsVerify ? 'yes' : 'no');
await platform.setProperty('hwdec', 'auto-safe');
```

每 500ms 读取 `demuxer-cache-state`，解析 `seekable-ranges` 和 `raw-input-rate`，用于三层进度条和网速显示。

### 进度上报

`services/progress_reporter.dart` 对齐旧版 Python 逻辑：

- Bearer `play_token`；
- 2–60 秒间隔；
- 单飞 + 合并请求；
- 暂停/seek/退出/播完立即 flush；
- 90% 自动标记 finished；
- 401/403 停止上报并提示。

### WebView Bridge

`web/bridge_script.dart` 注入兼容层，保留：

- `window.StrmActionNative`
- `window.pywebview.api`
- `window._strmaction_api`

因此现有前端不需要修改。

### 播放器 UI

- `player/widgets/controls_overlay.dart`：顶栏、底栏、中心反馈；
- `player/widgets/buffered_seekbar.dart`：复刻旧版三层进度条；
- `player/widgets/player_drawer.dart`：40% 选集/倍速/音轨抽屉；
- `player/widgets/message_card.dart`：播完/错误卡片；
- `player/input/player_keyboard.dart`：快捷键与长按右键 2.0x。

底栏使用 `LayoutBuilder` 按实际约束高度定位，避免 Windows 窗口/DPI 组合下 `Positioned(bottom: 0)` 把控制栏排到窗口外。

## 测试

```bash
flutter analyze
flutter test
```

当前测试覆盖配置、payload 校验、请求头格式化、进度上报 body/鉴权头、进度条时间格式和控制层布局。

## 已知事项

- 旧 QtWebEngine 的 Cookie 不能迁移到 WKWebView/WebView2，首次使用需要重新登录一次；
- Windows 端当前使用 DPI unaware manifest 以保证窗口坐标和 Flutter 布局一致，后续可改为 PerMonitorV2 + 显式坐标换算；
- macOS 构建/签名/公证需要在 macOS 机器上执行，本仓库的 Windows 开发环境无法实际运行 Xcode；
- 旧 `desktop/` 保留到新端完成验收后再移除或归档。
