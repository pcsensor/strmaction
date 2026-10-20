# StrmAction Desktop（Windows / macOS）

StrmAction 桌面端是一个 **WebView 外壳 + 本机 mpv 播放代理**：

- 网页、登录、媒体库、详情、设置全部复用服务端现有 Web UI；
- Python 不保存账号密码，也不读取网页 Cookie；
- 网页点播放后，把 `/api/play` 返回的播放数据交给 Python；
- Python 启动**本机 mpv**（独立播放窗口），自动设置服务端下发的全部请求头；
- 播放进度通过现有 `/api/items/{id}/progress` 接口上报，使用 item 级 `play_token`。

> 本机可以使用 `uv` 管理 Python 环境；下面命令默认使用 `uv`。

## 1. 环境要求

- Python 3.10+
- [uv](https://docs.astral.sh/uv/)
- Windows 10/11（需要 WebView2 Runtime，Win11 通常自带）
- macOS 11+（使用系统 WKWebView）
- mpv：
  - 推荐打包时自带（`scripts/prepare_mpv.py`）；
  - 开发时也可以使用系统已安装的 mpv（PATH、`/Applications/mpv.app`、Homebrew 等）。

服务端需要支持 `direct` 播放模式（见 `CHECKLIST.md`）。

## 2. 快速开始（源码运行）

```bash
cd desktop
uv venv
uv pip install -e ".[dev]"
uv run strmaction-desktop
```

或者：

```bash
uv run python -m strmaction_desktop
```

首次启动会打开桌面端设置页：

1. 填服务器地址（`https://media.example.com`，必须带 http/https）；
2. 选择或自动检测 mpv；
3. 点「保存并打开」，进入网页登录。

### 常用启动参数

```bash
uv run strmaction-desktop --server https://media.example.com
uv run strmaction-desktop --mpv "C:\tools\mpv\mpv.exe"
uv run strmaction-desktop --settings     # 直接打开桌面端设置
uv run strmaction-desktop --debug        # 调试日志 + WebView 调试
```

## 3. 配置与日志位置

| 平台 | 配置 |
|---|---|
| Windows | `%APPDATA%\StrmAction\config.json` |
| macOS | `~/Library/Application Support/StrmAction/config.json` |

日志：

- `%APPDATA%\StrmAction\logs\desktop.log`
- `~/Library/Application Support/StrmAction/logs/desktop.log`

WebView Cookie/存储：同目录下的 `webview/`。

配置只保存服务器地址、mpv 路径和窗口尺寸，不保存密码或 Cookie。

## 4. mpv 查找顺序

1. 配置里的 `mpv_path`；
2. 自带：`vendor/mpv/<platform>/mpv[.exe]`（macOS 也支持 `mpv.app`）；
3. 系统 PATH；
4. 常见安装路径：
   - macOS：`/Applications/mpv.app/Contents/MacOS/mpv`、`/opt/homebrew/bin/mpv`、`/usr/local/bin/mpv`
   - Windows：`C:\Program Files\mpv\mpv.exe`、`%LOCALAPPDATA%\Programs\mpv\mpv.exe`

如果找不到，播放会返回明确错误；可在桌面端设置页手动选择。

### 打包时自带 mpv

仓库不提交 mpv 二进制（体积 + 许可证/再分发义务）。构建前准备：

```powershell
# Windows：source 可以是包含 mpv.exe + DLL 的目录
uv run python scripts/prepare_mpv.py --source C:\tools\mpv
```

```bash
# macOS：可以是 mpv.app 或单个 mpv 可执行文件
uv run python scripts/prepare_mpv.py --source /Applications/mpv.app
```

目录约定见 `vendor/mpv/README.md`。

## 5. 播放与进度

- 网页调用 `/api/play/{item_id}`，`mode = "direct"`，拿到：
  `play_url / headers / play_token / resume_ms / progress_interval_ms / subtitles`；
- 前端通过 `window.StrmActionNative.playItem(JSON.stringify(payload))` 交给 Python；
- Python 启动 mpv，并通过 IPC：
  - 设置 `http-header-fields`（**全部**请求头，含 User-Agent、Referer、Cookie 等）；
  - 从 `resume_ms` 续播；
  - 加载字幕；
- 播放中按 `progress_interval_ms` 上报；
- 暂停、seek、退出、播完立即补写；
- `play_token` 过期/鉴权失败时停止上报并在日志提示，重新从网页打开播放即可。

## 6. 安全说明

- 不保存账号密码、网页会话 Cookie；
- 播放 URL、请求头、`play_token` 都是凭证，不写日志、不落盘；
- headers 通过 mpv IPC 设置，不放在命令行参数里（避免进程列表泄露）；
- IPC 使用随机命名管道（Windows）或权限 0700 的 Unix socket（macOS）；
- WebView 只应加载配置的服务器地址；
- 日志中的 URL 会脱敏；
- 生产环境请使用 HTTPS。

## 7. 构建安装包

### Windows

```powershell
cd desktop
.\scripts\build_windows.ps1
```

产物：`desktop\dist\StrmAction\StrmAction.exe`。

需要：
- 先准备 `vendor/mpv/windows-x64/`（可选，但推荐）；
- WebView2 Runtime（Win11 自带，Win10 可能需要安装）；
- 正式分发建议代码签名，减少 SmartScreen 提示。

### macOS

```bash
cd desktop
./scripts/build_macos.sh
```

产物：`desktop/dist/StrmAction.app`。

正式分发需要：
- Apple Developer ID；
- `codesign` + `notarytool` 公证；
- 如打包 mpv，确认 GPL/第三方许可证合规。

### 图标

`src/strmaction_desktop/assets/icon.svg` 来自网站 favicon；已生成：
- `icon.png`（窗口/设置页）
- `icon.ico`（Windows）
- `icon.icns`（macOS）

重新生成：

```bash
uv run python scripts/make_icons.py
```

## 8. 测试

```bash
cd desktop
uv run pytest -q
```

当前覆盖：配置校验、payload 校验/脱敏、mpv 查找、header 格式化、进度上报（payload、90% 已看、401、500 重试、client_key）。

## 9. 已知限制

- 播放窗口是**独立 mpv 窗口**，暂不把视频画面嵌入 StrmAction 主窗口；
- 不依赖用户安装 mpv 时，需要构建前自带 mpv；
- `play_token` 默认 12 小时；超长暂停后可能需要重新从网页打开；
- 暂不支持自动下一集/播放列表续播（接口字段已保留）；
- 托盘常驻、开机自启、自动更新暂未实现；
- macOS 公证/Windows 代码签名需要发布者证书。

## 10. 故障排查

| 现象 | 处理 |
|---|---|
| 启动提示缺少 pywebview | `uv pip install -r requirements.txt` |
| 页面空白/白屏 | 检查服务器地址；Windows 安装 WebView2 Runtime |
| 找不到 mpv | 设置页选择 mpv，或运行 `scripts/prepare_mpv.py` |
| 播放黑屏/403 | 检查服务端是否下发了正确 headers；确认网盘 URL 未过期 |
| 进度不更新 | 查看日志；`play_token` 可能过期，重新从网页播放 |
| macOS 打不开 | 未公证会被 Gatekeeper 拦截；开发期可右键打开 |
