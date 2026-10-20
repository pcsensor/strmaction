#!/usr/bin/env python3
"""Regenerate Windows/macOS icon files from the website favicon PNG."""

from __future__ import annotations

from pathlib import Path

from PIL import Image

ASSETS = Path(__file__).resolve().parents[1] / "src" / "strmaction_desktop" / "assets"


def main() -> int:
    png = ASSETS / "icon.png"
    if not png.is_file():
        raise SystemExit(f"缺少 {png}")
    image = Image.open(png).convert("RGBA")
    image.save(
        ASSETS / "icon.ico",
        sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
    )
    try:
        image.save(ASSETS / "icon.icns")
    except Exception as exc:  # pragma: no cover - Pillow version dependent
        print(f"ICNS 生成失败（可在 macOS 上用 iconutil 处理）：{exc}")
    print(f"图标已写入 {ASSETS}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
