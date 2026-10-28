"""刮削响应缓存（scrape_cache）。"""

from __future__ import annotations

import hashlib
import json
from contextlib import contextmanager
from contextvars import ContextVar
from collections.abc import Iterator
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlmodel import Session, select

from ..models import ScrapeCache, utcnow

_BYPASS_CACHE: ContextVar[bool] = ContextVar("scrape_bypass_cache", default=False)


@contextmanager
def bypass_cache(enabled: bool = True) -> Iterator[None]:
    """仅当前异步刮削请求跳过缓存，避免影响同一 Provider 的并发任务。"""
    token = _BYPASS_CACHE.set(enabled or _BYPASS_CACHE.get())
    try:
        yield
    finally:
        _BYPASS_CACHE.reset(token)


def cache_key(*parts: Any) -> str:
    raw = json.dumps(parts, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def cache_load(engine, provider: str, key: str) -> dict[str, Any] | None:
    if _BYPASS_CACHE.get():
        return None
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with Session(engine) as session:
        row = session.exec(
            select(ScrapeCache).where(
                ScrapeCache.provider == provider,
                ScrapeCache.query_hash == key,
            )
        ).first()
        if row is None:
            return None
        if row.expires_at < now:
            session.delete(row)
            session.commit()
            return None
        try:
            data = json.loads(row.payload)
        except json.JSONDecodeError:
            return None
        return data if isinstance(data, dict) else {"data": data}


def cache_store(
    engine,
    provider: str,
    key: str,
    payload: dict[str, Any],
    ttl_days: int,
) -> None:
    expires = (
        datetime.now(timezone.utc) + timedelta(days=ttl_days)
    ).isoformat(timespec="seconds")
    raw = json.dumps(payload, ensure_ascii=False)
    with Session(engine) as session:
        row = session.exec(
            select(ScrapeCache).where(
                ScrapeCache.provider == provider,
                ScrapeCache.query_hash == key,
            )
        ).first()
        if row is None:
            row = ScrapeCache(
                provider=provider,
                query_hash=key,
                payload=raw,
                expires_at=expires,
            )
        else:
            row.payload = raw
            row.expires_at = expires
        session.add(row)
        session.commit()


def purge_expired(engine) -> int:
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with Session(engine) as session:
        rows = session.exec(select(ScrapeCache).where(ScrapeCache.expires_at < now)).all()
        for row in rows:
            session.delete(row)
        if rows:
            session.commit()
        return len(rows)
