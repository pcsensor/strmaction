"""系统 API：健康检查、数据导出 / 导入。"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Body, Depends
from sqlalchemy import text
from sqlmodel import Session, select

from .. import __version__
from ..config import mask_play_headers_json
from ..config_store import SettingsService
from ..deps import get_engine, get_settings, require_admin
from ..errors import APIError
from ..models import Item, Library, PlayProgress, User, utcnow
from ..schemas import CurrentUser, ImportBody
from .settings import sanitize_settings_patch, validate_settings_patch

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


def _imported_play_headers(raw: Any) -> str | None:
    """导入备份时丢弃被脱敏的 header，避免把 **** 当成真实凭证。"""
    if not isinstance(raw, str) or not raw:
        return raw if isinstance(raw, str) else None
    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return raw
    if not isinstance(parsed, dict):
        return raw
    cleaned = {
        key: value
        for key, value in parsed.items()
        if value != "****"
    }
    return json.dumps(cleaned, ensure_ascii=False) if cleaned else None


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
    _admin: CurrentUser = Depends(require_admin),
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
                {
                    field: (
                        mask_play_headers_json(getattr(lib, field))
                        if field == "play_headers"
                        else getattr(lib, field)
                    )
                    for field in LIBRARY_EXPORT_FIELDS
                }
                for lib in libraries
            ],
            "items": [
                {field: getattr(item, field) for field in ITEM_EXPORT_FIELDS}
                for item in items
            ],
            "progress": [
                {
                    "user_id": row.user_id,
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
    admin: CurrentUser = Depends(require_admin),
    engine=Depends(get_engine),
    settings: SettingsService = Depends(get_settings),
):
    data = body.data or {}
    if not isinstance(data, dict) or "libraries" not in data:
        raise APIError(400, "INVALID_BACKUP", "不是有效的 StrmAction 导出文件")
    library_map: dict[int, int] = {}
    item_map: dict[int, int] = {}
    counts = {"libraries": 0, "items": 0, "progress": 0, "skipped": 0}
    warnings: list[str] = []
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
                    play_headers=_imported_play_headers(raw.get("play_headers")),
                )
                session.add(existing)
                session.flush()
                counts["libraries"] += 1
            if old_id is not None:
                library_map[int(old_id)] = existing.id or 0
        raw_items = [
            raw for raw in (data.get("items") or []) if isinstance(raw, dict)
        ]
        raw_by_old_id: dict[int, dict[str, Any]] = {}
        anonymous_items: list[dict[str, Any]] = []
        for raw in raw_items:
            old = raw.get("id")
            if old is None:
                anonymous_items.append(raw)
                continue
            try:
                old_id = int(old)
            except (TypeError, ValueError):
                anonymous_items.append(raw)
                continue
            if old_id in raw_by_old_id:
                warnings.append(f"备份中存在重复条目 ID {old_id}，已使用最后一条")
            raw_by_old_id[old_id] = raw

        fallback_library = next(iter(library_map.values()), None) if len(library_map) == 1 else None

        def _library_for(raw: dict[str, Any]) -> int | None:
            library_id = raw.get("library_id")
            if library_id is not None:
                try:
                    mapped = library_map.get(int(library_id))
                except (TypeError, ValueError):
                    mapped = None
                if mapped:
                    return mapped
            # 只有目标环境中恰好只有一个库时才允许回退，避免多库备份串库。
            return fallback_library

        def _upsert_item(
            raw: dict[str, Any], library_id: int, parent_id: int | None
        ) -> Item:
            kind = raw.get("kind") or "movie"
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
            if existing.id is None:
                session.flush()
            return existing

        visiting: set[int] = set()

        def _import_item(old_id: int) -> int | None:
            if old_id in item_map:
                return item_map[old_id]
            if old_id in visiting:
                warnings.append(f"条目 {old_id} 的父引用形成循环，已跳过")
                counts["skipped"] += 1
                return None
            raw = raw_by_old_id.get(old_id)
            if raw is None:
                return None
            kind = raw.get("kind") or "movie"
            library_id = _library_for(raw)
            if not library_id:
                warnings.append(f"条目 {old_id} 找不到目标媒体库，已跳过")
                counts["skipped"] += 1
                return None
            visiting.add(old_id)
            try:
                parent_id = None
                parent_old = raw.get("parent_id")
                if parent_old is not None:
                    try:
                        parent_id = _import_item(int(parent_old))
                    except (TypeError, ValueError):
                        parent_id = None
                    if parent_id is None and kind in {
                        "folder", "season", "episode", "video"
                    }:
                        warnings.append(f"条目 {old_id} 的父条目不存在，已跳过")
                        counts["skipped"] += 1
                        return None
                existing = _upsert_item(raw, library_id, parent_id)
                item_map[old_id] = int(existing.id or 0)
                return existing.id
            finally:
                visiting.discard(old_id)

        # 递归导入会自动先建父节点；不再依赖 kind 排序，folder/video 不会再错序。
        for old_id in raw_by_old_id:
            _import_item(old_id)

        # 没有旧 ID 的条目无法被其它条目引用，直接按顶层条目导入。
        for raw in anonymous_items:
            library_id = _library_for(raw)
            if not library_id:
                counts["skipped"] += 1
                warnings.append(f"条目 {raw.get('title') or '未命名'} 找不到目标媒体库，已跳过")
                continue
            _upsert_item(raw, library_id, None)
        session.commit()

        for raw in data.get("progress") or []:
            old_item = raw.get("item_id")
            item_id = item_map.get(int(old_item or 0))
            if not item_id:
                continue
            # 新备份带 user_id；旧备份没有用户概念，归到执行导入的管理员。
            target_user_id = admin.id
            raw_user = raw.get("user_id")
            if raw_user is not None:
                try:
                    candidate = int(raw_user)
                except (TypeError, ValueError):
                    candidate = admin.id
                if session.get(User, candidate) is not None:
                    target_user_id = candidate
            row = session.exec(
                select(PlayProgress).where(
                    PlayProgress.item_id == item_id,
                    PlayProgress.user_id == target_user_id,
                )
            ).first()
            if row is None:
                row = PlayProgress(
                    item_id=item_id,
                    user_id=target_user_id,
                    updated_at=utcnow(),
                )
            row.position_ms = int(raw.get("position_ms") or 0)
            row.duration_ms = raw.get("duration_ms")
            row.finished = bool(raw.get("finished"))
            row.updated_at = raw.get("updated_at") or utcnow()
            session.add(row)
            counts["progress"] += 1
        session.commit()

    if body.settings and isinstance(data.get("settings"), dict):
        # 备份里可能包含旧版本的 server.data_dir 等不可变字段，先剥离再校验。
        incoming_settings = sanitize_settings_patch(data["settings"])
        validate_settings_patch(incoming_settings)
        settings.update(incoming_settings)
    counts["scan_required"] = True
    return {"ok": True, "imported": counts, "warnings": warnings[-50:]}
