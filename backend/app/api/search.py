"""全库搜索 API。v0.9: 支持多用户权限过滤。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import case, exists, func, or_, true
from sqlmodel import Session, select

from ..deps import get_engine, get_current_user, get_accessible_library_ids
from ..models import Item
from ..schemas import CurrentUser
from ..serializers import item_summary, ready_item_query

router = APIRouter(tags=["search"])


def _genre_values():
    return func.json_each(
        case((func.json_valid(Item.genres), Item.genres), else_="[]")
    ).table_valued("value")


def _genre_filter_clause(genre_term: str):
    values = _genre_values()
    return exists(select(1).select_from(values).where(values.c.value == genre_term))


def _escape_like(term: str) -> str:
    return term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


@router.get("/search")
def search(
    q: str = Query("", min_length=0, max_length=100),
    limit: int = Query(60, ge=1, le=200),
    genre: str | None = Query(None),
    user: CurrentUser = Depends(get_current_user),
    engine=Depends(get_engine),
):
    """v0.9: 全库搜索，按用户可访问库过滤。"""
    term = (q or "").strip()
    genre_term = (genre or "").strip() or None

    with Session(engine) as session:
        accessible_ids = get_accessible_library_ids(user, engine)
        if accessible_ids is not None and not accessible_ids:
            return {"q": term, "items": [], "total": 0, "genres": []}

        ready_subquery = ready_item_query()
        base_query = select(Item).where(
            Item.deleted_at == None,  # noqa: E711
            Item.id.in_(ready_subquery),
        )
        if accessible_ids is not None:
            base_query = base_query.where(Item.library_id.in_(accessible_ids))

        if not term:
            query = base_query.where(Item.kind.in_(["movie", "series"]))
            if genre_term:
                query = query.where(_genre_filter_clause(genre_term))
            total = session.exec(select(func.count()).select_from(query.subquery())).one()
            results = session.exec(
                query.order_by(Item.rating.desc(), Item.created_at.desc()).limit(limit)
            ).all()
            genres = _genre_counts(session, ready_subquery, accessible_ids)
            return {
                "q": "",
                "items": [item_summary(r) for r in results],
                "total": total,
                "genres": genres,
            }

        pattern = f"%{_escape_like(term)}%"
        query = base_query.where(
            Item.kind.in_(["movie", "series", "video"]),
            or_(
                Item.title.like(pattern, escape="\\"),
                Item.original_title.like(pattern, escape="\\"),
                Item.alt_titles.like(pattern, escape="\\"),
                Item.cast.like(pattern, escape="\\"),
            ),
        )
        if genre_term:
            query = query.where(_genre_filter_clause(genre_term))

        lowered = term.lower()
        total = session.exec(select(func.count()).select_from(query.subquery())).one()
        results = session.exec(
            query.order_by(
                case((func.lower(Item.title) == lowered, 0), else_=1),
                case(
                    (func.lower(Item.title).startswith(lowered, autoescape=True), 0),
                    else_=1,
                ),
                Item.rating.desc(),
                Item.created_at.desc(),
            ).limit(limit)
        ).all()
        return {
            "q": term,
            "items": [item_summary(r) for r in results],
            "total": total,
            "genres": _genre_counts(session, ready_subquery, accessible_ids),
        }


def _genre_counts(
    session: Session, ready_subquery, accessible_ids: list[int] | None
) -> list[dict[str, Any]]:
    """类型统计在数据库侧完成，避免加载全库 genres JSON。"""
    values = _genre_values()
    query = (
        select(values.c.value, func.count().label("count"))
        .select_from(Item)
        .join(values, true())
        .where(
            Item.deleted_at == None,  # noqa: E711
            Item.kind.in_(["movie", "series"]),
            Item.id.in_(ready_subquery),
        )
    )
    if accessible_ids is not None:
        query = query.where(Item.library_id.in_(accessible_ids))
    rows = session.exec(
        query.group_by(values.c.value)
        .order_by(func.count().desc())
        .limit(12)
    ).all()
    return [
        {"name": str(name), "count": int(count)}
        for name, count in rows
        if name
    ]
