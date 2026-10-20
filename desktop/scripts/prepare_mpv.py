#!/usr/bin/env python3
"""Copy a local mpv build into desktop/vendor/mpv/<platform>/.

The repository does not commit the mpv binary (size + GPL distribution
considerations).  Build machines should run this script before PyInstaller so
the generated application contains mpv and does not depend on a user install.

Examples:
    python scripts/prepare_mpv.py --source C:\\tools\\mpv
    python scripts/prepare_mpv.py --source /Applications/mpv.app
    python scripts/prepare_mpv.py --source ./mpv.exe --platform windows-x64
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

DESKTOP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DESKTOP / "src"))

from strmaction_desktop.mpv import find_mpv, platform_key  # noqa: E402


def _copy_directory(source: Path, dest: Path) -> None:
    if source.name.endswith(".app"):
        target = dest / "mpv.app"
        shutil.copytree(source, target)
        return
    dest.mkdir(parents=True, exist_ok=True)
    for item in source.iterdir():
        target = dest / item.name
        if item.is_dir():
            shutil.copytree(item, target)
        else:
            shutil.copy2(item, target)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True, help="mpv 可执行文件或包含 mpv 的目录")
    parser.add_argument("--platform", default=platform_key(), help="例如 windows-x64 / macos-arm64")
    parser.add_argument("--dest", default="", help="默认 desktop/vendor/mpv/<platform>")
    parser.add_argument("--force", action="store_true", help="覆盖已有目录")
    args = parser.parse_args(argv)

    source = Path(args.source).expanduser().resolve()
    if not source.exists():
        print(f"源路径不存在：{source}")
        return 2
    dest = (
        Path(args.dest).expanduser().resolve()
        if args.dest
        else (DESKTOP / "vendor" / "mpv" / args.platform).resolve()
    )
    vendor_root = (DESKTOP / "vendor" / "mpv").resolve()
    if vendor_root not in dest.parents and dest != vendor_root:
        print(f"拒绝写入 vendor 之外：{dest}")
        return 2
    if dest.exists():
        if not args.force:
            print(f"{dest} 已存在；如需覆盖请加 --force")
            return 2
        shutil.rmtree(dest)

    if source.is_dir():
        _copy_directory(source, dest)
    else:
        dest.mkdir(parents=True, exist_ok=True)
        name = "mpv.exe" if args.platform.startswith("windows") else "mpv"
        shutil.copy2(source, dest / name)
        if not args.platform.startswith("windows"):
            (dest / name).chmod(0o755)

    found = find_mpv("", base_dir=DESKTOP, system=sys.platform)
    if found:
        print(f"mpv 已准备：{found}")
        return 0
    print(f"已复制到 {dest}，但未识别为可执行文件；请检查目录结构。")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
