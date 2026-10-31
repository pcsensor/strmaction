# StrmAction 统一客户端

Android、iOS、Windows、macOS 共用 Flutter 的 Web 外壳、设置、播放控件、选集规则和进度队列。媒体库复用服务器 Web；内部播放保留 Media3（Android）、KSPlayer（iOS）与 media_kit（桌面）内核。

客户端只提供**内部播放 / 复制链接**。普通浏览器的内部播放不可用。账号默认值适用于全部 App，本机可按服务器和账号覆盖。

## 构建与下载

打开 [Clients CI](https://github.com/pcsensor/strmaction/actions/workflows/clients.yml)，选择成功运行，在 Artifacts 下载 Android APK、iOS IPA、Windows ZIP、macOS ZIP。每个包附带提交号、签名状态、构建来源和 SHA-256。

本地不需要 SDK。Flutter 3.47.0、Android、Xcode、Windows SDK、原生项目生成、依赖解析、分析、测试和 Release 构建都在 CI 执行。`platform/` 中的原生桥接在 CI 生成的 Android / iOS runner 中编译；桌面 runner 保持既有应用身份。

最低系统版本为 Android 7 / API 24、iOS 16、Windows 10、macOS 12。Windows 运行需要 WebView2 Runtime。

正式 APK 使用新生成并固定保存在 CI Secrets 的发布密钥；旧签名版 / 测试版需卸载后首次安装，后续正式包可持续覆盖升级。测试 APK 使用独立测试签名。未签名 IPA 延续原有重签安装流程。正式签名配置、设置迁移、验收矩阵见[迁移说明](../docs/CLIENT_MIGRATION.md)。

## 功能与设置

- 本机缓存覆盖 → 云端默认 → 平台原默认预算。预读与磁盘容量分开；0 关闭相应层；退出 / 切集清理当前视频缓存。
- 设置页粘贴 PEM 根 CA。API、网页和媒体连接都校验证书链和主机名，支持多张根 CA；旧“允许自签名”开关不再生效。
- 暂停、后台、拖动、结束、退出和切集补报进度。待发送记录按服务器和账号隔离；重新登录同一账号后尝试恢复。过期、账号不明或与其他会话冲突的记录保留在本机并提示，避免覆盖较新的进度。
- 媒体跨来源重定向只转发兼容性请求头，不转发凭证；HTTPS 回源不允许降级。桌面直连回退无法安全约束带凭证的重定向时会拒绝播放，需使用支持安全缓存传输的片源。
- 自动连播使用服务端跳过已看的下一集；手动上下集按相邻顺序；课程按自然顺序播放。
- 手机支持双击快进退、长按倍速、拖动进度 / 亮度 / 音量、锁定和画中画；Android TV 支持方向键、确认 / 返回、音轨与选集抽屉；桌面保留原有快捷键。

桌面命令行参数：`--server URL`、`--settings`、`--debug`、`--version`。

## 测试位置

下载策略按平台区分：Android / iOS 使用 2–4 路 Range 并发与 4–8 MiB 分段；Windows / macOS
使用一条顺序回源流 + 一条 ≤4 MiB 的头部/moov 探针，读满预读窗口即暂停，seek 命中缓存
不触碰源站。详见[下载策略](../docs/playback-downloads.md)与[桌面传输重设计](../docs/desktop-playback-transport-redesign.md)。

`test/` 覆盖设置 / payload、长播放列表、窄屏控件、进度退出与重试队列、私有 CA 与主机名校验。`platform/android/test/` 验证私有 CA、错误主机名、叶子证书拒绝和重定向请求头。设备专属行为按迁移说明下载 CI 安装包验收。
