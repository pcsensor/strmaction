"""首页聚合 API（§13 GET /home）。v0.9: 支持多用户和管理员去重逻辑。"""

from __future__ import annotations

import json
from collections import Counter
from typing import Any

from fastapi import APIRouter, Depends
from sqlmodel import Session, select

from ..deps import get_engine, get_current_user, get_accessible_library_ids
from ..models import Item, Library, PlayProgress
from ..schemas import CurrentUser
from ..serializers import (
    episode_code,
    item_summary,
    library_payload,
    parse_json,
    ready_item_ids,
    series_of,
)

router = APIRouter(tags=["home"])


def _dedupe_items_for_admin(items: list[Item]) -> list[Item]:
    """
    管理员视角去重：同一影片在多个库中时，只保留一个。
    去重策略：按 provider_id（如 tmdb:12345）或 title+year 分组。
    """
    seen_keys: set[str] = set()
    deduped: list[Item] = []

    for item in items:
        key = None
        if item.provider_id:
            key = f"{item.provider}:{item.provider_id}"
        elif item.title and item.title.strip():
            title = item.title.strip().lower()
            year = item.year or 0
            key = f"title:{title}:{year}"

        if key is None or key not in seen_keys:
            if key:
                seen_keys.add(key)
            deduped.append(item)

    return deduped


def _hero(item: Item) -> dict[str, Any]:
    data = item_summary(item)
    data.update(
        {
            "tagline": item.tagline,
            "overview": item.overview,
            "genres": parse_json(item.genres, []),
            "logo": data.get("logo"),
        }
    )
    return data


