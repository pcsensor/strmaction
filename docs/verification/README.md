# 修复验证记录（Android 模拟器）

- 设备：Android 14（API 34）模拟器，Pixel 6，1080×2400
- APK：`companion/strmaction-companion-v1.3.apk`（versionName 1.3 / versionCode 4）
- 测试媒体库类型故意设为 **电影**，目录结构为：
  `媒体库根/卿卿日常 2022/Season 01/S01E01-S01E40/S01E01.strm`，
  同库还有 `狂飙/S01E01.strm`（无 Season 目录）、`漫长的季节 2023/S01E01-S01E12/01.strm`、
  以及电影 `流浪地球2 (2023)`。

## 截图

| 文件 | 验证内容 |
|---|---|
| `series-episodes.png` | 电影库中的电视剧被正确识别为「卿卿日常」2022，1 季 3 集；剧集卡片显示 S01E01 / 第1集，而不是「版本」 |
| `player-controls.png` | 底部控制条：上一集 / 播放暂停 / 下一集、进度条、选集、倍速、全屏；右侧中间「锁」 |
| `player-playlist.png` | 选集弹窗列出同一部剧的全部剧集（S01E01–S01E03），当前集、已看集有标记 |
| `player-fullscreen.png` | 全屏后隐藏系统栏并横屏，右下角按钮变为「退出全屏」 |
| `player-locked.png` | 锁定后隐藏全部控件，仅保留右侧「解锁」入口 |

后端 `pytest`：48 项全部通过。
