# 这里放打包用的 mpv（不提交二进制）

目录约定：

```text
vendor/mpv/
├── windows-x64/
│   ├── mpv.exe
│   └── *.dll
├── windows-arm64/
│   └── mpv.exe
├── macos-arm64/
│   └── mpv            # 或 mpv.app/Contents/MacOS/mpv
└── macos-x64/
    └── mpv
```

`desktop/` 源码运行时也会优先查这里；没有时回退到用户已安装的 mpv。
构建安装包前执行：

```powershell
uv run python scripts/prepare_mpv.py --source C:\tools\mpv
```

```bash
uv run python scripts/prepare_mpv.py --source /Applications/mpv.app
```

注意：mpv 的许可证与再分发义务需要按你的发布方式确认；仓库默认不提交二进制。
