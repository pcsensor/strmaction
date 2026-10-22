# 播放器组件说明（已废弃）

> **重要更新（v1.3）**：
> StrmAction 桌面端使用 **PySide6 播放内核（`QMediaPlayer` + `QVideoWidget` + 内置轻量环回代理）**，
> 运行与打包**完全不再依赖外部 mpv 二进制**，也不再提供播放器路径配置。
>
> - `packaging/strmaction-desktop.spec` 已不再包含本目录；
> - `scripts/prepare_mpv.py` 已删除；
> - 本目录下的文件仅为历史遗留，可整目录删除，不影响运行与打包。

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
