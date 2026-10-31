"""首页聚合 API（§13 GET /home）。v0.9: 支持多用户和管理员去重逻辑。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import and_, case, func, or_, true
from sqlmodel import Session, select

from ..deps import get_engine, get_current_user, get_accessible_library_ids
from ..models import Item, Library, PlayProgress
from ..schemas import CurrentUser
from ..serializers import (
    episode_code,
    item_summary,
    library_payload,
    parse_json,
    playlist_key_map,
    ready_item_query,
    series_of,
)

router = APIRouter(tags=["home"])

ITEM_KINDS = ["movie", "series", "video", "folder"]


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


def _base_query(
    accessible_ids: list[int] | None, kinds: list[str], library_id: int | None = None
):
    query = select(Item).where(
        Item.deleted_at == None,  # noqa: E711
        Item.kind.in_(kinds),
        Item.id.in_(ready_item_query(library_id)),
    )
    if accessible_ids is not None:
        query = query.where(Item.library_id.in_(accessible_ids))
    if library_id is not None:
        query = query.where(Item.library_id == library_id)
    return query


def _take(
    session: Session,
    query,
    *,
    order_by,
    limit: int,
    dedupe: bool,
) -> list[Item]:
    # 管理员去重后再截断，因此先多取一些候选；普通用户可直接限量。
    rows = session.exec(
        query.order_by(*order_by).limit(limit * 3 if dedupe else limit)
    ).all()
    if dedupe:
        rows = _dedupe_items_for_admin(rows)
    return rows[:limit]


@router.get("/home")
def home(user: CurrentUser = Depends(get_current_user), engine=Depends(get_engine)):
    """v0.9: 首页聚合，管理员看所有库（去重+标注多库），普通用户只看授权库。"""
    with Session(engine) as session:
        accessible_ids = get_accessible_library_ids(user, engine)
        if accessible_ids is not None and not accessible_ids:
            return {
                "hero": [],
                "continue": [],
                "rows": [],
                "stats": {"movies": 0, "series": 0, "episodes": 0, "videos": 0},
                "needs_attention": 0,
                "libraries": [],
            }

        dedupe = user.role == "admin"

        # 每个区块只查需要返回的行，不再把整个媒体库加载到 Python。
        hero_candidates = _take(
            session,
            _base_query(accessible_ids, ["movie", "series"]).where(
                Item.backdrop_path != None  # noqa: E711
            ),
            order_by=(Item.rating.desc(), Item.updated_at.desc()),
            limit=6,
            dedupe=dedupe,
        )
        hero = [_hero(i) for i in hero_candidates]

        recent = _take(
            session,
            _base_query(accessible_ids, ["movie", "series"]),
            order_by=(Item.created_at.desc(),),
            limit=20,
            dedupe=dedupe,
        )
        top_rated = _take(
            session,
            _base_query(accessible_ids, ["movie", "series"]).where(
                Item.rating != None  # noqa: E711
            ),
            order_by=(Item.rating.desc(), Item.created_at.desc()),
            limit=20,
            dedupe=dedupe,
        )

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

        # 按类型：先在数据库侧统计前 4 个类型，再分别限量取条目。
        genre_values = func.json_each(
            case((func.json_valid(Item.genres), Item.genres), else_="[]")
        ).table_valued("value")
        genre_query = (
            select(genre_values.c.value, func.count().label("count"))
            .select_from(Item)
            .join(genre_values, true())
            .where(
                Item.deleted_at == None,  # noqa: E711
                Item.kind.in_(["movie", "series"]),
                Item.id.in_(ready_item_query()),
            )
        )
        if accessible_ids is not None:
            genre_query = genre_query.where(Item.library_id.in_(accessible_ids))
        genre_rows = session.exec(
            genre_query.group_by(genre_values.c.value)
            .order_by(func.count().desc())
            .limit(4)
        ).all()
        for genre, _count in genre_rows:
            if not genre:
                continue
            items = _take(
                session,
                _base_query(accessible_ids, ["movie", "series"]).where(
                    Item.genres.like(f'%"{genre}"%')
                ),
                order_by=(Item.rating.desc(), Item.created_at.desc()),
                limit=20,
                dedupe=dedupe,
            )
            if items:
                rows.append(
                    {
                        "key": f"genre:{genre}",
                        "title": str(genre),
                        "items": [item_summary(i) for i in items],
                    }
                )

        # 按媒体库
        libraries_query = select(Library).order_by(Library.id)
        if accessible_ids is not None:
            libraries_query = libraries_query.where(Library.id.in_(accessible_ids))
        libraries = session.exec(libraries_query).all()

        for library in libraries:
            if library.type in {"home", "course"}:
                lib_items = _take(
                    session,
                    _base_query(accessible_ids, ["folder", "video"], library.id).where(
                        Item.parent_id == None  # noqa: E711
                    ),
                    order_by=(Item.episode_no.asc(), Item.title.asc()),
                    limit=20,
                    dedupe=False,
                )
            else:
                lib_items = _take(
                    session,
                    _base_query(accessible_ids, ["movie", "series", "video"], library.id),
                    order_by=(Item.created_at.desc(),),
                    limit=20,
                    dedupe=False,
                )
            if not lib_items:
                continue
            rows.append(
                {
                    "key": f"library:{library.id}",
                    "title": library.name,
                    "items": [item_summary(i) for i in lib_items],
                }
            )

        needs_attention = 0
        if user.role == "admin":
            attention_query = select(func.count(Item.id)).where(
                Item.deleted_at == None,  # noqa: E711
                Item.kind.in_(["movie", "series"]),
                or_(
                    Item.match_state == "failed",
                    and_(Item.match_state == "pending", Item.provider != None),  # noqa: E711
                ),
            )
            if accessible_ids is not None:
                attention_query = attention_query.where(
                    Item.library_id.in_(accessible_ids)
                )
            needs_attention = int(session.exec(attention_query).one() or 0)

        # 统计：数据库聚合，不再加载全部条目。
        stats_query = (
            select(Item.kind, func.count(Item.id))
            .where(
                Item.deleted_at == None,  # noqa: E711
                Item.kind.in_(ITEM_KINDS),
                Item.id.in_(ready_item_query()),
            )
            .group_by(Item.kind)
        )
        if accessible_ids is not None:
            stats_query = stats_query.where(Item.library_id.in_(accessible_ids))
        kind_counts = {str(kind): int(count) for kind, count in session.exec(stats_query).all()}

        episode_query = select(func.count(Item.id)).where(
            Item.deleted_at == None,  # noqa: E711
            Item.kind == "episode",
            Item.id.in_(ready_item_query()),
        )
        if accessible_ids is not None:
            episode_query = episode_query.where(Item.library_id.in_(accessible_ids))
        stats = {
            "movies": kind_counts.get("movie", 0),
            "series": kind_counts.get("series", 0),
            "episodes": int(session.exec(episode_query).one() or 0),
            "videos": kind_counts.get("video", 0),
        }

        # 继续观看：只查最近 200 条进度，并批量计算播放列表根。
        progress_query = (
            select(PlayProgress)
            .join(Item, Item.id == PlayProgress.item_id)
            .where(
                PlayProgress.user_id == user.id,
                PlayProgress.finished == False,  # noqa: E712
                PlayProgress.position_ms > 0,
                PlayProgress.dismissed == False,  # noqa: E712
            )
        )
        if accessible_ids is not None:
            progress_query = progress_query.where(Item.library_id.in_(accessible_ids))
        progress_rows = session.exec(
            progress_query.order_by(
                PlayProgress.updated_at.desc(), PlayProgress.id.desc()
            ).limit(200)
        ).all()
        progress_items = (
            session.exec(
                select(Item).where(Item.id.in_([row.item_id for row in progress_rows]))
            ).all()
            if progress_rows
            else []
        )
        item_map = {i.id: i for i in progress_items}
        ready_progress_ids = (
            set(
                session.exec(
                    select(Item.id).where(
                        Item.id.in_(list(item_map)),
                        Item.id.in_(ready_item_query()),
                    )
                ).all()
            )
            if item_map
            else set()
        )
        playlist_keys = playlist_key_map(session, progress_items)

        continue_rows: list[dict[str, Any]] = []
        grouped: dict[int, tuple[PlayProgress, Item]] = {}
        for row in progress_rows:
            item = item_map.get(row.item_id)
            if item is None or item.id not in ready_progress_ids:
                continue
            grouped.setdefault(playlist_keys.get(item.id, item.id), (row, item))
        for row, item in grouped.values():
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
            display_summary = item_summary(display)
            continue_rows.append(
                {
                    **display_summary,
                    "continue_item_id": item.id,
                    "title": display.title,
                    "subtitle": subtitle,
                    "poster": display_summary["poster"],
                    "backdrop": display_summary["backdrop"],
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
