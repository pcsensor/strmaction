"""系统 API：健康检查、数据导出 / 导入。"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Body, Depends
from sqlalchemy import text
from sqlmodel import Session, select

from .. import __version__
from ..config_store import SettingsService
from ..deps import get_engine, get_settings
from ..errors import APIError
from ..models import Item, Library, PlayProgress, utcnow
from ..schemas import ImportBody

router = APIRouter(tags=["system"])

ITEM_EXPORT_FIELDS = [
    "id",
    "library_id",
    "parent_id",
    "kind",
    "title",
    "original_title",
    "sort_title",
    "year",
    "season_no",
    "episode_no",
    "overview",
    "tagline",
    "runtime_min",
    "rating",
    "provider",
    "provider_id",
    "external_ids",
    "genres",
    "cast",
    "certification",
    "alt_titles",
    "trailer_key",
    "collection",
    "poster_path",
    "backdrop_path",
    "logo_path",
    "still_path",
    "color_primary",
    "locked_fields",
    "meta_hash",
    "match_state",
    "status",
    "air_date",
    "created_at",
    "updated_at",
    "deleted_at",
    "parse_confidence",
    "parse_payload",
]

LIBRARY_EXPORT_FIELDS = [
    "id",
    "name",
    "root_path",
    "type",
    "provider",
    "language",
    "scan_cron",
    "enabled",
    "created_at",
    "last_scan_at",
    "provider_priority",
    "tvdb_season_type",
    "template",
    "auto_scrape",
    "play_headers",
]


@router.get("/health")
def health(engine=Depends(get_engine)):
    db_ok = True
    try:
        with Session(engine) as session:
            session.exec(text("SELECT 1"))
    except Exception:
        db_ok = False
    return {
        "ok": db_ok,
        "version": __version__,
        "time": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "db": "sqlite",
    }


@router.get("/export")
def export_data(
    engine=Depends(get_engine),
    settings: SettingsService = Depends(get_settings),
):
    with Session(engine) as session:
        libraries = session.exec(select(Library)).all()
        items = session.exec(select(Item)).all()
        progress = session.exec(select(PlayProgress)).all()
        payload = {
            "version": 1,
            "app": "StrmAction",
            "app_version": __version__,
            "exported_at": utcnow(),
            "libraries": [
                {field: getattr(lib, field) for field in LIBRARY_EXPORT_FIELDS}
                for lib in libraries
            ],
            "items": [
                {field: getattr(item, field) for field in ITEM_EXPORT_FIELDS}
                for item in items
            ],
            "progress": [
                {
                    "item_id": row.item_id,
                    "position_ms": row.position_ms,
                    "duration_ms": row.duration_ms,
                    "finished": row.finished,
                    "updated_at": row.updated_at,
                }
                for row in progress
            ],
            "settings": settings.public(),
            "note": "导出不包含 .strm 播放地址（视为凭证）；恢复后请重新扫描目录。",
        }
    return payload


def _copy_item(raw: dict[str, Any], session: Session, library_id: int, parent_id: int | None) -> Item:
    item = Item(
        library_id=library_id,
        parent_id=parent_id,
        kind=raw.get("kind") or "movie",
        title=raw.get("title") or "未命名",
        created_at=raw.get("created_at") or utcnow(),
        updated_at=raw.get("updated_at") or utcnow(),
    )
    for field in ITEM_EXPORT_FIELDS:
        if field in {"id", "library_id", "parent_id", "kind", "title", "created_at"}:
            continue
        setattr(item, field, raw.get(field))
    session.add(item)
    session.flush()
    return item


@router.post("/import")
def import_data(
    body: ImportBody,
    engine=Depends(get_engine),
    settings: SettingsService = Depends(get_settings),
):
    data = body.data or {}
    if not isinstance(data, dict) or "libraries" not in data:
        raise APIError(400, "INVALID_BACKUP", "不是有效的 StrmAction 导出文件")
    library_map: dict[int, int] = {}
    item_map: dict[int, int] = {}
    counts = {"libraries": 0, "items": 0, "progress": 0}
    with Session(engine) as session:
        for raw in data.get("libraries") or []:
            old_id = raw.get("id")
            root = raw.get("root_path")
            if not root:
                continue
            existing = session.exec(
                select(Library).where(Library.root_path == root)
            ).first()
            if existing is None:
                existing = Library(
                    name=raw.get("name") or "未命名媒体库",
                    root_path=root,
                    type=raw.get("type") or "movie",
                    provider=raw.get("provider") or "tmdb",
                    language=raw.get("language") or "zh-CN",
                    scan_cron=raw.get("scan_cron"),
                    enabled=bool(raw.get("enabled", True)),
                    created_at=raw.get("created_at") or utcnow(),
                    last_scan_at=raw.get("last_scan_at"),
                    provider_priority=raw.get("provider_priority"),
                    tvdb_season_type=raw.get("tvdb_season_type"),
                    template=raw.get("template"),
                    auto_scrape=bool(raw.get("auto_scrape", True)),
                    play_headers=raw.get("play_headers"),
                )
                session.add(existing)
                session.flush()
                counts["libraries"] += 1
            if old_id is not None:
                library_map[int(old_id)] = existing.id or 0
        fallback_library = next(iter(library_map.values()), None)

        order = {"movie": 0, "series": 1, "season": 2, "episode": 3, "video": 3}
        items = sorted(
            data.get("items") or [], key=lambda r: order.get(r.get("kind"), 4)
        )
        for raw in items:
            old_id = raw.get("id")
            kind = raw.get("kind") or "movie"
            library_id = library_map.get(int(raw.get("library_id") or 0), fallback_library)
            if not library_id:
                continue
            parent_id = None
            if raw.get("parent_id") is not None:
                parent_id = item_map.get(int(raw["parent_id"]))
                if parent_id is None and kind in {"season", "episode", "video"}:
                    continue
            existing = session.exec(
                select(Item).where(
                    Item.library_id == library_id,
                    Item.kind == kind,
                    Item.parent_id == parent_id,
                    Item.title == (raw.get("title") or "未命名"),
                    Item.year == raw.get("year"),
                    Item.season_no == raw.get("season_no"),
                    Item.episode_no == raw.get("episode_no"),
                )
            ).first()
            if existing is None:
                existing = _copy_item(raw, session, library_id, parent_id)
                counts["items"] += 1
            else:
                for field in ITEM_EXPORT_FIELDS:
                    if field in {"id", "library_id", "parent_id", "kind", "title"}:
                        continue
                    value = raw.get(field)
                    if value is not None:
                        setattr(existing, field, value)
                session.add(existing)
            if old_id is not None:
                item_map[int(old_id)] = existing.id or 0
        session.commit()

        for raw in data.get("progress") or []:
            old_item = raw.get("item_id")
            item_id = item_map.get(int(old_item or 0))
            if not item_id:
                continue
            row = session.exec(
                select(PlayProgress).where(PlayProgress.item_id == item_id)
            ).first()
            if row is None:
                row = PlayProgress(item_id=item_id, updated_at=utcnow())
            row.position_ms = int(raw.get("position_ms") or 0)
            row.duration_ms = raw.get("duration_ms")
            row.finished = bool(raw.get("finished"))
            row.updated_at = raw.get("updated_at") or utcnow()
            session.add(row)
            counts["progress"] += 1
        session.commit()

    if body.settings and isinstance(data.get("settings"), dict):
        settings.update(data["settings"])
    counts["scan_required"] = True
    return {"ok": True, "imported": counts}
