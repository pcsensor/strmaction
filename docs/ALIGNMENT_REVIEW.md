# StrmAction 跨端对齐检查（2026-10-24）

检查范围为本地两个仓库的云后端、云页面、Android 伴侣、Flutter Windows/macOS 桌面端和 iOS 伴侣。发现 14 项需要修复或明确产品规则的不一致，主要集中在播放参数、自动连播、进度同步和设置生效范围。这是迁移前的历史检查记录；以下路径和行号均固定到检查基线，当前实施见 [CLIENT_MIGRATION.md](CLIENT_MIGRATION.md)。

审查版本：`strmaction` 为 `a66ffad2f51fd1f66915a83b37a2cb17c68d1fbe`；`strmaction-ios` 为 `40cb910e155b28f8c15ef0d2721d6f5b6c6a2ea6`。

验证结果：后端现有测试 **62 passed**；前端 `npm run build`（含 TypeScript 检查）通过。额外用隔离数据库运行了接口样例，并编译运行了仓库中的 Swift 播放响应模型和进度引擎。完整原生 App、真实媒体播放、画中画和真机操作没有执行；下文分别标明运行复现与静态确认。

| 对齐项 | 云后端 / 云页面 | Android | 桌面 | iOS |
|---|---|---|---|---|
| 播放响应字段、毫秒单位、Bearer 进度凭证 | 基本一致 | 已接入 | 已接入 | 当前模型可正确解码真实响应 |
| 网页选择媒体版本 | 支持 `media_file_id` | 桥接丢失 | 正常透传 | 桥接丢失 |
| 个人播放方式 | 页面与接口支持 | 不执行响应中的 mode | 固定 direct，页面已有说明 | 固定请求 builtin |
| 下一集跳过已看 | 下发 `next_item_id` | 遵循 | 被相邻条目覆盖 | null 时回退到已看条目 |
| 课程顺序 | 详情自然排序 | 播放列表使用另一规则 | 同左 | 同左 |
| 退出 / 暂停即时进度 | 支持 | 已接入 | 退出补报被拦截 | 暂停缺补报；失败队列丢记录 |
| 返回网页刷新进度 | 监听统一事件 | 发送事件 | 发送事件 | 未发送 |
| 切换服务器 | 各端本地配置 | 重启主页面 | 重新加载页面 | WebView 不加载新地址 |
| 音轨 / 内封字幕选择 | 来自播放内核 | 有 | 有 | 缺入口 |

建议先修复媒体版本、连播选择、进度丢失和服务器切换，再处理设置项与功能入口；每个修复应补覆盖实际触发条件的回归检查。

**1. Android / iOS 丢失用户选择的媒体版本。**

网页详情正确把 `selectedMedia.id` 交给播放入口，但伴侣分支只调用 `bridge.play(itemId)`。Android 的桥和 API、iOS 的桥和 API 也只继续传条目 ID，没有 `media_file_id`，因此服务器重新选默认文件。浏览器与桌面端会正常带上所选文件，出现同一页面在不同平台播放不同版本的情况。

