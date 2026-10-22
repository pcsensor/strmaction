# StrmAction Companion（Android 伴侣 App）

**手机优先、兼容电视**的 Android 壳：一个 WebView 加载 StrmAction 网页，
播放交给原生 **Media3 / ExoPlayer**（v1.3 起不再有外部播放器兜底）。

体积约 5 MB，不含网络代理、不含刮削、不中转视频流。

## 手机与电视

| | 手机 | 电视 / 盒子 |
|---|---|---|
| 布局 | 跟随系统竖屏/横屏，保留状态栏 | 自动横屏、隐藏系统栏、`?tv=1` 10-foot 布局 |
| 操作 | 触摸滚动（WebView 原生手势，不做任何拦截） | 遥控器方向键 / 确定 / 返回 |
| 播放 | 内置 Media3，支持画中画 | 内置 Media3，左右键 ±10s、上下键菜单 |
| 服务器设置 | 设置页「播放器 → 伴侣 App → 服务器设置」 | 长按遥控器「确定」 |

> 触摸设备永远按手机处理：即使 ROM 声明了 `android.software.leanback`，
> 只要有触摸屏就不会切入电视模式。

## 安装与部署

构建生成的 APK 可直接安装到手机或电视（需处于同一局域网）：

```bash
adb install -r app/build/outputs/apk/release/app-release.apk

# 电视 / 盒子
adb connect <TV_IP>:5555
adb install -r app/build/outputs/apk/release/app-release.apk
```

签名证书可使用本地生成的演示 keystore（`release.keystore`，口令 `strmaction`，
alias `strmaction`）。正式分发请替换为你自己的 keystore；更换签名后需先卸载旧版。

## 构建

需要 JDK 17 + Android SDK 34。

```bash
cd companion

# 首次：生成 Gradle Wrapper（仓库不包含 wrapper jar）
gradle wrapper --gradle-version 8.7

./gradlew assembleRelease
```

产物在 `app/build/outputs/apk/release/`。用 Android Studio 打开 `companion/` 也可以直接构建。

### 签名

```bash
keytool -genkeypair -v -keystore release.keystore -alias strmaction \
  -keyalg RSA -keysize 2048 -validity 10000

zipalign -f -p 4 app-release-unsigned.apk app-release-aligned.apk
apksigner sign --ks release.keystore --ks-key-alias strmaction \
  --out app-release.apk app-release-aligned.apk
```

## 首次启动

1. 输入服务器地址（如 `http://192.168.1.10:8080`，公网建议 `https://你的域名`，
   见 [云服务器部署指南](../docs/deploy-cloud.md)），点「测试连接」；
2. 「保存并进入」后加载同一套网页，登录一次即可（Cookie 由 WebView 保存）；
3. 电视上长按「确定」可随时重新配置；手机可在网页「设置 → 播放器 → 伴侣 App →
   打开 App 设置」重新进入配置页。

## 播放流程

```
网页点播放
  └─ window.StrmActionNative.play(itemId)          ← 只传 id，不传 URL/token
       └─ 原生：POST /api/play/{itemId}（带 WebView Cookie）
            └─ PlayerActivity（Media3）
                 ├─ 按库下发的 headers 请求片源（UA/Referer）
                 ├─ resume_ms 续播
                 ├─ 每 5 秒 POST /api/items/{id}/progress（Bearer play_token）
                 ├─ 播完 → 上报 finished + 用 next_item_id 无缝连播
                 └─ 失败 → 弹窗说明原因 + 重试/返回
```

### 播放控件与手势

播放器全面重构为现代主流播放器交互样式：

- **现代矢量图标**：返回、播放/暂停、上一集/下一集、选集、倍速、全屏、锁屏、画中画均采用精细矢量图标与现代扁平化布局；
- **中心大按钮**：屏幕正中央悬浮播放/暂停半透明按钮，状态清晰直观；
- **底部控制栏**：
  - 上方全宽精致进度条，支持实时拖拽预览时间；
  - 下方左侧排列「播放/暂停」、「上一集」、「下一集」、当前/总时长与实时网速；
  - 下方右侧排列「选集」、「倍速」及「全屏」切换；
  - **窄屏自动换行**：`screenWidthDp < 600`（竖屏手机）时，「选集 / 倍速」下移到第二行
    右对齐，避免把「全屏」按钮挤出屏幕；横屏与电视仍是单行；
