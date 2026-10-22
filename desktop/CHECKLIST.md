# StrmAction 桌面端开发清单（原生内嵌硬件加速 + 自制控件）

> 目标：macOS / Windows 桌面端，PySide6 加载现有网页，纯原生硬件加速内嵌播放器（零外部二进制依赖、零手动播放器路径配置），自制视频控件与键盘控制，5秒进度上报。
> 形态：**PySide6 现代桌面应用（Web 浏览 + 原生 QVideoWidget 播放器 + 本地环回流媒体代理 + 仿伴侣 App 自制控件）**。
> 代码位置：本目录 `desktop/`，不把桌面端源代码放到其他目录。
> 本机环境：使用 **uv** 管理 Python 环境（`uv venv` / `uv pip install -e ".[dev]"` / `uv run ...`）。

## 0. 架构与边界

- [x] WebView 加载服务端网页，登录、媒体库、详情、设置复用现有 Web UI
- [x] Python 不重复登录、不保存账号密码、不持有网页 Cookie
- [x] 网页通过 `window.StrmActionNative` 调用 Python：
  - `isDesktop()` / `version()`
  - `playItem(payloadJson)`：把 `/api/play` 返回的播放数据交给 Python
  - `openSettings()` / `stopPlayback()` / `quit()`
- [x] Python 原生播放：内嵌 `QMediaPlayer` + `QVideoWidget`，配合 `LocalStreamingProxy` 透传 headers，上报进度
- [x] 无需打包或配置 mpv：彻底去除 mpv 路径配置界面，纯 Python/PySide6 零外部二进制运行
- [x] 服务端新增 `direct` 模式：返回 URL/headers/play_token，不启动服务端 mpv
- [x] 复用现有 `POST /api/items/{id}/progress`（Bearer `play_token`）

## 1. 服务端集成

- [x] `VALID_MODES` 增加 `direct`
- [x] `resolve_mode_detail` 对 `direct` 直接返回，不选适配器
- [x] `direct` 不进入全局 `player.mode`/用户偏好选项
- [x] `/api/play` 的 `direct` 响应包含 `play_url / headers / play_token / resume_ms / progress_interval_ms / subtitles`
- [x] 测试：`direct` 不触发服务端 mpv、返回播放数据
- [x] 文档补充 `direct` 模式说明

## 2. 前端 Bridge

- [x] `StrmActionNativeBridge` 类型增加 `isDesktop()`、`playItem()`、`stopPlayback()`、`quit()`
- [x] `useStartPlayback` 检测桌面端：`/api/play` 使用 `mode: "direct"`，然后调用 `playItem`
- [x] 桌面端播放失败时显示明确 toast，不静默失败
- [x] `PlayResponse.mode` 支持 `direct`
- [x] 设置页显示“当前为桌面端”，提供“打开桌面端设置”（原生 QDialog）
- [x] `npm run build` 通过

## 3. desktop/ 工程基础

- [x] `pyproject.toml`、`requirements.txt`
- [x] `src/strmaction_desktop/` 包结构
- [x] 版本号、应用名 `StrmAction`
- [x] 配置目录（Windows `%APPDATA%` / macOS `Application Support`）
- [x] 配置读写：`server_url`、窗口尺寸、日志级别（彻底剔除 `mpv_path`）
- [x] 启动参数：`--server`、`--settings`、`--debug`
- [x] 首次启动进入设置页；保存后加载服务端网页

## 4. 配置与设置页

- [x] 原生设置对话框：服务器地址、预读缓存上限、自签名证书开关、版本
- [x] 保存配置并重新加载网页
- [x] 开箱即用：零播放器路径配置
- [x] 修改服务器地址后刷新 WebView
- [x] 配置原子写入，避免半截文件
- [x] 配置校验：只接受 http/https、去除尾部 `/`

## 5. 原生播放与内置流媒体代理（已完全替代旧版 mpv）

- [x] 内置本地环回流媒体代理（`proxy.py`，绑定 `127.0.0.1:<可用随机端口>`）
- [x] 代理全量透传服务端下发的所有 headers（`User-Agent` 与 `Referer`）
- [x] 妥善处理 302/301 跨域重定向与请求头保持，彻底杜绝 403 Forbidden
- [x] 支持 HTTP 206 Partial Content 与 Range 字节范围请求（保障拖拽 Seek 顺畅）
- [x] 基于 PySide6 `QMediaPlayer` + `QVideoWidget` + `QAudioOutput` 进行系统 GPU 硬件加速渲染
- [x] 播放结束/退出时优雅关闭代理会话与释放多媒体资源，无残留垃圾流

