# StrmAction 桌面端开发清单（方案 A 形态：内嵌播放 + 自制控件）

> 目标：macOS / Windows 桌面端，PySide6 加载现有网页，内嵌 mpv 播放器，自制视频控件与键盘控制，5秒进度上报。
> 形态：**PySide6 现代桌面应用（Web 浏览 + 内嵌 mpv 播放器 + 仿伴侣 App 自制控件）**。
> 代码位置：本目录 `desktop/`，不把桌面端源代码放到其他目录。
> 本机环境：使用 **uv** 管理 Python 环境（`uv venv` / `uv pip install -e ".[dev]"` / `uv run ...`）。

## 0. 架构与边界

- [x] WebView 加载服务端网页，登录、媒体库、详情、设置复用现有 Web UI
- [x] Python 不重复登录、不保存账号密码、不持有网页 Cookie
- [x] 网页通过 `window.StrmActionNative` 调用 Python：
  - `isDesktop()` / `version()`
  - `playItem(payloadJson)`：把 `/api/play` 返回的播放数据交给 Python
  - `openSettings()` / `stopPlayback()` / `quit()`
- [x] Python 只做：校验 payload、找到 mpv、启动 mpv、设置 headers、上报进度
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
- [x] 设置页显示“当前为桌面端，由本机 mpv 播放”，提供“打开桌面端设置”
- [x] `npm run build` 通过

## 3. desktop/ 工程基础

- [x] `pyproject.toml`、`requirements.txt`
- [x] `src/strmaction_desktop/` 包结构
- [x] 版本号、应用名 `StrmAction`
- [x] 配置目录（Windows `%APPDATA%` / macOS `Application Support`）
- [x] 配置读写：`server_url`、`mpv_path`、窗口尺寸、日志级别
- [x] 启动参数：`--server`、`--mpv`、`--settings`、`--debug`
- [x] 首次启动进入设置页；保存后加载服务端网页

## 4. 配置与设置页

- [x] 本地 `settings.html`：服务器地址、mpv 路径、版本
- [x] 保存配置并重新加载网页
- [x] 选择 mpv 可执行文件（pywebview 文件对话框）
- [x] 修改服务器地址后刷新 WebView
- [x] 配置原子写入，避免半截文件
- [x] 配置校验：只接受 http/https、去除尾部 `/`

## 5. mpv 发现与启动

- [x] 查找顺序：配置路径 → 自带 `vendor/mpv/<platform>/` → PATH → 常见安装路径
- [x] macOS：`/Applications/mpv.app/Contents/MacOS/mpv`、Homebrew 路径
- [x] Windows：`%ProgramFiles%\mpv\mpv.exe`、`%LOCALAPPDATA%\Programs\mpv\mpv.exe`
- [x] 找不到 mpv 时给出可操作提示（设置页选择/安装）
- [x] 启动参数：`--input-ipc-server`、`--no-terminal`、`--force-window`、`--idle`、`--start`
- [x] Windows 命名管道 / macOS Unix socket，权限 0700
- [x] 连接 IPC 带重试与超时
- [x] 播放结束/退出时清理进程与临时 socket（不残留）

## 6. 请求头与字幕

- [x] 使用服务端 `headers` 全量设置，不只 User-Agent
- [x] 通过 IPC 设置 `http-header-fields`，避免出现在进程命令行
- [x] headers 只接受字符串键值；大小/数量限制
- [x] 字幕 URL 拼接服务器绝对地址
- [x] `sub-add` 加载字幕（首个 select，其余 auto）
- [x] headers/URL/token 不写日志

## 7. IPC 与播放状态

- [x] JSON IPC 客户端：命令、事件、缓冲区
- [x] 观察 `time-pos`、`duration`、`pause`、`eof-reached`
- [x] `file-loaded` 后加载字幕
- [x] 暂停/seek/退出时立即 flush 进度
- [x] 播放器异常退出时停止上报、提示用户
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
- [x] WebView 导航限制在配置的服务器 origin
- [x] JS Bridge 只接受合法 payload，不执行任意命令
- [x] mpv 路径只允许可执行文件，不拼接 shell
- [x] IPC 本地 socket/pipe，随机名，权限 0700
- [x] 日志脱敏：URL/token/headers 不落盘
- [x] HTTPS 证书校验；自签名需用户显式信任（后续）
- [x] 不保存密码/Cookie；只保存服务器地址与 mpv 路径

