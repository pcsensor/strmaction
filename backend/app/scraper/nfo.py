"""本地 .nfo 兼容（tinyMediaManager / Kodi 标准）。

命中 .nfo 时完全接管元数据，不再请求在线源。
"""

from __future__ import annotations

import os
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any


def _text(node: ET.Element | None, tag: str) -> str | None:
    if node is None:
        return None
    child = node.find(tag)
    if child is None or child.text is None:
        return None
    value = child.text.strip()
    return value or None


def _int(value: str | None) -> int | None:
    if not value:
        return None
    try:
        return int(float(value))
    except ValueError:
        return None


def _float(value: str | None) -> float | None:
    if not value:
        return None
    try:
        return float(value)
    except ValueError:
        return None


def find_nfo(media_path: str, kind: str, library_root: str | None = None) -> Path | None:
    media = Path(media_path)
    directory = media.parent
    stem = media.name
    for suffix in (".strm", ".mp4", ".mkv", ".avi"):
        if stem.lower().endswith(suffix):
            stem = stem[: -len(suffix)]
            break
    candidates = [
        directory / f"{stem}.nfo",
        directory / ("tvshow.nfo" if kind == "tv" else "movie.nfo"),
    ]
    if kind == "tv":
        # 剧集 NFO 可能在剧集根目录（Season 上一级）
        current = directory
        root = Path(library_root).resolve() if library_root else None
        while True:
            candidates.append(current / "tvshow.nfo")
            if root is not None and current.resolve() == root:
                break
            if current.parent == current:
                break
            current = current.parent
            if root is not None and not str(current.resolve()).startswith(str(root)):
                break
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def parse_nfo(path: str | Path) -> dict[str, Any] | None:
    try:
        tree = ET.parse(path)
    except (ET.ParseError, OSError):
        return None
    root = tree.getroot()
    base = Path(path).parent
    kind_tag = root.tag.lower()
    kind = "tv" if kind_tag in {"tvshow"} else "movie"

    genres = [
        (node.text or "").strip()
        for node in root.findall("genre")
        if (node.text or "").strip()
    ]
    cast: list[dict[str, Any]] = []
    for actor in root.findall("actor"):
        name = _text(actor, "name")
        if not name:
            continue
        thumb = _text(actor, "thumb")
        cast.append(
            {
                "name": name,
                "role": _text(actor, "role"),
                "avatar": str((base / thumb).resolve()) if thumb and not thumb.startswith("http") else thumb,
            }
        )
    directors = [
        (node.text or "").strip()
        for node in root.findall("director")
        if (node.text or "").strip()
    ]
    for name in directors:
        cast.insert(0, {"name": name, "role": "导演", "kind": "director"})

    external: dict[str, str] = {}
    for node in root.findall("uniqueid"):
        uid_type = (node.get("type") or "").lower()
        value = (node.text or "").strip()
        if not value:
            continue
        if uid_type in {"tmdb", "tvdb", "imdb"}:
            external[uid_type] = value
    for node in root.findall("id"):
        value = (node.text or "").strip()
        if value:
            external.setdefault("imdb", value)

    poster = None
    node = root.find("thumb")
    if node is not None and node.text:
        poster = node.text.strip()
    if not poster:
        for thumb in root.findall("thumb"):
            if (thumb.get("aspect") or "").lower() == "poster" and thumb.text:
                poster = thumb.text.strip()
                break
    fanart = root.find("fanart")
    backdrop = None
    if fanart is not None:
        thumb = fanart.find("thumb")
        if thumb is not None and thumb.text:
            backdrop = thumb.text.strip()

    def absolute(value: str | None) -> str | None:
        if not value:
            return None
        if value.startswith(("http://", "https://")):
            return value
        return str((base / value).resolve())

    trailer = None
    node = root.find("trailer")
    if node is not None and node.text:
        text = node.text.strip()
        if "youtube.com" in text:
            trailer = text.split("v=")[-1].split("&")[0]
        else:
            trailer = text

    year_raw = _text(root, "year") or _text(root, "premiered") or ""
    year = None
    if year_raw[:4].isdigit():
        year = int(year_raw[:4])

    return {
        "kind": kind,
        "title": _text(root, "title"),
        "original_title": _text(root, "originaltitle"),
        "year": year,
        "overview": _text(root, "plot") or _text(root, "outline"),
        "tagline": _text(root, "tagline"),
        "rating": _float(_text(root, "rating")),
        "runtime_min": _int(_text(root, "runtime")),
        "genres": genres,
        "certification": _text(root, "mpaa") or _text(root, "certification"),
        "status": _text(root, "status"),
        "cast": cast,
        "external_ids": external,
        "poster": absolute(poster),
        "backdrop": absolute(backdrop),
        "trailer_key": trailer,
        "path": str(path),
    }
