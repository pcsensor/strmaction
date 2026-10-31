"""目录遍历与 .strm 读取。"""

from __future__ import annotations

import fnmatch
import os
from dataclasses import dataclass
from pathlib import Path

DEFAULT_IGNORE = ["@eaDir", ".DS_Store", "#recycle", "*.tmp"]
STRM_SUFFIX = ".strm"


@dataclass
class WalkEntry:
    abs_path: str
    rel_path: str
    mtime: int
    size: int


@dataclass
class StrmContent:
    url: str
    valid: bool
    error: str | None = None


def _is_ignored(name: str, patterns: list[str]) -> bool:
    lowered = name.lower()
    for pattern in patterns or []:
        if fnmatch.fnmatch(lowered, pattern.lower()):
            return True
    return False


def _within_root(path: str, root: str) -> bool:
    try:
        return os.path.commonpath([os.path.realpath(path), root]) == root
    except ValueError:
        return False


def iter_strm_files(
    root_path: str,
    ignore: list[str] | None = None,
    max_depth: int = 6,
    follow_symlinks: bool = False,
):
    """遍历 .strm 文件；结果按相对路径排序，保证扫描确定性。"""
    root = os.path.realpath(root_path)
    patterns = list(ignore or DEFAULT_IGNORE)
    results: list[WalkEntry] = []

    if not os.path.isdir(root):
        raise OSError(f"媒体库目录不可访问: {root_path}")

    def walk(directory: str, depth: int) -> None:
        if depth > max_depth:
            return
        try:
            entries = sorted(os.scandir(directory), key=lambda e: e.name.lower())
        except OSError as exc:
            raise OSError(f"无法扫描目录 {directory}: {exc}") from exc
        for entry in entries:
            name = entry.name
            if _is_ignored(name, patterns):
                continue
            try:
                is_link = entry.is_symlink()
                if is_link and not follow_symlinks:
                    continue
                if is_link and not _within_root(entry.path, root):
                    continue
                if entry.is_dir(follow_symlinks=follow_symlinks):
                    walk(entry.path, depth + 1)
                elif entry.is_file(follow_symlinks=follow_symlinks):
                    if not name.lower().endswith(STRM_SUFFIX):
                        continue
                    if is_link and not _within_root(entry.path, root):
                        continue
                    stat = entry.stat(follow_symlinks=follow_symlinks)
                    rel = os.path.relpath(entry.path, root).replace(os.sep, "/")
                    results.append(
                        WalkEntry(
                            abs_path=os.path.realpath(entry.path)
                            if follow_symlinks
                            else entry.path,
                            rel_path=rel,
                            mtime=int(stat.st_mtime),
                            size=int(stat.st_size),
                        )
                    )
            except OSError as exc:
                raise OSError(f"无法检查路径 {entry.path}: {exc}") from exc

    walk(root, 0)
    results.sort(key=lambda e: e.rel_path.lower())
    return results


def read_strm(path: str, max_bytes: int = 64 * 1024) -> StrmContent:
    """读取 .strm 首个有效行；兼容 UTF-8 BOM；不做任何网络请求。"""
    try:
        with open(path, "rb") as handle:
            raw = handle.read(max_bytes)
    except OSError as exc:
        return StrmContent("", False, f"读取失败: {exc}")
    text = raw.decode("utf-8-sig", errors="replace")
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if not line.lower().startswith(("http://", "https://")):
            return StrmContent("", False, "URL 必须以 http:// 或 https:// 开头")
        return StrmContent(line, True)
    return StrmContent("", False, "文件为空或没有有效 URL")


def is_within_root(path: str, root_path: str) -> bool:
    return _within_root(path, os.path.realpath(root_path))


def ensure_library_root(root_path: str) -> tuple[bool, str]:
    path = Path(root_path)
    if not path.is_absolute():
        return False, "root_path 必须是容器内绝对路径"
    if not path.exists():
        return False, "目录不存在"
    if not path.is_dir():
        return False, "不是目录"
    return True, ""