## 6. 请求头与字幕

- [x] 使用服务端 `headers` 全量设置，不只 User-Agent（由本地环回代理注入）
- [x] `Range` / `If-Range` / `If-None-Match` 透传，保证拖拽 seek
- [x] headers 只接受字符串键值；大小/数量限制
- [x] 字幕 URL 拼接服务器绝对地址（外挂字幕暂不支持内嵌播放器）
- [x] 支持容器内嵌字幕/音轨切换（Qt 6.8+ `subtitleTracks/audioTracks`）
- [x] headers/URL/token 不写日志

## 7. 播放状态

- [x] `positionChanged` / `durationChanged` / `playbackStateChanged` / `mediaStatusChanged`
- [x] 暂停/seek/退出/播完时立即 flush 进度
- [x] 播放错误上抛到界面（不再静默黑屏），提供重试/返回
- [x] 播完显示结束卡片，5 秒倒计时自动下一集
- [x] 单实例播放：新播放先停旧播放

## 8. 进度上报

- [x] 复用 `/api/items/{id}/progress`
- [x] `Authorization: Bearer <play_token>`
- [x] `client_key = desktop-<session_uuid>-<seq>`
- [x] 按 `progress_interval_ms` 上报，默认 5s
- [x] 位置、时长、finished 校验；90% 自动 finished
- [x] 单飞（同一时间只一个请求）
- [x] 失败退避重试，保留最新位置
- [x] 401/403 停止上报并通知“重新从网页打开”
- [x] 退出/暂停/播完 flush
- [x] 线程退出干净，不阻塞应用关闭

## 9. 安全

- [x] payload 校验：`item_id`、`http/https` URL、headers、token、数值范围
- [x] WebView 导航限制在配置的服务器 origin（Qt `acceptNavigationRequest`）
- [x] JS Bridge 只接受合法 payload，不执行任意命令
- [x] 日志脱敏：URL/token/headers 不落盘
- [x] HTTPS 证书校验；自签名需用户显式信任（后续）
- [x] 不保存密码/Cookie；只保存服务器地址、缓存上限与证书开关

## 10. 图标与打包

- [x] `assets/icon.svg`（来自网站 favicon）
- [x] `assets/icon.png` 512×512
- [x] `assets/icon.ico`（Windows）
- [x] `assets/icon.icns` 生成脚本（macOS）
- [x] PyInstaller spec：`console=False`，包含 assets（不含任何播放器二进制）
- [x] Windows 构建脚本
- [x] macOS `.app` 构建脚本、签名/公证说明
- [x] README：运行、配置、构建、限制

## 11. 测试

- [x] 配置校验单元测试
- [x] payload 校验/脱敏单元测试
- [x] headers 格式化单元测试
- [x] 代理 TLS 策略 / Content-Type 兜底单元测试
- [x] 进度上报 payload/重试/401/单飞测试（httpx.MockTransport）
- [x] Python `compileall` 通过
- [x] `pytest desktop/tests` 通过
- [x] 前端 `npm run build` 通过
- [x] 服务端 `pytest` 通过
- [x] 手工：设置保存、WebView 启动
- [ ] 手工：自签名片源播放（勾选「允许自签名 HTTPS」）
- [ ] 手工：暂停/退出/播完的进度回写与续播
- [ ] 手工：macOS/Windows 各一次（本轮至少验证当前平台）

## 12. 本轮已实现（纯原生硬件加速与 6 项缺陷彻底修复）