依据：[详情播放入口](https://github.com/pcsensor/strmaction/blob/a66ffad2f51fd1f66915a83b37a2cb17c68d1fbe/frontend/src/pages/DetailPage.tsx#L219)、[伴侣分支](https://github.com/pcsensor/strmaction/blob/a66ffad2f51fd1f66915a83b37a2cb17c68d1fbe/frontend/src/hooks/useStartPlayback.ts#L75)、[Android 请求体](https://github.com/pcsensor/strmaction/blob/a66ffad2f51fd1f66915a83b37a2cb17c68d1fbe/companion/app/src/main/java/top/strmaction/companion/PlayApi.kt#L38)、[iOS 请求体](https://github.com/pcsensor/strmaction-ios/blob/40cb910e155b28f8c15ef0d2721d6f5b6c6a2ea6/Sources/Network/PlayApi.swift#L147)。

运行验证：同一个条目显式指定第二个文件返回 `2160p.mp4`，只传条目 ID 返回 `1080p.mp4`；原生参数丢失由上述调用链静态确认。建议扩展兼容桥接参数，让两端将所选文件 ID 一直传到播放 API。

**2. 网页“个人播放方式”在两个伴侣端不按设置执行。**

Android 不显式指定 mode，服务端正确返回用户选择的 `copy` 等模式，但 PlayerActivity 直接用 `play_url` 初始化 ExoPlayer，没有执行响应中的 mode / action。iOS 则默认显式提交 `builtin`，直接覆盖个人偏好，收到响应后也直接呈现播放器。用户在网页保存“复制链接”或 Android 外部播放器后，伴侣仍打开内置播放器。桌面固定 direct 已有专门说明，不属于此问题。

依据：[Android 下发模式解析](https://github.com/pcsensor/strmaction/blob/a66ffad2f51fd1f66915a83b37a2cb17c68d1fbe/companion/app/src/main/java/top/strmaction/companion/PlayApi.kt#L120)、[Android 直接播放](https://github.com/pcsensor/strmaction/blob/a66ffad2f51fd1f66915a83b37a2cb17c68d1fbe/companion/app/src/main/java/top/strmaction/companion/PlayerActivity.kt#L1317)、[iOS 固定模式与响应处理](https://github.com/pcsensor/strmaction-ios/blob/40cb910e155b28f8c15ef0d2721d6f5b6c6a2ea6/Sources/App/StrmActionApp.swift#L104)。

运行验证：账号偏好为 copy 时，Android 形态请求返回 copy，iOS 当前形态请求返回 builtin。建议让原生调度执行服务端模式，或者在伴侣设置页面明确限制为内置播放并移除无效选项。

**3. 桌面退出时最终进度补报一定被提前返回。**

`stop(flush: true)` 先把 `_stopped` 设置为 true，再调用 `flushOnce`；后者进入 `_send` 时立即被 `_stopped` 拦截。退出播放器、切集和关闭 App 都会经过这条路径，最后一次进度不能按设计补写；随后还会强制关闭 HTTP client。静态确认，未运行 Flutter。

依据：[stop 顺序](https://github.com/pcsensor/strmaction/blob/a66ffad2f51fd1f66915a83b37a2cb17c68d1fbe/desktop_flutter/lib/services/progress_reporter.dart#L159)、[发送前置检查](https://github.com/pcsensor/strmaction/blob/a66ffad2f51fd1f66915a83b37a2cb17c68d1fbe/desktop_flutter/lib/services/progress_reporter.dart#L85)、[播放器退出路径](https://github.com/pcsensor/strmaction/blob/a66ffad2f51fd1f66915a83b37a2cb17c68d1fbe/desktop_flutter/lib/player/player_page.dart#L239)。

建议先停定时器、等待在途请求并发送最新快照，再设置停止标记和关闭连接。现有进度测试只检查显式 `flushOnce`，随后用 `stop(flush: false)` 收尾，没有覆盖此路径。

**4. iOS 失败的进度上报被丢弃，队列没有实现补发。**

`drain` 在发送前就 `removeFirst()`；HTTP 500 或网络失败时只 break，没有把失败记录保留或放回队列。切集 / 退出时最后一条记录一旦失败，下一轮也无法重试，和 Android 保留网络失败记录、桌面重新标记 dirty 的行为不同。

依据：[iOS 队列发送](https://github.com/pcsensor/strmaction-ios/blob/40cb910e155b28f8c15ef0d2721d6f5b6c6a2ea6/Sources/Progress/ProgressEngine.swift#L98)。

已运行原仓库 Swift 进度引擎：本地服务器对条目 501 首次返回 HTTP 500，然后提交条目 502。服务器只收到 `501 → 502`，没有失败条目的重试。建议成功后再移除或合并失败快照，并区分可重试错误与凭证失效。

**5. iOS 暂停不会立即补报，暂停期间也不再发送心跳。**

播放状态变化的订阅只更新控件；周期上报又要求 `isPlaying == true`。因此用户在两个心跳之间暂停并停留在播放器时，服务器一直保留暂停前的旧位置，直到其他触发补报的事件发生。Android 在 `onIsPlayingChanged(false)` 补报，桌面暂停按钮也请求 flush。静态确认。

依据：[iOS 状态订阅](https://github.com/pcsensor/strmaction-ios/blob/40cb910e155b28f8c15ef0d2721d6f5b6c6a2ea6/Sources/Player/PlayerView.swift#L216)、[iOS 心跳限制](https://github.com/pcsensor/strmaction-ios/blob/40cb910e155b28f8c15ef0d2721d6f5b6c6a2ea6/Sources/Player/PlayerView.swift#L554)、[Android 状态回调](https://github.com/pcsensor/strmaction/blob/a66ffad2f51fd1f66915a83b37a2cb17c68d1fbe/companion/app/src/main/java/top/strmaction/companion/PlayerActivity.kt#L264)。

建议在已开始的播放会话从播放转为暂停时补报快照，同时避免初次装载状态误写零进度。

**6. iOS 保存新服务器后，网页仍停留在旧服务器。**

`WebContainerView` 只在 `makeUIView` 加载地址，`updateUIView` 为空，调用处也没有按 serverUrl 重建容器；serverUrl 的变化只更新桥接允许的 host。保存服务器 B 后，界面仍显示 A 的媒体库，而原生播放请求和 Cookie 筛选已经使用 B。跨 host 时桥接会拒绝旧页面的请求；重启 App 才会重新加载。静态确认。

依据：[空 updateUIView](https://github.com/pcsensor/strmaction-ios/blob/40cb910e155b28f8c15ef0d2721d6f5b6c6a2ea6/Sources/Web/WebContainerView.swift#L69)、[serverUrl 变更处理](https://github.com/pcsensor/strmaction-ios/blob/40cb910e155b28f8c15ef0d2721d6f5b6c6a2ea6/Sources/App/StrmActionApp.swift#L72)。

建议在服务器地址变化时重新加载 / 重建 WebView，并同步更新桥接脚本与导航状态。

**7. iOS 返回网页时缺少统一进度刷新事件。**

Android 在播放器返回后发送 `strmaction:progress-updated`，桌面也发送该事件；iOS 关闭播放器只清空 activePlayInfo。云页面依赖该事件 invalidation 更新首页和详情，并关闭了窗口聚焦自动刷新，因此原生已经上报成功，返回后网页仍可能展示旧续播位置或已看状态。静态确认。

依据：[iOS 关闭回调](https://github.com/pcsensor/strmaction-ios/blob/40cb910e155b28f8c15ef0d2721d6f5b6c6a2ea6/Sources/App/StrmActionApp.swift#L47)、[网页刷新监听](https://github.com/pcsensor/strmaction/blob/a66ffad2f51fd1f66915a83b37a2cb17c68d1fbe/frontend/src/App.tsx#L164)、[关闭自动聚焦刷新](https://github.com/pcsensor/strmaction/blob/a66ffad2f51fd1f66915a83b37a2cb17c68d1fbe/frontend/src/main.tsx#L12)。

建议完成退出补报后，通过 WKWebView 发送同一事件；不要仅依靠刷新页面恢复状态。

**8. 后端 next_item_id 与同一响应的可播放 playlist 不一致。**

`_next_unwatched` 只排除已看集，没有排除缺失、损坏或软删除的集；随后生成 playlist 时却会过滤缺失 / 损坏媒体。客户端按 next_item_id 请求下一集时可能拿到列表中根本不存在的条目，并遭遇 `404 NO_MEDIA` 或 `ITEM_NOT_FOUND`。

依据：[下一集计算](https://github.com/pcsensor/strmaction/blob/a66ffad2f51fd1f66915a83b37a2cb17c68d1fbe/backend/app/api/play.py#L123)、[playlist 可播放过滤](https://github.com/pcsensor/strmaction/blob/a66ffad2f51fd1f66915a83b37a2cb17c68d1fbe/backend/app/api/play.py#L279)。

已运行复现：E1、E3 可播放，E2 的 MediaFile 标记 missing。E1 响应中 playlist 为 `[E1,E3]`，next_item_id 却是 E2；请求 E2 返回 `404 NO_MEDIA`。建议从同一份有效、未删除的播放序列计算列表和下一集。

**9. 三个平台对“跳过已看”的连播规则不同。**

Android 使用服务端 next_item_id。桌面优先取 playlist 的相邻条目，覆盖服务端跳过已看的结果；iOS 虽然优先使用服务端值，但 next_item_id 为 null 时会回退到相邻条目，并仍显示自动连播。后续全已看时，Android 停止，桌面 / iOS 会继续重播已看内容。

依据：[桌面下一集优先级](https://github.com/pcsensor/strmaction/blob/a66ffad2f51fd1f66915a83b37a2cb17c68d1fbe/desktop_flutter/lib/player/player_page.dart#L494)、[iOS 有下一集判断](https://github.com/pcsensor/strmaction-ios/blob/40cb910e155b28f8c15ef0d2721d6f5b6c6a2ea6/Sources/Player/PlayerView.swift#L59)、[iOS 回退](https://github.com/pcsensor/strmaction-ios/blob/40cb910e155b28f8c15ef0d2721d6f5b6c6a2ea6/Sources/Player/PlayerView.swift#L568)。

接口样例已验证：E2 已看、E3 未看时服务端返回 E3，桌面算法会取 E2；E2/E3 都已看时服务端返回 null，iOS 仍可回退到 E2。建议自动连播统一遵循 next_item_id；若手动“下一集”要按相邻顺序，应将两种行为明确区分。

**10. 课程 / 家庭视频在网页与原生播放列表中的排序不同。**

详情与起播目标使用 `natural_sort_key(title)`；播放接口对同目录视频使用 `(episode_no or 0, title)`，而此类视频的 episode_no 通常为 null，所以退化成字符串排序。用户看到的课程顺序和播放器选集 / 上下一集顺序不一致。

依据：[网页详情自然排序](https://github.com/pcsensor/strmaction/blob/a66ffad2f51fd1f66915a83b37a2cb17c68d1fbe/backend/app/api/items.py#L551)、[播放接口排序](https://github.com/pcsensor/strmaction/blob/a66ffad2f51fd1f66915a83b37a2cb17c68d1fbe/backend/app/api/play.py#L343)。

已运行复现：标题 `[1] lesson`、`[2] lesson`、`[10] lesson`，网页为 `1,2,10`，播放器为 `10,1,2`；从文件夹起播第一课时，播放器中甚至会把第十课列为“上一集”。建议共用排序函数。

**11. 桌面截断 200 条 playlist，却保留原索引，导致上一集越界。**

payload 清洗执行 `raw.take(200)`，current_index 却直接沿用服务端完整列表索引。`_hasPrevious` 没有检查索引上界，`_previousEpisode` 直接访问 `playlist[index-1]`。第 202 集及以后，点击上一集会抛出 RangeError；第 201 集及以后也不在选集抽屉中。

依据：[截断列表](https://github.com/pcsensor/strmaction/blob/a66ffad2f51fd1f66915a83b37a2cb17c68d1fbe/desktop_flutter/lib/models/playback_payload.dart#L249)、[上一集索引](https://github.com/pcsensor/strmaction/blob/a66ffad2f51fd1f66915a83b37a2cb17c68d1fbe/desktop_flutter/lib/player/player_page.dart#L419)。

接口样例已生成 205 集列表，第 202 集 current_index 为 201；桌面只保留 200 条，上一集访问索引 200 超出范围。越界由源码静态确认，未运行 Flutter。建议保留完整列表，或者分页时重新映射索引并按 ID 查找。

**12. 云页面声称全局缓存设置对客户端生效，实际各端均使用本地值。**

云设置文案称非零缓存值按 16–2048MB 执行、对伴侣和桌面生效，后端也下发 cache_limit_mb。但 Android 使用本地预取与磁盘设置及固定内存预算；桌面只传 `app.config.cacheLimitMb`；iOS 从本地 PlaybackBufferPreference 读取。下发字段在 Android / iOS 虽被解析，实际播放不采用；桌面 payload 根本未保存该字段。静态确认。

依据：[云页面说明](https://github.com/pcsensor/strmaction/blob/a66ffad2f51fd1f66915a83b37a2cb17c68d1fbe/frontend/src/i18n/zh-CN.ts#L343)、[Android 本地预取](https://github.com/pcsensor/strmaction/blob/a66ffad2f51fd1f66915a83b37a2cb17c68d1fbe/companion/app/src/main/java/top/strmaction/companion/PlayerActivity.kt#L1544)、[桌面本地缓存](https://github.com/pcsensor/strmaction/blob/a66ffad2f51fd1f66915a83b37a2cb17c68d1fbe/desktop_flutter/lib/player/player_page.dart#L123)、[iOS 本地缓冲](https://github.com/pcsensor/strmaction-ios/blob/40cb910e155b28f8c15ef0d2721d6f5b6c6a2ea6/Sources/Player/PlaybackSession.swift#L77)。

建议明确“全局默认 + 本地覆盖”的优先级和单位语义，或者移除失效的云设置与承诺。不同内核可以保留不同缓冲实现，但界面应准确描述生效范围。

**13. 网页 fallback_on_error 开关没有被客户端执行。**

页面提供“开启：播放失败时给出提示 / 关闭：不提示”，服务端可保存和返回；Android 与 iOS 仅将其解析进模型，没有使用。两个伴侣端的错误提示路径无条件显示弹窗或错误面板，因此关闭选项也不改变行为。静态确认。

依据：[设置文案](https://github.com/pcsensor/strmaction/blob/a66ffad2f51fd1f66915a83b37a2cb17c68d1fbe/frontend/src/i18n/zh-CN.ts#L326)、[Android 错误提示](https://github.com/pcsensor/strmaction/blob/a66ffad2f51fd1f66915a83b37a2cb17c68d1fbe/companion/app/src/main/java/top/strmaction/companion/PlayerActivity.kt#L1945)、[iOS 错误界面](https://github.com/pcsensor/strmaction-ios/blob/40cb910e155b28f8c15ef0d2721d6f5b6c6a2ea6/Sources/Player/PlayerView.swift#L187)。

建议先明确这个字段是控制提示还是控制播放器回退；当前产品始终提示失败也合理，但应同步移除无效开关和旧契约。

**14. iOS 缺少 Android / 桌面已有的音轨和内封字幕选择入口。**

iOS 自定义菜单只列出服务器返回的外挂字幕，没有枚举或选择播放器中的音轨 / 内封字幕。只有内封字幕的 MKV 会显示“没有外挂字幕”，用户无法在此选择语言；多音轨也无法切换。Android 已通过 Media3 Tracks 枚举，桌面通过 media_kit 轨道枚举提供了入口，iOS 架构文档同样承诺了音轨选择。静态确认，未测试解码器默认选轨行为。

依据：[iOS 菜单](https://github.com/pcsensor/strmaction-ios/blob/40cb910e155b28f8c15ef0d2721d6f5b6c6a2ea6/Sources/Player/PlayerDrawerView.swift#L316)、[iOS 字幕列表](https://github.com/pcsensor/strmaction-ios/blob/40cb910e155b28f8c15ef0d2721d6f5b6c6a2ea6/Sources/Player/PlayerDrawerView.swift#L452)、[Android 轨道枚举](https://github.com/pcsensor/strmaction/blob/a66ffad2f51fd1f66915a83b37a2cb17c68d1fbe/companion/app/src/main/java/top/strmaction/companion/player/PlayerTrackHelper.kt#L16)、[桌面轨道处理](https://github.com/pcsensor/strmaction/blob/a66ffad2f51fd1f66915a83b37a2cb17c68d1fbe/desktop_flutter/lib/player/media_kit_engine.dart#L188)。

建议把原生内核轨道和外挂字幕放入统一选择模型，并保留“关闭字幕”入口。

另有三处较小的契约漂移，未计入上面 14 项：Android 将心跳下限夹到 3 秒，而云设置允许 2 秒；iOS API 文档仍将 play_token_expires_at 示例写成数字，实际接口与当前 Swift 模型已改为 ISO 字符串；文档和 iOS 外部调用仍沿用已被后端归一化为 auto 的 external_mpv 模式名。应同步文档和能力声明，避免后续实现再次偏离。

这些检查没有发现当前播放响应的关键字段类型不兼容：真实返回的 ISO 到期时间、playlist、subtitles、headers 和 resume_ms 可以由当前 Swift PlayResponse 解码。登录、库授权、字幕下载鉴权和进度接口的现有后端测试均通过。浏览器复制 / intent 降级、桌面 direct、本地不同 TLS 配置方式属于可解释的设计差异，没有因为实现不同就列为缺陷。

复现材料位于本目录：[接口结果](/Users/pcsensor/justin/test/alignment-review/contract-results.json)、[Swift 失败队列结果](/Users/pcsensor/justin/test/alignment-review/swift-progress-results.json)、[接口探针](/Users/pcsensor/justin/test/alignment-review/probes/contract_probe.py)、[Swift 探针运行器](/Users/pcsensor/justin/test/alignment-review/probes/run_swift_progress_probe.py)。探针使用临时数据库和本地 HTTP 服务，不连接真实业务服务器；Swift 探针仅为 HTTP 队列测试替换了 TLS 策略依赖，实际进度引擎与模型均直接编译自仓库。

本轮复现命令（Python 环境已装后端依赖及 pytest）：

```sh
cd /Users/pcsensor/justin/test/strmaction/backend
PYTHONPATH=. /tmp/strmaction-review-venv/bin/python /Users/pcsensor/justin/test/alignment-review/probes/contract_probe.py /Users/pcsensor/justin/test/alignment-review
/tmp/strmaction-review-venv/bin/python /Users/pcsensor/justin/test/alignment-review/probes/run_swift_progress_probe.py
```
