#!/usr/bin/env python3
"""Regenerate Windows/macOS icon files from the website favicon PNG."""

from __future__ import annotations

from pathlib import Path

from PIL import Image

ASSETS = Path(__file__).resolve().parents[1] / "src" / "strmaction_desktop" / "assets"

# macOS 图标规范：内容约占画布 80%（1024 画布上为 824），四周留透明边距。
# 否则系统统一遮罩裁剪后，图标在 Dock 中会比规范图标大一圈。
MACOS_ICON_SIDE = 1024
MACOS_ICON_SCALE = 0.8047


def macos_icon(image: Image.Image) -> Image.Image:
    """按 macOS 图标规范生成带留白的图标，用于 .icns。"""
    side = MACOS_ICON_SIDE
    inner = round(side * MACOS_ICON_SCALE)
    content = image.resize((inner, inner), Image.LANCZOS)
    canvas = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    canvas.paste(content, ((side - inner) // 2, (side - inner) // 2))
    return canvas


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
        macos_icon(image).save(ASSETS / "icon.icns")
    except Exception as exc:  # pragma: no cover - Pillow version dependent
        print(f"ICNS 生成失败（可在 macOS 上用 iconutil 处理）：{exc}")
    print(f"图标已写入 {ASSETS}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
