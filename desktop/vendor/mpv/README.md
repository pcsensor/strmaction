# 播放器组件说明

> **重要更新**：
> 从当前版本起，StrmAction 桌面端已全面升级为 **PySide6 原生硬件加速播放内核（`QMediaPlayer` + `QVideoWidget` + 内置轻量环回代理）**。
> 桌面端运行与打包**完全不再依赖或需要外部 mpv 二进制文件**，用户亦无需手动配置 mpv 路径，开箱即用。
> 
> 本目录及旧版 `prepare_mpv.py` 仅作为历史参考与向后兼容保留。

---

### 历史目录约定（已废弃）

```text
vendor/mpv/
├── windows-x64/
│   └── mpv.exe
├── macos-arm64/
│   └── mpv
└── macos-x64/
    └── mpv
```