- [x] **架构升级**：彻底去除 mpv 外部可执行程序依赖与手动路径配置，升级为 `QMediaPlayer` + `QVideoWidget` + `LocalStreamingProxy`
- [x] **Bug 1 修复**：macOS 打包应用“保存并进入”无响应已解决（Bridge 注入与事件双向兼容，补充 `MainWindow.load_url`）
- [x] **Bug 2 修复**：Windows 视频黑屏有声音已彻底解决（原生 `QVideoWidget` 零 HWND 冲突）
- [x] **Bug 3 修复**：鼠标移动速度变快且卡顿已解决（`ControlsOverlay.mouseMoveEvent` 增加可见性与光标状态防抖节流）
- [x] **Bug 4 修复**：选集界面未指示当前播放剧集已解决（`security.py` 兼容 `id` 字段，`drawer.py` 激活 `▶ 播放中` 金色高亮与徽标）
- [x] **Bug 5 修复**：调节进度时缓存条闪烁已解决（`BufferedSeekBar` 增加平滑区间维持，拖拽 Seek 期间保持稳定缓冲）
- [x] **Bug 6 修复**：长按倍速提示居中遮挡画面已解决（移至窗口正上方 Y≈70px，改用 45% 高透明度磨砂金色胶囊）
- [x] **单元测试扩充**：47 passed（包含流媒体代理、Qt 播控、选集 ID 格式兼容性、鼠标节流与平滑缓冲）

## 13. 明确不在本轮范围

- [ ] 托盘常驻、开机自启、自动更新
- [ ] macOS 公证/Windows 代码签名（提供构建说明）
- [ ] 多账号/多设备管理、离线进度队列持久化

## 验收标准

1. 服务端 `direct` 模式可用，普通用户可拿到自己有权访问条目的播放数据。
2. 桌面端启动后能配置服务器地址并加载网页，登录成功。
3. 网页点播放时，桌面端内置原生播放器流畅播放，本地代理全量透传防盗链请求头与 302 重定向。
4. 播放中按间隔上报进度，暂停/退出/播完立即补写；401 有明确提示。
5. 零 mpv 依赖：开箱即用，无需配置任何外部播放器路径。
6. 源码全部位于 `desktop/`，不影响其他模块的既有行为。

## 验证记录（2026-10-22 / 纯原生架构升级与缺陷修复）

- 环境：Windows 11，uv 0.12.0，Python 3.12.13（`desktop/.venv`），PySide6 6.12.0。
- `desktop` 单元测试：**47 passed**。
- 服务端全量测试：**60 passed**。
- 原生渲染表面：`QVideoWidget` 直接调度系统 GPU，杜绝黑屏与外部窗口。
- 本地流媒体代理：`LocalStreamingProxy` 正确透传 User-Agent/Referer，处理 302 重定向与分片 Range 字节范围请求。
- 选集高亮与指示：`drawer.py` 正确识别后端 `id` 字段并指示当前播放剧集。
- 鼠标与反馈：鼠标移动无卡顿，倍速提示移至顶部透明胶囊，进度缓冲平滑稳定。

## 14. v1.3 本轮修复（黑屏 / 登录 / 设置 / 云端去 mpv）

- [x] **黑屏根因**：`proxy.py` 用裸 urllib 抓流，未遵循 `allow_self_signed_https`，
      自签名片源一律 `CERTIFICATE_VERIFY_FAILED` → 502 → `QMediaPlayer: Could not open file`。
      已改为按设置注入 SSL context，并透传 `Range/If-Range`、补齐 `Content-Type`/`Accept-Ranges`。
- [x] 播放失败不再静默：`errorOccurred` 接入界面，显示「播放失败 + 原因 + 重试/返回」。
- [x] **每次启动重新登录**：`QWebEngineView()` 默认 profile 是 off-the-record，
      `setPersistentStoragePath()` 无效。改为命名 profile + `ForcePersistentCookies` + 独立 cache 目录。
- [x] **设置页只能退出/保存并进入**：改为原生 `QDialog`，不导航主 WebView；
      保存后热生效（证书回调、代理 TLS 标志），只有服务器地址变化才重新加载。
- [x] `_webview_allow_self_signed` 在 Qt 分支从未初始化 → 勾选自签名必然要求重启；已修复。
- [x] 续播丢失：`seek()` 在 duration 未知时把目标 clamp 到 0；改为加载完成后应用起播位置。
- [x] 播放器上/下一集、选集、自动连播失效：`strmaction:request-play` 无人监听；前端已接入。
- [x] 播完/错误卡片、内嵌字幕与音轨切换、导航白名单、`settings.html` 移除。
- [x] 打包剔除 `vendor/mpv`（124MB）与 `pywebview` 依赖。
- [x] `desktop` 38 tests / `backend` 61 tests / 前端 `tsc + vite build` 全通过。
