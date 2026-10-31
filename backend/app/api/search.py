"""全库搜索 API。v0.9: 支持多用户权限过滤。"""

from __future__ import annotations

import json
from collections import Counter
from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import case, exists, func, or_
from sqlmodel import Session, select

from ..deps import get_engine, get_current_user, get_accessible_library_ids
from ..models import Item
from ..schemas import CurrentUser
from ..serializers import item_summary, ready_item_query

router = APIRouter(tags=["search"])


def _genre_filter_clause(genre_term: str):
    values = func.json_each(case((func.json_valid(Item.genres), Item.genres), else_="[]")).table_valued("value")
    return exists(select(1).select_from(values).where(values.c.value == genre_term))


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
        # 获取用户可访问的库
        accessible_ids = get_accessible_library_ids(user, engine)

        # 构造基础查询
        base_query = select(Item).where(
            Item.deleted_at == None,  # noqa: E711
        )

        # 按用户权限过滤
        if accessible_ids is not None:  # 普通用户
            if not accessible_ids:
                return {"q": term, "items": [], "total": 0, "genres": []}
            base_query = base_query.where(Item.library_id.in_(accessible_ids))

        base_query = base_query.where(Item.id.in_(ready_item_query()))

        if not term:
            query = base_query.where(Item.kind.in_(["movie", "series"]))
            if genre_term:
                query = query.where(_genre_filter_clause(genre_term))
            total = session.exec(select(func.count()).select_from(query.subquery())).one()
            results = session.exec(query.order_by(Item.rating.desc(), Item.created_at.desc()).limit(limit)).all()
            genres = _genre_counts(session, accessible_ids)
            return {
                "q": "",
                "items": [item_summary(r) for r in results],
                "total": total,
                "genres": genres,
            }

        pattern = f"%{term}%"
        query = base_query.where(
            Item.kind.in_(["movie", "series", "video"]),
            or_(
                Item.title.like(pattern),
                Item.original_title.like(pattern),
                Item.alt_titles.like(pattern),
                Item.cast.like(pattern),
            ),
        )
        if genre_term:
            query = query.where(_genre_filter_clause(genre_term))

        lowered = term.lower()
        total = session.exec(select(func.count()).select_from(query.subquery())).one()
        results = session.exec(query.order_by(
            case((func.lower(Item.title) == lowered, 0), else_=1),
            case((func.lower(Item.title).startswith(lowered, autoescape=True), 0), else_=1),
            Item.rating.desc(), Item.created_at.desc(),
        ).limit(limit)).all()
        return {
            "q": term,
            "items": [item_summary(r) for r in results],
            "total": total,
            "genres": _genre_counts(session, accessible_ids),
        }


def _genre_counts(session: Session, accessible_ids: list[int] | None) -> list[dict[str, Any]]:
    """v0.9: 统计类型，按用户可访问库过滤。"""
    query = select(Item.genres).where(
        Item.deleted_at == None,  # noqa: E711
        Item.kind.in_(["movie", "series"]),
        Item.id.in_(ready_item_query()),
    )

    if accessible_ids is not None:
        if not accessible_ids:
            return []
        query = query.where(Item.library_id.in_(accessible_ids))

    rows = session.exec(query).all()
    counter: Counter[str] = Counter()
    for raw in rows:
        try:
            values = json.loads(raw or "[]")
        except (json.JSONDecodeError, TypeError):
            continue
        if isinstance(values, list):
            for value in values:
                if value:
                    counter[str(value)] += 1
    return [{"name": name, "count": count} for name, count in counter.most_common(12)]