@router.get("/home")
def home(user: CurrentUser = Depends(get_current_user), engine=Depends(get_engine)):
    """v0.9: 首页聚合，管理员看所有库（去重+标注多库），普通用户只看授权库。"""
    with Session(engine) as session:
        # 获取用户可访问的库
        accessible_ids = get_accessible_library_ids(user, engine)

        # 构造查询条件
        ready = ready_item_ids(session)
        query = select(Item).where(
            Item.deleted_at == None,  # noqa: E711
            Item.kind.in_(["movie", "series", "video", "folder"]),
        )

        # 按用户权限过滤
        if accessible_ids is not None:  # 普通用户
            if not accessible_ids:
                # 用户没有授权任何库
                return {
                    "hero": [],
                    "continue": [],
                    "rows": [],
                    "stats": {"movies": 0, "series": 0, "episodes": 0, "videos": 0},
                    "needs_attention": 0,
                    "libraries": [],
                }
            query = query.where(Item.library_id.in_(accessible_ids))

        all_items = session.exec(query).all()
        playable = [i for i in all_items if i.id in ready]

        # 管理员去重逻辑（用于推荐流，不影响单库展示）
        deduped_playable = (
            _dedupe_items_for_admin(playable)
            if user.role == "admin" and accessible_ids is None
            else playable
        )

        hero_candidates = [
            i
            for i in deduped_playable
            if i.kind in {"movie", "series"} and i.backdrop_path
        ]
        hero_candidates.sort(
            key=lambda i: (-(i.rating or 0), i.updated_at or ""), reverse=False
        )
        hero = [_hero(i) for i in hero_candidates[:6]]

        # 继续观看：按 user_id 过滤
        continue_rows: list[dict[str, Any]] = []
        progress_rows = session.exec(
            select(PlayProgress)
            .where(
                PlayProgress.user_id == user.id,
                PlayProgress.finished == False,  # noqa: E712
                PlayProgress.position_ms > 0,
                PlayProgress.dismissed == False,  # noqa: E712
            )
            .order_by(PlayProgress.updated_at.desc())
            .limit(24)
        ).all()
        progress_map = {row.item_id: row for row in progress_rows}
        progress_items = session.exec(
            select(Item).where(Item.id.in_(list(progress_map)))
        ).all() if progress_map else []
        item_map = {i.id: i for i in progress_items}
        for row in progress_rows:
            item = item_map.get(row.item_id)
            if item is None or item.id not in ready:
                continue
            series = series_of(session, item)
            display = series if series and series.kind == "series" else item
            ratio = (
                round(row.position_ms / row.duration_ms, 4)
                if row.duration_ms and row.duration_ms > 0
                else None
            )
            remaining = None
            if row.duration_ms and row.duration_ms > row.position_ms:
                remaining = max(1, round((row.duration_ms - row.position_ms) / 60000))
            code = episode_code(item)
            if item.kind == "episode":
                subtitle = " · ".join(
                    x
                    for x in [
                        code,
                        f"剩余 {remaining} 分钟" if remaining else None,
                    ]
                    if x
                )
            else:
                subtitle = f"剩余 {remaining} 分钟" if remaining else "继续观看"
            continue_rows.append(
                {
                    **item_summary(display),
                    "continue_item_id": item.id,
                    "title": display.title,
                    "subtitle": subtitle,
                    "poster": item_summary(display)["poster"],
                    "backdrop": item_summary(display)["backdrop"],
                    "progress": {
                        "position_ms": row.position_ms,
                        "duration_ms": row.duration_ms,
                        "progress": ratio,
                        "updated_at": row.updated_at,
                    },
                    "episode_code": code,
                }
            )
            if len(continue_rows) >= 12:
                break

        recent = sorted(
            [i for i in deduped_playable if i.kind in {"movie", "series"}],
            key=lambda i: i.created_at or "",
            reverse=True,
        )[:20]
        top_rated = sorted(
            [i for i in deduped_playable if i.rating],
            key=lambda i: (-(i.rating or 0), i.created_at or ""),
        )[:20]

        rows: list[dict[str, Any]] = []
        if recent:
            rows.append(
                {
                    "key": "recent",
                    "title": "最近添加",
                    "items": [item_summary(i) for i in recent],
                }
            )
        if top_rated:
            rows.append(
                {
                    "key": "top",
                    "title": "评分最高",
                    "items": [item_summary(i) for i in top_rated],
                }
            )

        # 按类型
        genre_counter: Counter[str] = Counter()
        for item in deduped_playable:
            if item.kind not in {"movie", "series"}:
                continue
            for genre in parse_json(item.genres, []) or []:
                genre_counter[str(genre)] += 1
        for genre, _count in genre_counter.most_common(4):
            items = [
                i
                for i in deduped_playable
                if i.kind in {"movie", "series"}
                and genre in (parse_json(i.genres, []) or [])
            ]
            items.sort(key=lambda i: (-(i.rating or 0), i.created_at or ""))
            rows.append(
                {
                    "key": f"genre:{genre}",
                    "title": genre,
                    "items": [item_summary(i) for i in items[:20]],
                }
            )

        # 按媒体库
        libraries_query = select(Library).order_by(Library.id)
        if accessible_ids is not None:
            libraries_query = libraries_query.where(Library.id.in_(accessible_ids))
        libraries = session.exec(libraries_query).all()

        for library in libraries:
            if library.type in {"home", "course"}:
                lib_items = [
                    i
                    for i in playable
                    if i.library_id == library.id
                    and i.parent_id is None
                    and i.kind in {"folder", "video"}
                ]
                lib_items.sort(key=lambda i: (i.episode_no or 0, i.title))
            else:
                lib_items = [
                    i
                    for i in playable
                    if i.library_id == library.id
                    and i.kind in {"movie", "series", "video"}
                ]
                lib_items.sort(key=lambda i: i.created_at or "", reverse=True)
            if not lib_items:
                continue
            rows.append(
                {
                    "key": f"library:{library.id}",
                    "title": library.name,
                    "items": [item_summary(i) for i in lib_items[:20]],
                }
            )

        needs_attention = (
            sum(
                1
                for i in all_items
                if i.kind in {"movie", "series"}
                and (
                    i.match_state == "failed"
                    or (i.match_state == "pending" and i.provider)
                )
            )
            if user.role == "admin"
            else 0
        )
        episodes_query = select(Item).where(
            Item.kind == "episode",
            Item.deleted_at == None,  # noqa: E711
        )
        if accessible_ids is not None:
            episodes_query = episodes_query.where(Item.library_id.in_(accessible_ids))
        episodes_all = session.exec(episodes_query).all()
        stats = {
            "movies": sum(1 for i in playable if i.kind == "movie"),
            "series": sum(1 for i in playable if i.kind == "series"),
            "episodes": sum(1 for i in episodes_all if i.id in ready),
            "videos": sum(1 for i in playable if i.kind == "video"),
        }

        return {
            "hero": hero,
            "continue": continue_rows,
            "rows": rows,
            "stats": stats,
            "needs_attention": needs_attention,
            "libraries": [
                library_payload(lib, include_private=user.role == "admin")
                for lib in libraries
            ],
        }
