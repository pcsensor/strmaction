"""全库搜索 API。"""

from __future__ import annotations

import json
from collections import Counter
from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import or_
from sqlmodel import Session, select

from ..deps import get_engine
from ..models import Item
from ..serializers import item_summary, ready_item_ids

router = APIRouter(tags=["search"])


@router.get("/search")
def search(
    q: str = Query("", min_length=0, max_length=100),
    limit: int = Query(60, ge=1, le=200),
    genre: str | None = Query(None),
    engine=Depends(get_engine),
):
    term = (q or "").strip()
    with Session(engine) as session:
        if not term:
            ready = ready_item_ids(session)
            rows = session.exec(
                select(Item)
                .where(
                    Item.deleted_at == None,  # noqa: E711
                    Item.kind.in_(["movie", "series"]),
                )
                .order_by(Item.rating.desc())
                .limit(limit)
            ).all()
            rows = [r for r in rows if r.id in ready]
            genres = _genre_counts(session, ready)
            return {
                "q": "",
                "items": [item_summary(r) for r in rows],
                "total": len(rows),
                "genres": genres,
            }
        pattern = f"%{term}%"
        rows = session.exec(
            select(Item)
            .where(
                Item.deleted_at == None,  # noqa: E711
                Item.kind.in_(["movie", "series", "video"]),
                or_(
                    Item.title.like(pattern),
                    Item.original_title.like(pattern),
                    Item.alt_titles.like(pattern),
                    Item.cast.like(pattern),
                ),
            )
            .order_by(Item.rating.desc(), Item.created_at.desc())
        ).all()
        ready = ready_item_ids(session)
        rows = [r for r in rows if r.id in ready]
        if genre:
            rows = [r for r in rows if f'"{genre}"' in (r.genres or "")]
        total = len(rows)
        results = rows[:limit]
        lowered = term.lower()
        results.sort(
            key=lambda r: (
                0 if (r.title or "").lower() == lowered else 1,
                0 if (r.title or "").lower().startswith(lowered) else 1,
                -(r.rating or 0),
            )
        )
        return {
            "q": term,
            "items": [item_summary(r) for r in results],
            "total": total,
            "genres": _genre_counts(session, ready),
        }


def _genre_counts(session: Session, ready: set[int]) -> list[dict[str, Any]]:
    rows = session.exec(
        select(Item.genres).where(
            Item.deleted_at == None,  # noqa: E711
            Item.kind.in_(["movie", "series"]),
        )
    ).all()
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
