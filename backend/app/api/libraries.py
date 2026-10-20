"""媒体库管理 API。"""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, Depends, Query
from sqlalchemy import delete, func, update
from sqlmodel import Session, select

from ..deps import (
    get_engine,
    get_scheduler,
    get_tasks,
    get_current_user,
    require_admin,
    get_accessible_library_ids,
)
from ..errors import APIError
from ..models import (
    ImageTask,
    Item,
    Library,
    MediaFile,
    PlayProgress,
    PlaySession,
    PlayToken,
    Setting,
    UserLibraryAccess,
    utcnow,
)
from ..jobs import SchedulerService, TaskManager
from ..players import clean_headers
from ..scanner.walker import ensure_library_root
from ..schemas import LibraryCreate, LibraryPatch, CurrentUser
from ..serializers import library_payload, ready_item_ids

router = APIRouter(prefix="/libraries", tags=["libraries"])

VALID_TYPES = {"movie", "tv", "home", "course"}
VALID_PROVIDERS = {"tmdb", "tvdb"}


def _counts(session: Session, library_id: int) -> dict[str, int]:
    ready = ready_item_ids(session, library_id)
    counts: dict[str, int] = {}
    if ready:
        rows = session.exec(
            select(Item.kind, func.count(Item.id))
            .where(
                Item.library_id == library_id,
                Item.deleted_at == None,  # noqa: E711
                Item.id.in_(ready),
            )
            .group_by(Item.kind)
        ).all()
        counts = {str(kind): int(count) for kind, count in rows}
    files = session.exec(
        select(func.count(MediaFile.id)).where(
            MediaFile.library_id == library_id,
            MediaFile.invalid == False,  # noqa: E712
            MediaFile.missing == False,  # noqa: E712
        )
    ).one()
    counts["files"] = int(files or 0)
    return counts


def _validate_root(root_path: str, session: Session, exclude_id: int | None = None) -> str:
    root_path = (root_path or "").strip()
    ok, message = ensure_library_root(root_path)
    if not ok:
        raise APIError(400, "INVALID_ROOT", message)
    real = str(Path(root_path).resolve())
    query = select(Library).where(Library.root_path == real)
    existing = session.exec(query).first()
    if existing and existing.id != exclude_id:
        raise APIError(409, "ROOT_EXISTS", "该目录已被其他媒体库使用")
    return real


def _priority(value: list[str] | None) -> str | None:
    if value is None:
        return None
    cleaned = [v for v in value if v in VALID_PROVIDERS]
    return json.dumps(cleaned, ensure_ascii=False)


def _play_headers(value: dict[str, str] | None) -> str | None:
    if value is None:
        return None
    cleaned = clean_headers(value)
    return json.dumps(cleaned, ensure_ascii=False) if cleaned else None


@router.get("")
def list_libraries(
    user: CurrentUser = Depends(get_current_user),
    engine=Depends(get_engine),
):
    """v0.9: 获取用户可访问的媒体库列表。"""
    with Session(engine) as session:
        # 管理员看所有库
        if user.role == "admin":
            libraries = session.exec(select(Library).order_by(Library.id)).all()
        else:
            # 普通用户只看授权的库
            accessible_ids = get_accessible_library_ids(user, engine)
            if not accessible_ids:
                return {"libraries": []}
            libraries = session.exec(
                select(Library)
                .where(Library.id.in_(accessible_ids))
                .order_by(Library.id)
            ).all()
        return {
            "libraries": [
                library_payload(
                    library,
                    _counts(session, library.id or 0),
                    include_private=user.role == "admin",
                )
                for library in libraries
            ]
        }


@router.post("", status_code=201)
def create_library(
    body: LibraryCreate,
    _admin: CurrentUser = Depends(require_admin),
    engine=Depends(get_engine),
    scheduler: SchedulerService = Depends(get_scheduler),
):
    """v0.9: Create library (admin only)."""
    if body.type not in VALID_TYPES:
        raise APIError(400, "INVALID_TYPE", "未知的媒体库类型")
    name = (body.name or "").strip()
    if not name:
        raise APIError(400, "INVALID_NAME", "媒体库名称不能为空")
    with Session(engine) as session:
        root = _validate_root(body.root_path, session)
        priority = _priority(body.provider_priority)
        providers = json.loads(priority) if priority else []
        library = Library(
            name=name,
            root_path=root,
            type=body.type,
            provider=(providers[0] if providers else "tmdb"),
            scan_cron=(body.scan_cron or "").strip() or None,
            enabled=body.enabled,
            auto_scrape=body.auto_scrape,
            template=(body.template or "").strip() or None,
            tvdb_season_type=body.tvdb_season_type,
            provider_priority=priority,
            play_headers=_play_headers(body.play_headers),
            created_at=utcnow(),
        )
        session.add(library)
        session.commit()
        session.refresh(library)
        payload = library_payload(library, _counts(session, library.id or 0))
    scheduler.reload()
    return payload


