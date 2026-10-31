"""API 序列化辅助。"""

from __future__ import annotations

import json
from typing import Any

from sqlmodel import Session, select

from .images import image_url
from .models import Item, Library, MediaFile, PlayProgress, TaskLog
from .text import normalize_title


def parse_json(value: str | None, default: Any = None) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return default


def poster_url(sha: str | None, size: int = 342) -> str | None:
    return image_url(sha, size)


def media_labels(media: MediaFile | None) -> list[str]:
    if media is None:
        return []
    labels = parse_json(media.labels, [])
    out = [str(x) for x in labels] if isinstance(labels, list) else []
    if media.version:
        if media.version == "2160p" and "4K" not in out:
            out.insert(0, "4K")
        elif media.version == "1080p" and "1080P" not in out:
            out.append("1080P")
    return out


def progress_payload(row: PlayProgress | None) -> dict[str, Any] | None:
    if row is None:
        return None
    ratio = None
    if row.duration_ms and row.duration_ms > 0:
        ratio = round(min(1.0, max(0.0, row.position_ms / row.duration_ms)), 4)
    return {
        "position_ms": row.position_ms,
        "duration_ms": row.duration_ms,
        "finished": bool(row.finished),
        "progress": ratio,
        "updated_at": row.updated_at,
    }


def episode_code(item: Item) -> str | None:
    if item.season_no is None or item.episode_no is None:
        return None
    return f"S{item.season_no:02d}E{item.episode_no:02d}"