- **40% 侧滑抽屉（全面替代原生丑陋弹窗）**：
  - **选集**：点击后从右侧平滑滑出抽屉面板，占据屏幕 40% 宽度，点击左侧 60% 遮罩区域即可即刻收回；卡片式分集列表，当前播放集高亮金黄色标签并带 `▶` 标志，已看集打勾 `✓`；
  - **倍速面板**：从右侧平滑滑出，单列展示 `0.5x`~`3.0x` 倍速，直接集成长按倍速配置；
  - **右上角更多菜单**：右侧滑出暗黑毛玻璃面板，包含字幕、音轨切换、倍速与下一集；
- **手势控制**：
  - 单击唤起/收起控件（播放时 4.5s 自动淡出）；
  - 双击屏幕左侧 35% 区域快退 10 秒（居中提示 `⏪ 快退 10 秒`）；
  - 双击屏幕右侧 35% 区域快进 10 秒（居中提示 `⏩ 快进 10 秒`）；
  - 双击屏幕中间区域切换播放/暂停；
- **长按倍速**：
  - 在屏幕任意区域长按，触发触觉震动反馈，实时以指定倍速极速播放，顶部浮现 `▶▶ 2.0x 快速播放中`；
  - 松手即恢复原播放速度；
  - 在倍速菜单及设置中支持自定义长按倍速（可选 1.5x / 2.0x / 2.5x / 3.0x，自动保存）；
- **退出与返回**：左上角返回按钮在全屏/非全屏模式下均直接退出播放页面；返回键在抽屉打开时优先关闭抽屉。

### 关键实现

- 数据源：Media3 `OkHttpDataSource` + `setDefaultRequestProperties(headers)`；
  OkHttp 自动跟随 302（AList → 百度 CDN）、支持 HTTP/2/TLS 重试，云端媒体库兼容性更好；
- 直连 15 秒仍未就绪时自动逐级切换传输参数（保留 pan.baidu.com UA；首轮 Range: bytes=0-、identity、HTTP/1.1；后续 HTTP/2）；
  仍失败则明确提示「连接网盘超时」并提供「重试 / 返回」，不再无限转圈；
- 换库/换源时自动重建播放器，保证请求头跟随当前媒体库；
- 心跳失败不阻塞播放：本地队列最多 3 条，下一跳补发；`401` 提示重新播放；
- 进度钳制：`0 <= position <= duration`；暂停、`onStop`、`STATE_ENDED` 各补写一次；
- 字幕：内封轨道切换、外挂 `.srt/.ass`（服务端下发 URL，带 `?pt=` 凭证）；
- 手机画中画：`onUserLeaveHint` 自动进入 PiP（Android 8+）；
- JS 桥的所有 WebView 访问都切回主线程（否则会抛
  `A WebView method was called on thread 'JavaBridge'`，网页显示「播放失败」）。

## 播放缓存与缓冲进度

三个概念分开，设置页里对应两个可填项：

| 概念 | 值 | 说明 |
|---|---|---|
| 内存缓冲 | 固定 64MB | 播放器解码抖动缓冲，不可调；堆过小时按一半收敛 |
| 缓冲大小 | 默认 512MB，0 关闭 | 实时预拉取窗口，决定「往后提前拉多少」 |
| 磁盘缓存上限 | 默认 2048MB，0 关闭 | 落盘容量，超出按 LRU 淘汰 |

预拉取的实际窗口 = `min(缓冲大小, 磁盘上限)`（落不了盘就白拉）；磁盘为 0 时预取也关闭。

- **内存缓冲（固定 64MB）**：`DefaultLoadControl.setTargetBufferBytes(64MB)`。
  `minBufferMs` 与 `maxBufferMs` 统一给到 6 小时兜底值，拉满后消耗多少补多少，
  不再出现「跌到 5 秒再一次性拉满 60 秒」的锯齿。
- **预拉取**：`PlaybackPrefetcher` 后台单线程从播放器已缓冲的末端继续往前拉，直到
  「当前播放位置 + 窗口 MB」，播放与暂停都跑；播放器正在缓冲时让路，先保证不断流。
- **磁盘缓存**：
  - 数据源链 `DefaultDataSource → CacheDataSource → RedirectResolvingDataSource → OkHttp`，
    `CacheDataSink` 把拉取过的字节按 5MB 分片落盘，seek 回已拉取区间直接读盘；
  - `FLAG_BLOCK_ON_CACHE | FLAG_IGNORE_CACHE_ON_ERROR`：先查盘再决定是否走网络，
    写盘失败（磁盘满/IO 错）自动降级为纯网络播放；
  - 目录 `<externalCacheDir>/playback/s-<ts>/`，每次进入播放新建会话；
  - 退出播放：release 后在后台线程用 `SimpleCache.delete()` 删掉会话目录与 SQLite 索引；
  - 切集：`Cache.removeResource(上一集播放地址)`，只保留当前集；
  - 上限还会按「可用空间 − 1GB」收敛，收敛后不足 256MB 时直接关闭缓存。
