"""Fetch the libmpv shared library into the package vendor directory.

The library is 121 MB, so it is not committed.  Run this once after cloning:

    python scripts/fetch_libmpv.py

Windows pulls the official shinchiro ``mpv-dev`` build and extracts
``libmpv-2.dll``.  macOS needs the universal XCFramework from
``media-kit/libmpv-darwin-build``; that path is documented but not automated
here because it requires picking a framework slice.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

# Pinned so builds stay reproducible; override with --url when updating.
WINDOWS_URL = (
    "https://sourceforge.net/projects/mpv-player-windows/files/libmpv/"
    "mpv-dev-x86_64-20261018-git-01e2533f31.7z/download"
)
WINDOWS_MEMBER = "libmpv-2.dll"
MACOS_HINT = """\
macOS 需要自行准备 universal 的 libmpv：

  # 方式一：Homebrew（注意其 formula 为 Vulkan-only，mpv 渲染可能不可用）
  brew install mpv

  # 方式二：取 media-kit 的预编译 XCFramework（推荐，含完整解码器）
  #   仓库：https://github.com/media-kit/libmpv-darwin-build/releases
  #   解压后把 Mpv.framework 放到：
  #     src/strmaction_desktop/vendor/libmpv/macos-<arch>/
  #   mpv_loader 会识别 Mpv.framework/libmpv
"""

VENDOR = (
    Path(__file__).resolve().parent.parent
    / "src"
    / "strmaction_desktop"
    / "vendor"
    / "libmpv"
)


def find_7z() -> str | None:
    for name in ("7z", "7za", "7zz"):
        found = shutil.which(name)
        if found:
            return found
    # Default install locations on Windows.
    for candidate in (
        Path(r"C:\Program Files\7-Zip\7z.exe"),
        Path(r"C:\Program Files (x86)\7-Zip\7z.exe"),
    ):
        if candidate.is_file():
            return str(candidate)
    return None


def extract(archive: Path, target: Path, member: str) -> None:
    target.mkdir(parents=True, exist_ok=True)
    seven = find_7z()
    if seven:
        subprocess.run(
            [seven, "e", str(archive), f"-o{target}", member, "-y"],
            check=True,
            stdout=subprocess.DEVNULL,
        )
        return
    try:
        import py7zr  # type: ignore[import-not-found]
    except ImportError as exc:  # pragma: no cover - depends on the machine
        raise SystemExit(
            "需要 7-Zip 或 py7zr 才能解压：pip install py7zr"
        ) from exc
    with py7zr.SevenZipFile(archive, mode="r") as handle:  # pragma: no cover
        handle.extract(path=target, targets=[member])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default=WINDOWS_URL, help="libmpv archive URL")
    parser.add_argument("--force", action="store_true", help="re-download")
    args = parser.parse_args()

    if sys.platform == "darwin":
        print(MACOS_HINT)
        return 0
    if not sys.platform.startswith("win"):
        raise SystemExit("当前脚本只自动化了 Windows；Linux 请安装 libmpv 开发包")

    target = VENDOR / "windows-x64"
    destination = target / WINDOWS_MEMBER
    if destination.is_file() and not args.force:
        size = destination.stat().st_size / (1024 * 1024)
        print(f"已存在：{destination}（{size:.0f} MB），用 --force 重新下载")
        return 0

    with tempfile.TemporaryDirectory() as tmp:
        archive = Path(tmp) / "mpv-dev.7z"
        print(f"下载 {args.url}")
        with urllib.request.urlopen(args.url, timeout=300) as response:
            archive.write_bytes(response.read())
        size = archive.stat().st_size / (1024 * 1024)
        print(f"归档 {size:.1f} MB，解压 {WINDOWS_MEMBER}")
        extract(archive, target, WINDOWS_MEMBER)

    if not destination.is_file():
        raise SystemExit(f"解压后未找到 {WINDOWS_MEMBER}")
    print(f"完成：{destination}（{destination.stat().st_size / (1024 * 1024):.0f} MB）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
