# StrmAction Companion（Android 伴侣 App）

**手机优先、兼容电视**的 Android 壳：一个 WebView 加载 StrmAction 网页，
播放交给原生 **Media3 / ExoPlayer**（v0.8 默认路径），外部 mpv 作为兜底。

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

## 已构建产物

`strmaction-companion-v1.4.apk`（本目录）已签名，可直接安装（版本 1.4 / versionCode 5）：

```bash
adb install -r strmaction-companion-v1.4.apk

# 电视 / 盒子
adb connect <TV_IP>:5555
adb install -r strmaction-companion-v1.4.apk
```

签名证书为本地生成的演示 keystore（`release.keystore`，口令 `strmaction`，
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
  --out strmaction-companion-v1.apk app-release-aligned.apk
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
                 └─ 失败 → 弹窗 → 外部 mpv 兜底
```

### 播放控件

底部控制条统一放置全部操作：

- **选集**：列出同一部剧的全部剧集（跨季），当前集与已看集有标记，选中即切换；
- **倍速**：0.5x / 0.75x / 1x / 1.25x / 1.5x / 2x / 3x，按钮显示当前倍速；
- **全屏**：底部右下角，进入后隐藏系统栏并横屏，可再次点击退出；
- 上一集 / 播放暂停 / 下一集、进度条与时间同样在底部；
- **锁定**：右侧中间的「锁」按钮，锁定后隐藏全部控件，只保留「解锁」入口；
  再按一次恢复。返回键按「解锁 → 退全屏 → 收起控件 → 退出」逐级处理。

### 关键实现

- 数据源：Media3 `OkHttpDataSource` + `setDefaultRequestProperties(headers)`；
  OkHttp 自动跟随 302（AList → 百度 CDN）、支持 HTTP/2/TLS 重试，云端媒体库兼容性更好；
- 换库/换源时自动重建播放器，保证请求头跟随当前媒体库；
- 心跳失败不阻塞播放：本地队列最多 3 条，下一跳补发；`401` 提示重新播放；
- 进度钳制：`0 <= position <= duration`；暂停、`onStop`、`STATE_ENDED` 各补写一次；
- 字幕：内封轨道切换、外挂 `.srt/.ass`（服务端下发 URL，带 `?pt=` 凭证）；
- 手机画中画：`onUserLeaveHint` 自动进入 PiP（Android 8+）；
- JS 桥的所有 WebView 访问都切回主线程（否则会抛
  `A WebView method was called on thread 'JavaBridge'`，网页显示「播放失败」）。

## 外部 mpv 兜底（E.6 的 6 个坑）

| # | 处理 |
|---|---|
| 1 | `setDataAndType(uri, "video/any")`，兼容无扩展名的 SmartStrm 地址 |
| 2 | `setPackage("is.xyz.mpv")`，绝不弹系统选择器 |
| 3 | 使用 `registerForActivityResult`，**不添加** `FLAG_ACTIVITY_NEW_TASK` |
| 4 | Manifest 声明 `<queries><package android:name="is.xyz.mpv"/></queries>` |
| 5 | 分支包名不同（mpvKt 等）→ 首次设置页可改 |
| 6 | `onResume` 里 `webView.requestFocus()`，避免遥控器焦点丢失 |

外部 mpv 的 `mpv.conf`：

```ini
http-header-fields=User-Agent: pan.baidu.com,Referer: https://pan.baidu.com/
cache=yes
demuxer-max-bytes=256MiB
```

## 网页上传支持

网页里的「上传海报 / 上传背景」通过 `WebChromeClient.onShowFileChooser` 调起系统
文件选择器；不需要额外存储权限（使用 SAF/Content URI）。

## 目录

```
app/src/main/java/top/strmaction/companion/
├─ MainActivity.kt      # WebView 壳：滚动、TV/手机适配、文件选择、生命周期
├─ JsBridge.kt          # window.StrmActionNative（主线程切换 + 来源校验）
├─ PlayerActivity.kt    # Media3 播放器、心跳、连播、字幕/音轨/倍速、PiP
├─ ProgressReporter.kt  # play_token 进度上报 + 失败队列
├─ PlayApi.kt           # POST /api/play/{id} 解析
├─ PlayInfo.kt          # 播放参数 + Device 检测
├─ MpvFallback.kt       # 外部 mpv intent
└─ SetupActivity.kt     # 服务器地址 / mpv 包名
```

## 已知限制

- 复杂 ASS 特效字幕无法还原（Media3 只支持基础样式），需要原样显示请用 mpv；
- 杜比视界 P5 在非 DV 设备上颜色异常，属于设备能力限制；
- 外部 mpv 路径只能拿到退出时的进度，断电/强杀会丢最后一段；
- 电视端浏览器内核由系统 WebView 提供，Android 7 以下不再保证体验。
