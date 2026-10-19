"""首页聚合 API（§13 GET /home）。"""

from __future__ import annotations

import json
from collections import Counter
from typing import Any

from fastapi import APIRouter, Depends
from sqlmodel import Session, select

from ..deps import get_engine
from ..models import Item, Library, PlayProgress
from ..serializers import (
    episode_code,
    item_summary,
    library_payload,
    parse_json,
    ready_item_ids,
    series_of,
)

router = APIRouter(tags=["home"])


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
def home(engine=Depends(get_engine)):
    with Session(engine) as session:
        ready = ready_item_ids(session)
        all_items = session.exec(
            select(Item).where(
                Item.deleted_at == None,  # noqa: E711
                Item.kind.in_(["movie", "series", "video"]),
            )
        ).all()
        playable = [i for i in all_items if i.id in ready]

        hero_candidates = [
            i
            for i in playable
            if i.kind in {"movie", "series"} and i.backdrop_path
        ]
        hero_candidates.sort(
            key=lambda i: (-(i.rating or 0), i.updated_at or ""), reverse=False
        )
        hero = [_hero(i) for i in hero_candidates[:6]]

        continue_rows: list[dict[str, Any]] = []
        progress_rows = session.exec(
            select(PlayProgress)
            .where(
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
            [i for i in playable if i.kind in {"movie", "series"}],
            key=lambda i: i.created_at or "",
            reverse=True,
        )[:20]
        top_rated = sorted(
            [i for i in playable if i.rating],
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
        for item in playable:
            if item.kind not in {"movie", "series"}:
                continue
            for genre in parse_json(item.genres, []) or []:
                genre_counter[str(genre)] += 1
        for genre, _count in genre_counter.most_common(4):
            items = [
                i
                for i in playable
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
        libraries = session.exec(select(Library).order_by(Library.id)).all()
        for library in libraries:
            lib_items = [
                i
                for i in playable
                if i.library_id == library.id
                and i.kind in {"movie", "series", "video"}
            ]
            if not lib_items:
                continue
            lib_items.sort(key=lambda i: i.created_at or "", reverse=True)
            rows.append(
                {
                    "key": f"library:{library.id}",
                    "title": library.name,
                    "items": [item_summary(i) for i in lib_items[:20]],
                }
            )

        needs_attention = sum(
            1
            for i in all_items
            if i.kind in {"movie", "series"}
            and (
                i.match_state == "failed"
                or (i.match_state == "pending" and i.provider)
            )
        )
        stats = {
            "movies": sum(1 for i in playable if i.kind == "movie"),
            "series": sum(1 for i in playable if i.kind == "series"),
            "episodes": len(
                session.exec(
                    select(Item).where(
                        Item.kind == "episode",
                        Item.deleted_at == None,  # noqa: E711
                    )
                ).all()
            ),
            "videos": sum(1 for i in playable if i.kind == "video"),
        }

        return {
            "hero": hero,
            "continue": continue_rows,
            "rows": rows,
            "stats": stats,
            "needs_attention": needs_attention,
            "libraries": [library_payload(lib) for lib in libraries],
        }
