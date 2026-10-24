# 统一客户端实施与验收

本次代码在 `codex/unified-client` 分支实施。媒体库继续使用云端 Web，四个平台共用 `client_flutter/` 的设置、桥接、播放器控件和进度队列；移动端保留 Media3 / KSPlayer 的原生播放与系统服务。

## 构建和安装

[Clients CI](https://github.com/pcsensor/strmaction/actions/workflows/clients.yml) 在 push、PR 和手动触发时运行。检查包含后端回归、Web 类型检查与生产构建、Flutter 分析与公共测试、Android 原生信任 / 重定向测试。四端构建均成功后，汇总 job 才成功。

| Artifact | 内容 | 签名状态 |
|---|---|---|
| StrmAction-Android | 可安装测试 APK、Release APK | 未配置原密钥时 Release 明确标为 unsigned |
| StrmAction-iOS | 未签名 IPA | 下载后使用既有重签安装工具 |
| StrmAction-windows | exe、DLL、资源完整 ZIP | 未签名 |
| StrmAction-macos | 完整 .app ZIP | ad hoc；尚未做 Developer ID 公证 |

每个包附 `build-info.json`，记录提交、CI 运行、工具链与签名状态，并列出包的 SHA-256。Artifacts 保留 30 天。用户本地不需要 Flutter、Android、Xcode、Windows SDK，源码生成和编译都在 runner 完成。

工具链固定 Flutter 3.47.0 / Dart 3.13；Android 使用 JDK 17、AGP 8.11.1、Kotlin 2.2.20、Gradle 8.14，保持与稳定版 WebView 插件兼容；iOS KSPlayer 固定 2.3.4。Windows 稳定版 WebView 插件缺少原生证书挑战派发，CI 应用仓库内的小范围 WebView2 回调补丁；默认拒绝，只有共享严格验证回调通过才接受，并清除会话中的证书例外缓存。最低系统为 Android 7、iOS 16、Windows 10、macOS 12。

用户已选择本轮先验收测试包，正式升级签名后续处理。测试 APK 不能覆盖以其他密钥签名的旧正式应用；当前仓库及 CI 没有原发布密钥，不能据此宣称完成旧正式包覆盖升级验证。

后续沿用原 Android 身份时，在仓库 Actions Secrets 配置 `ANDROID_KEYSTORE_BASE64`、`ANDROID_KEYSTORE_PASSWORD`、`ANDROID_KEY_ALIAS`、`ANDROID_KEY_PASSWORD`，重新运行 CI 即可。缺少这些值时不会生成或替换正式签名。测试签名单独缓存以支持测试包之间升级。

## 设置和行为

- **播放模式**：本机按服务器 + 账号保存的覆盖 → 账号默认 → 全局默认。公开选项仅内部播放与复制链接；旧模式归一化到内部播放。普通浏览器内部播放禁用，明确提示使用 App。
- **媒体版本**：Web 选中的 `media_file_id` 经共享桥接传到播放 API，字幕下载同样绑定该版本；复制链接返回该版本的直链。
- **连播**：自动连播只使用服务端 `next_item_id`，跳过已看、缺失、删除、无有效媒体的集数；手动上下集按相邻可播放顺序。课程 / 家庭视频按 Web 自然顺序，不跳过已看课程。
- **进度**：暂停、后台、seek、结束、关闭、切集补报；退出先冻结播放、发送最终快照，再释放引擎。发送前持久化，确认后移除；失败在下次启动恢复，失效凭证停止重试。关闭播放器后触发 Web 进度刷新事件。
- **缓存**：设备覆盖 → 云默认 → 平台原预算。默认预读 Android 512 MB、iOS / 桌面 128 MB；磁盘预算 2048 MB。0 分别关闭预读或落盘；只保留当前视频，切集 / 退出删除。Android 使用原 Media3 LRU；iOS 使用原字节范围缓存；桌面使用有硬容量上限的字节块 LRU，避免 mpv 追加文件无限增长。范围缓存适用于支持 HTTP Range 的渐进媒体；桌面 HLS / DASH 或不支持 Range 的来源使用原生流式传输与内存缓冲；iOS 继承原有渐进媒体缓存链路，HLS / DASH 兼容性需另按片源验证，不能宣称所有格式都落盘。
- **TLS**：设置中导入自签名根 CA（PEM，支持多根），API / 媒体保持证书链与主机名校验。WebView 的私有证书挑战还要与独立严格 TLS 连接的证书一致才能接受。旧“允许自签名”布尔开关不再放行任何证书。

## 升级迁移

Android / iOS applicationId 与 bundle identifier 均保留 `top.strmaction.companion`；桌面身份和配置目录保留。允许重新登录。Android 从原 SharedPreferences、iOS 从 UserDefaults 迁移服务器和本地预算，iOS 原 CA 根信任库一并迁移。

迁移与覆盖安装依赖相同的签名身份；卸载旧应用会清除其沙盒数据，应在有原签名的升级包上验证自动迁移。旧 Android / 桌面的“信任任意证书”开关没有证书内容，不能迁移为 CA；私有站点需导入对应根 CA。

原 `strmaction-ios` 仓库保持历史与独立构建。此次仅将所需原生核心导入主仓库，完成真机迁移验收后再停止独立开发，不提前归档。

## 验收记录

CI 结果以对应提交的工作流和安装包为准。编译通过不等同于设备播放验收；以下项目需要下载安装包后记录结果，无需本地编译。

| 项目 | Android 手机 | Android TV | iPhone / iPad | Windows / macOS |
|---|---|---|---|---|
| 登录、切服务器 / 账号、本机覆盖与清除 | 待设备验收 | 待设备验收 | 待设备验收 | 待设备验收 |
| 所选版本、带 UA / Referer / 302 的真实片源 | 待设备验收 | 待设备验收 | 待设备验收 | 待设备验收 |
| 自动 / 手动上下集、课程顺序、超过 200 集 | 待设备验收 | 待设备验收 | 待设备验收 | 待设备验收 |
| 暂停、后台、退出、断网上报、返回 Web 刷新 | 待设备验收 | 待设备验收 | 待设备验收 | 待设备验收 |
| 音轨、内封字幕、外挂 SRT / ASS / VTT | 待设备验收 | 待设备验收 | 待设备验收 | 待设备验收 |
| PiP、后台音频、系统播放控制 | 待设备验收 | 按设备系统能力 | 待设备验收 | 沿用桌面行为 |
| 手势 / 遥控焦点 / 桌面键盘与 DPI | 待设备验收 | 待设备验收 | 待设备验收 | 待设备验收 |
| CA 导入、错误主机名拒绝、证书轮换 | 待设备验收 | 待设备验收 | 待设备验收 | 待设备验收 |
| 缓存容量、回拖复用、退出清理、旧设置迁移 | 待设备验收 | 待设备验收 | 待设备验收 | 待设备验收 |