@router.patch("/{library_id}")
def update_library(
    library_id: int,
    body: LibraryPatch,
    _admin: CurrentUser = Depends(require_admin),
    engine=Depends(get_engine),
    scheduler: SchedulerService = Depends(get_scheduler),
):
    """v0.9: Update library (admin only)."""
    with Session(engine) as session:
        library = session.get(Library, library_id)
        if library is None:
            raise APIError(404, "LIBRARY_NOT_FOUND", "媒体库不存在")
        fields = body.model_fields_set
        if "root_path" in fields and body.root_path is not None:
            library.root_path = _validate_root(body.root_path, session, library_id)
        if "name" in fields and body.name is not None:
            library.name = body.name.strip() or library.name
        if "type" in fields and body.type is not None:
            if body.type not in VALID_TYPES:
                raise APIError(400, "INVALID_TYPE", "未知的媒体库类型")
            library.type = body.type
        if "scan_cron" in fields:
            library.scan_cron = (body.scan_cron or "").strip() or None
        if "enabled" in fields and body.enabled is not None:
            library.enabled = body.enabled
        if "auto_scrape" in fields and body.auto_scrape is not None:
            library.auto_scrape = body.auto_scrape
        if "template" in fields:
            library.template = (body.template or "").strip() or None
        if "tvdb_season_type" in fields:
            library.tvdb_season_type = body.tvdb_season_type
        if "provider_priority" in fields:
            library.provider_priority = _priority(body.provider_priority)
        if "play_headers" in fields:
            library.play_headers = _play_headers(body.play_headers)
        session.add(library)
        session.commit()
        session.refresh(library)
        payload = library_payload(library, _counts(session, library.id or 0))
    scheduler.reload()
    return payload


@router.delete("/{library_id}", status_code=204)
def delete_library(
    library_id: int,
    _admin: CurrentUser = Depends(require_admin),
    engine=Depends(get_engine),
    scheduler: SchedulerService = Depends(get_scheduler),
):
    with Session(engine) as session:
        library = session.get(Library, library_id)
        if library is None:
            raise APIError(404, "LIBRARY_NOT_FOUND", "媒体库不存在")
        # 清除用户授权
        session.exec(
            delete(UserLibraryAccess).where(UserLibraryAccess.library_id == library_id)
        )
        item_ids = [
            row
            for row in session.exec(
                select(Item.id).where(Item.library_id == library_id)
            ).all()
        ]
        if item_ids:
            for model in (ImageTask, PlayProgress, PlaySession, PlayToken):
                session.exec(
                    delete(model).where(model.item_id.in_(item_ids))
                )
        session.exec(delete(MediaFile).where(MediaFile.library_id == library_id))
        # 解除 item 之间的自引用 parent_id 约束，彻底避免多层目录自引用导致的外键冲突
        session.exec(
            update(Item).where(Item.library_id == library_id).values(parent_id=None)
        )
        session.exec(delete(Item).where(Item.library_id == library_id))
        session.exec(
            delete(Setting).where(Setting.key == f"scanner:parser_version:{library_id}")
        )
        session.delete(library)
        session.commit()
    scheduler.reload()
    return None


@router.post("/{library_id}/scan")
async def scan_library(
    library_id: int,
    _admin: CurrentUser = Depends(require_admin),
    engine=Depends(get_engine),
    tasks: TaskManager = Depends(get_tasks),
):
    with Session(engine) as session:
        if session.get(Library, library_id) is None:
            raise APIError(404, "LIBRARY_NOT_FOUND", "媒体库不存在")
    task_id = tasks.start_scan(library_id)
    return {"task_id": task_id, "status": "running"}


@router.post("/{library_id}/scrape")
async def scrape_library(
    library_id: int,
    mode: str = Query("pending", pattern="^(pending|refresh)$"),
    _admin: CurrentUser = Depends(require_admin),
    engine=Depends(get_engine),
    tasks: TaskManager = Depends(get_tasks),
):
    with Session(engine) as session:
        if session.get(Library, library_id) is None:
            raise APIError(404, "LIBRARY_NOT_FOUND", "媒体库不存在")
    task_id = tasks.start_scrape(library_id, mode=mode)
    return {"task_id": task_id, "status": "running"}


@router.post("/{library_id}/refresh")
async def refresh_library(
    library_id: int,
    _admin: CurrentUser = Depends(require_admin),
    engine=Depends(get_engine),
    tasks: TaskManager = Depends(get_tasks),
):
    with Session(engine) as session:
        if session.get(Library, library_id) is None:
            raise APIError(404, "LIBRARY_NOT_FOUND", "媒体库不存在")
    task_id = tasks.start_refresh_library(library_id)
    return {"task_id": task_id, "status": "running"}