- **进度条（缓存线置顶）**：8dp 全高圆角轨道（触摸区 32dp）。已播放段整段填金橙、全高
  保留；**已缓存画成 2.5dp 白色细线，压在最上层并穿过已播放区域**，按真实缓存区间分段
  （缓存有洞就断开）；播放头是 3.5×16dp 白色竖线，压在最上层、上下各露出轨道 4dp。
- **缓存线只增不减**：`PlayerActivity` 每 500ms 取「内存已缓冲区间 + `SimpleCache` 里真实
  存在的 span」的并集，合并后与历史累积再做并集，从不删减；换集才清空。所以往回拖时
  不会出现先塌掉再涨回来的闪跳，线条永远只往右长。另外进度条在 seek 后会把播放位置钉在
  目标值（追上或 1.5 秒超时），避免拇指回弹。
- **网速**：控制栏时间右侧显示实时网速。`NetworkSpeedMeter` 挂在 OkHttp 工厂上
  （缓存层之下），只统计真正走网络的字节，命中磁盘时自然归零；500ms 采样一次并做
  非对称平滑（上升快、下降慢）。
- **边界**：预取需要 `Content-Length`（渐进式 MP4）；HLS 分段拿不到整片长度时自动跳过
  预取，播放器仍按内存缓冲正常播放。缓存策略全部由 App 设置页控制。

## 播放失败的处理

v1.3 起移除了「外部 mpv 兜底」（`MpvFallback`、`playExternal` 桥、设置页的 mpv 包名、
`<queries>` 里的 `is.xyz.mpv` 全部删除），失败时改为：

1. 在弹窗里给出可读原因（Media3 错误名 + 底层 message）；
2. 提供「重试」（从当前位置重播）与「返回」；
3. 用户可回到列表改用桌面端或网页端观看。

## 网页上传支持

网页里的「上传海报 / 上传背景」通过 `WebChromeClient.onShowFileChooser` 调起系统
文件选择器；不需要额外存储权限（使用 SAF/Content URI）。

## 目录

```
app/src/main/java/top/strmaction/companion/
├─ MainActivity.kt      # WebView 壳：滚动、TV/手机适配、文件选择、生命周期
├─ JsBridge.kt          # window.StrmActionNative（主线程切换 + 来源校验）
├─ PlayerActivity.kt    # Media3 播放器主界面、手势、全屏与生命周期
├─ player/              # 播放器解耦模块
│  ├─ PlayerDrawer.kt   # 40% 抽屉交互与集数渲染（选集/倍速/更多）
│  ├─ BufferedSeekBar.kt # 进度条（全高金橙 + 置顶缓存细线 + 竖线播放头）
│  ├─ PlayerTrackHelper.kt # 音轨与字幕轨道管理
│  ├─ PlayerSpeedHelper.kt # 倍速切换与长按极速播放管理
│  └─ PlayerUiHelper.kt # UI 样式与时间格式化
├─ ProgressReporter.kt  # play_token 进度上报 + 失败队列
├─ PlayApi.kt           # POST /api/play/{id} 解析
├─ PlayInfo.kt          # 播放参数 + Device 检测
├─ PlaybackCache.kt     # 内存缓冲固定值 / 缓冲大小 / 磁盘上限设置
├─ PlaybackDiskCache.kt # 会话级磁盘缓存（SimpleCache / 退出清理）
├─ PlaybackPrefetcher.kt # 后台磁盘预取（按缓冲大小提前拉取后续内容）
├─ NetworkSpeedMeter.kt # 实时网速统计（TransferListener + 平滑采样）
└─ SetupActivity.kt     # 服务器地址 / 缓冲大小 / 磁盘缓存上限 / 自签名证书
```

## 已知限制

- 复杂 ASS 特效字幕无法还原（Media3 只支持基础样式），需要原样显示可在桌面端观看；
- 杜比视界 P5 在非 DV 设备上颜色异常，属于设备能力限制；
- 个别编码（DTS/TrueHD 音轨、部分 HEVC 10bit）依赖设备解码能力；
- 电视端浏览器内核由系统 WebView 提供，Android 7 以下不再保证体验。