## 10. 图标与打包

- [x] `assets/icon.svg`（来自网站 favicon）
- [x] `assets/icon.png` 512×512
- [x] `assets/icon.ico`（Windows）
- [x] `assets/icon.icns` 生成脚本（macOS）
- [x] PyInstaller spec：`console=False`，包含 assets/settings.html/vendor mpv
- [x] Windows 构建脚本
- [x] macOS `.app` 构建脚本、签名/公证说明
- [x] `scripts/prepare_mpv.py`：把 mpv 二进制放入 `vendor/mpv/<platform>/`
- [x] README：运行、配置、构建、mpv 准备、限制

## 11. 测试

- [x] 配置校验单元测试
- [x] payload 校验/脱敏单元测试
- [x] headers 格式化单元测试
- [x] mpv 发现顺序单元测试
- [x] 进度上报 payload/重试/401/单飞测试（httpx.MockTransport）
- [x] Python `compileall` 通过
- [x] `pytest desktop/tests` 通过
- [x] 前端 `npm run build` 通过
- [x] 服务端 `pytest` 通过
- [x] 手工：设置保存、WebView 启动
- [ ] 手工：无 mpv 时的播放错误提示
- [ ] 手工：有 mpv 时播放、headers、暂停/退出进度
- [ ] 手工：macOS/Windows 各一次（本轮至少验证当前平台）

## 12. 本轮已实现（方案 A 内嵌与控件改造）

- [x] 视频画面嵌入 StrmAction 主窗口（PySide6 / mpv wid / 无外部窗口）
- [x] 仿伴侣 App 自制控件（BufferedSeekBar 三层缓冲条、ControlsOverlay 顶底栏、PlayerDrawer 40% 抽屉）
- [x] 全功能键盘快捷键与“长按右方向键倍速”状态机
- [x] 自动连播与选集切换
- [x] 单元测试扩充：41 passed

## 13. 明确不在本轮范围

- [ ] 内置 mpv 二进制实际下载并提交到仓库（提供准备脚本/打包路径）
- [ ] 托盘常驻、开机自启、自动更新
- [ ] macOS 公证/Windows 代码签名（提供构建说明）
- [ ] 多账号/多设备管理、离线进度队列持久化

## 验收标准

1. 服务端 `direct` 模式可用，普通用户可拿到自己有权访问条目的播放数据。
2. 桌面端启动后能配置服务器地址并加载网页，登录成功。
3. 网页点播放时，桌面端启动本机 mpv，自动设置服务端下发的全部请求头。
4. 播放中按间隔上报进度，暂停/退出/播完立即补写；401 有明确提示。
5. 无 mpv 时不崩溃，提示用户选择或安装。
6. 源码全部位于 `desktop/`，不影响其他模块的既有行为。


## 验证记录（2026-10-20 / Windows）

- 环境：Windows 11，uv 0.12.0，Python 3.12.13（`desktop/.venv`），pywebview 6.2.1。
- `desktop` 单元测试：**25 passed**。
- 服务端全量测试：**58 passed**（含 `direct` 模式）。
- 前端 `npm run build` 通过。
- Playwright 验证：
  - 桌面设置页：8 项断言通过（预填、mpv 检测、选择、URL 校验、保存）。
  - 网页 + 桌面桥：15 项断言通过（`direct` 请求、payload 交付、设置页桌面提示）。
- 应用启动：使用临时 `APPDATA` 启动了 WebView 设置窗口，进程稳定。
- PyInstaller 构建：`dist/StrmAction/StrmAction.exe` 构建成功；打包后的 `--version`、`--settings` 启动冒烟通过。
- 进度上报节流：模拟 20Hz 位置更新 7 秒只有 4 次请求、约 1.25KB，折合约 0.0014 Mbps；已修复原先按每个 `time-pos` 事件唤醒的问题。
- 未验证：本机未安装 mpv，未做真实视频播放/headers/进度回写；macOS 构建/公证未验证。
- 未提交：`vendor/mpv/` 二进制（按许可证策略由构建机准备）。