def item_summary(
    item: Item,
    *,
    progress: PlayProgress | None = None,
    badges: list[str] | None = None,
    overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    data = {
        "id": item.id,
        "library_id": item.library_id,
        "parent_id": item.parent_id,
        "kind": item.kind,
        "title": item.title,
        "original_title": item.original_title,
        "year": item.year,
        "season_no": item.season_no,
        "episode_no": item.episode_no,
        "overview_short": (item.overview or "")[:180] or None,
        "rating": round(item.rating, 1) if item.rating else None,
        "poster": poster_url(item.poster_path, 342),
        "poster_large": poster_url(item.poster_path, 500),
        "backdrop": poster_url(item.backdrop_path, 780),
        "backdrop_large": poster_url(item.backdrop_path, 1280),
        "still": poster_url(item.still_path, 300),
        "still_large": poster_url(item.still_path, 780),
        "logo": poster_url(item.logo_path, 400),
        "color": item.color_primary,
        "certification": item.certification,
        "runtime_min": item.runtime_min,
        "provider": item.provider,
        "match_state": item.match_state,
        "status": item.status,
        "badges": badges or [],
        "progress": progress_payload(progress),
        "watched": bool(progress and progress.finished),
        "created_at": item.created_at,
        "updated_at": item.updated_at,
    }
    if overrides:
        data.update(overrides)
    return data


def episode_summary(
    item: Item, *, progress: PlayProgress | None = None
) -> dict[str, Any]:
    data = item_summary(item, progress=progress)
    data.update(
        {
            "episode_code": episode_code(item),
            "still": poster_url(item.still_path, 300),
            "overview": item.overview,
            "air_date": item.air_date,
        }
    )
    return data


def library_payload(
    library: Library,
    counts: dict[str, int] | None = None,
    *,
    include_private: bool = True,
) -> dict[str, Any]:
    return {
        "id": library.id,
        "name": library.name,
        "root_path": library.root_path if include_private else "",
        "type": library.type,
        "language": library.language,
        "scan_cron": library.scan_cron,
        "enabled": library.enabled,
        "auto_scrape": library.auto_scrape,
        "template": library.template,
        "provider_priority": parse_json(library.provider_priority, None),
        "tvdb_season_type": library.tvdb_season_type,
        "play_headers": (
            (parse_json(library.play_headers, {}) or {}) if include_private else {}
        ),
        "created_at": library.created_at,
        "last_scan_at": library.last_scan_at,
        "counts": counts or {},
    }


def task_payload(row: TaskLog) -> dict[str, Any]:
    stats = parse_json(row.stats, {}) or {}
    return {
        "id": row.id,
        "kind": row.kind,
        "library_id": row.library_id,
        "status": row.status,
        "message": row.message,
        "stats": stats,
        "started_at": row.started_at,
        "finished_at": row.finished_at,
    }


def ready_item_ids(session: Session, library_id: int | None = None) -> set[int]:
    """可展示条目：至少有一个有效且未缺失 media_file 的条目及其祖先，排除软删除。"""
    return set(session.exec(ready_item_query(library_id)).all())


def ready_item_query(library_id: int | None = None):
    """Database-side playable descendants and their non-deleted ancestors."""
    from sqlalchemy.orm import aliased

    base = select(Item.id, Item.parent_id).join(MediaFile, MediaFile.item_id == Item.id).where(
        MediaFile.invalid == False, MediaFile.missing == False, Item.deleted_at == None,  # noqa: E711,E712
    )
    deleted = select(Item.id).where(Item.deleted_at != None)  # noqa: E711
    if library_id is not None:
        base = base.where(Item.library_id == library_id, MediaFile.library_id == library_id)
        deleted = deleted.where(Item.library_id == library_id)
    blocked = deleted.cte("blocked_items", recursive=True)
    child = aliased(Item)
    blocked = blocked.union(select(child.id).join(blocked, child.parent_id == blocked.c.id))
    ready = base.cte("ready_items", recursive=True)
    parent = aliased(Item)
    ready = ready.union(select(parent.id, parent.parent_id).join(
        ready, parent.id == ready.c.parent_id
    ).where(parent.deleted_at == None))  # noqa: E711
    return select(ready.c.id).where(~ready.c.id.in_(select(blocked.c.id))).distinct()


def series_of(session: Session, item: Item) -> Item | None:
    current = item
    guard = 0
    while current is not None and current.kind != "series":
        if current.parent_id is None:
            return None
        current = session.get(Item, current.parent_id)
        guard += 1
        if guard > 6:
            return None
    return current


def playlist_root(session: Session, item: Item) -> Item | None:
    """
    返回条目所属的「播放列表」根节点：最顶层的 series / season / folder。

    「继续观看」按它分组，保证同一部剧（或同一个课程文件夹）只出现一张卡。
    没有集合型祖先时返回 None，调用方按条目自身分组（电影、散装视频）。
    """
    chain: list[Item] = []
    current: Item | None = item
    guard = 0
    while current is not None:
        chain.append(current)
        if current.parent_id is None:
            break
        current = session.get(Item, current.parent_id)
        guard += 1
        if guard > 8:
            break
    for node in reversed(chain):
        if node.kind in {"series", "season", "folder"}:
            return node
    return None


def playlist_key(session: Session, item: Item) -> int:
    """分组键：播放列表根节点 id；没有根节点时用条目自身 id。"""
    root = playlist_root(session, item)
    return root.id if root is not None and root.id is not None else item.id


def playlist_key_map(session: Session, items: list[Item]) -> dict[int, int]:
    """批量计算播放列表根，避免为每一行进度逐级查询祖先。"""
    by_id: dict[int, Item] = {
        item.id: item for item in items if item.id is not None
    }
    pending = {
        item.parent_id
        for item in items
        if item.parent_id is not None and item.parent_id not in by_id
    }
    while pending:
        rows = session.exec(select(Item).where(Item.id.in_(list(pending)))).all()
        if not rows:
            break
        for row in rows:
            if row.id is not None:
                by_id[row.id] = row
        pending = {
            row.parent_id
            for row in rows
            if row.parent_id is not None and row.parent_id not in by_id
        }

    result: dict[int, int] = {}
    for item in items:
        if item.id is None:
            continue
        chain: list[Item] = []
        current: Item | None = item
        guard = 0
        while current is not None and guard <= 8:
            chain.append(current)
            if current.parent_id is None:
                break
            current = by_id.get(current.parent_id)
            guard += 1
        root = None
        for node in reversed(chain):
            if node.kind in {"series", "season", "folder"}:
                root = node
                break
        result[item.id] = root.id if root is not None and root.id is not None else item.id
    return result


def ancestors(session: Session, item: Item) -> dict[str, Item | None]:
    parent = session.get(Item, item.parent_id) if item.parent_id else None
    season = parent if parent and parent.kind == "season" else (
        item if item.kind == "season" else None
    )
    series = series_of(session, item)
    return {"parent": parent, "season": season, "series": series}


def search_text(item: Item) -> str:
    parts = [item.title, item.original_title or "", item.overview or ""]
    for value in (item.alt_titles, item.genres, item.cast):
        parsed = parse_json(value, [])
        if isinstance(parsed, list):
            for entry in parsed:
                if isinstance(entry, dict):
                    parts.append(str(entry.get("name") or ""))
                    parts.append(str(entry.get("role") or ""))
                else:
                    parts.append(str(entry))
    return " ".join(p for p in parts if p).lower()


def sort_title(item: Item) -> str:
    return item.sort_title or normalize_title(item.title)
