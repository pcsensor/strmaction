"""条目 API：查询、详情、手动修正、进度、已看标记、海报上传。"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from fastapi import APIRouter, Depends, File, Form, Query, Request, UploadFile
from sqlalchemy import or_
from sqlmodel import Session, select

from ..deps import (
    authorize_item_access,
    get_engine,
    get_images,
    get_settings,
    get_tasks,
    get_current_user,
    require_admin,
    get_accessible_library_ids,
)
from ..errors import APIError
from ..images import ImageService
from ..jobs import TaskManager
from ..models import Item, Library, MediaFile, PlayProgress, utcnow
from ..config_store import SettingsService
from ..schemas import ItemPatch, MatchBody, MergeBody, ProgressBody, WatchedBody, CurrentUser
from ..scraper.service import ScrapeService
from ..serializers import (
    episode_code,
    episode_summary,
    item_summary,
    library_payload,
    media_labels,
    parse_json,
    progress_payload,
    ready_item_ids,
    series_of,
)
from ..text import normalize_title

router = APIRouter(prefix="/items", tags=["items"])

LIST_KINDS = {"movie", "series", "season", "episode", "video"}


# ---------------------------------------------------------------------------
# 辅助
# ---------------------------------------------------------------------------


def _get_item(session: Session, item_id: int) -> Item:
    item = session.get(Item, item_id)
    if item is None or item.deleted_at:
        raise APIError(404, "ITEM_NOT_FOUND", "条目不存在")
    return item


def _progress_map(session: Session, item_ids: list[int], user_id: int) -> dict[int, PlayProgress]:
    """v0.9: 获取用户的播放进度映射。"""
    if not item_ids:
        return {}
    rows = session.exec(
        select(PlayProgress).where(
            PlayProgress.item_id.in_(item_ids),
            PlayProgress.user_id == user_id
        )
    ).all()
    return {row.item_id: row for row in rows}


def _media_map(session: Session, item_ids: list[int]) -> dict[int, list[MediaFile]]:
    if not item_ids:
        return {}
    rows = session.exec(
        select(MediaFile).where(
            MediaFile.item_id.in_(item_ids),
            MediaFile.invalid == False,  # noqa: E712
            MediaFile.missing == False,  # noqa: E712
        )
    ).all()
    out: dict[int, list[MediaFile]] = {}
    for media in rows:
        out.setdefault(media.item_id, []).append(media)
    return out


def _media_payload(media: MediaFile) -> dict[str, Any]:
    return {
        "id": media.id,
        "version": media.version,
        "labels": media_labels(media),
        "part": media.part,
        "size_bytes": media.size_bytes,
        "missing": bool(media.missing),
        "mtime": media.mtime,
    }


def _episode_sequence(session: Session, series: Item) -> list[Item]:
    seasons = session.exec(
        select(Item)
        .where(Item.parent_id == series.id, Item.kind == "season")
        .order_by(Item.season_no)
    ).all()
    sequence: list[Item] = []
    for season in seasons:
        episodes = session.exec(
            select(Item)
            .where(Item.parent_id == season.id, Item.kind == "episode")
            .order_by(Item.episode_no)
        ).all()
        sequence.extend(episodes)
    return sequence


def _choose_play_target(session: Session, item: Item, user_id: int) -> Item:
    if item.kind in {"movie", "video", "episode"}:
        return item
    if item.kind == "season":
        episodes = session.exec(
            select(Item)
            .where(Item.parent_id == item.id, Item.kind == "episode")
            .order_by(Item.episode_no)
        ).all()
        if not episodes:
            raise APIError(400, "NO_EPISODE", "该季没有可播放的剧集")
        progress = _progress_map(session, [e.id for e in episodes], user_id)
        for episode in episodes:
            row = progress.get(episode.id)
            if row is None or not row.finished:
                return episode
        return episodes[-1]
    if item.kind == "series":
        sequence = _episode_sequence(session, item)
        if not sequence:
            raise APIError(400, "NO_EPISODE", "该剧没有可播放的剧集")
        progress = _progress_map(session, [e.id for e in sequence], user_id)
        for episode in sequence:
            row = progress.get(episode.id)
            if row is None or not row.finished:
                return episode
        return sequence[-1]
    raise APIError(400, "NOT_PLAYABLE", "该条目不可播放")


def _ready_episodes(session: Session, ready: set[int], episodes: list[Item]) -> list[Item]:
    return [e for e in episodes if e.id in ready]


# ---------------------------------------------------------------------------
# 列表
# ---------------------------------------------------------------------------


@router.get("")
def list_items(
    library_id: int | None = Query(None),
    kind: str | None = Query(None, description="逗号分隔，默认 movie,series,video"),
    q: str | None = Query(None),
    genre: str | None = Query(None),
    year: int | None = Query(None),
    sort: str = Query("recent"),
    page: int = Query(1, ge=1),
    page_size: int = Query(24, ge=1, le=100),
    match_state: str | None = Query(None),
    user: CurrentUser = Depends(get_current_user),
    engine=Depends(get_engine),
):
    """v0.9: 列表查询，按用户可访问库过滤。"""
    kinds = (
        [k.strip() for k in kind.split(",") if k.strip() in LIST_KINDS]
        if kind
        else ["movie", "series", "video"]
    )
    if not kinds:
        kinds = ["movie", "series", "video"]

    with Session(engine) as session:
        # 获取用户可访问的库
        accessible_ids = get_accessible_library_ids(user, engine)

        query = select(Item).where(
            Item.deleted_at == None,  # noqa: E711
            Item.kind.in_(kinds),
        )

        # 按用户权限过滤库
        if accessible_ids is None:
            # 管理员：查看所有库
            if library_id:
                query = query.where(Item.library_id == library_id)
        else:
            # 普通用户：只能查看授权的库
            if not accessible_ids:
                return {"items": [], "total": 0, "page": page, "page_size": page_size}
            if library_id:
                if library_id not in accessible_ids:
                    raise APIError(403, "FORBIDDEN", "无权访问该媒体库")
                query = query.where(Item.library_id == library_id)
            else:
                query = query.where(Item.library_id.in_(accessible_ids))

        if q:
            term = f"%{q.strip()}%"
            query = query.where(
                or_(
                    Item.title.like(term),
                    Item.original_title.like(term),
                    Item.alt_titles.like(term),
                    Item.cast.like(term),
                )
            )
        if genre:
            query = query.where(Item.genres.like(f'%"{genre}"%'))
        if year:
            query = query.where(Item.year == year)
        if match_state:
            query = query.where(Item.match_state == match_state)
        if sort == "rating":
            query = query.order_by(Item.rating.desc(), Item.created_at.desc())
        elif sort == "title":
            query = query.order_by(Item.sort_title.asc())
        elif sort == "year":
            query = query.order_by(Item.year.desc(), Item.created_at.desc())
        elif sort == "updated":
            query = query.order_by(Item.updated_at.desc())
        else:
            query = query.order_by(Item.created_at.desc())
        rows = session.exec(query).all()
        ready = ready_item_ids(session, library_id)
        rows = [row for row in rows if row.id in ready]
        total = len(rows)
        start = (page - 1) * page_size
        page_rows = rows[start : start + page_size]
        progress = _progress_map(session, [r.id for r in page_rows if r.id], user.id)
        media = _media_map(session, [r.id for r in page_rows if r.id])
        items = []
        for row in page_rows:
            files = [f for f in media.get(row.id, []) if not f.invalid]
            badges = media_labels(files[0]) if files else []
            items.append(
                item_summary(row, progress=progress.get(row.id), badges=badges)
            )
    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": max(1, (total + page_size - 1) // page_size),
    }


# ---------------------------------------------------------------------------
# 详情
# ---------------------------------------------------------------------------


@router.get("/{item_id}")
def get_item(
    item_id: int,
    user: CurrentUser = Depends(get_current_user),
    engine=Depends(get_engine),
):
    """v0.9: 获取条目详情，检查用户权限。"""
    with Session(engine) as session:
        item = _get_item(session, item_id)

        # 检查用户是否有权访问该条目所属的库
        accessible_ids = get_accessible_library_ids(user, engine)
        if accessible_ids is not None and item.library_id not in accessible_ids:
            raise APIError(403, "FORBIDDEN", "无权访问该条目")

        library = session.get(Library, item.library_id)
        parent = session.get(Item, item.parent_id) if item.parent_id else None
        series = series_of(session, item)
        ready = ready_item_ids(session)
        progress = _progress_map(
            session,
            [item.id]
            + ([series.id] if series and series.kind == "series" else [])
            + ([parent.id] if parent else []),
            user.id
        )
        media_rows = session.exec(
            select(MediaFile).where(MediaFile.item_id == item.id)
        ).all()
        media_files = [_media_payload(m) for m in media_rows if not m.invalid and not m.missing]

        detail = item_summary(
            item, progress=progress.get(item.id), badges=media_labels(
                next((m for m in media_rows if not m.invalid and not m.missing), None)
            )
        )
        detail.update(
            {
                "overview": item.overview,
                "tagline": item.tagline,
                "genres": parse_json(item.genres, []),
                "cast": parse_json(item.cast, []),
                "collection": parse_json(item.collection, None),
                "alt_titles": parse_json(item.alt_titles, []),
                "external_ids": parse_json(item.external_ids, {}),
                "provider_id": item.provider_id,
                "locked_fields": parse_json(item.locked_fields, []),
                "trailer_key": item.trailer_key,
                "air_date": item.air_date,
            }
        )
        series_summary = None
        if series and series.id != item.id:
            series_summary = item_summary(
                series, progress=progress.get(series.id)
            )
        parent_summary = (
            item_summary(parent, progress=progress.get(parent.id))
            if parent and parent.kind in {"season", "series"}
            else None
        )
        library_info = (
            library_payload(library) if library is not None else None
        )
        needs_attention = item.kind in {"movie", "series"} and item.match_state in {
            "failed",
            "pending",
        }

        seasons_payload: list[dict[str, Any]] = []
        episodes_payload: list[dict[str, Any]] = []
        next_episode_id = None
        prev_episode_id = None

        target_series = series if series and series.kind == "series" else None
        if target_series:
            seasons = session.exec(
                select(Item)
                .where(
                    Item.parent_id == target_series.id,
                    Item.kind == "season",
                    Item.deleted_at == None,  # noqa: E711
                )
                .order_by(Item.season_no)
            ).all()
            all_episodes: list[Item] = []
            for season in seasons:
                episodes = session.exec(
                    select(Item)
                    .where(Item.parent_id == season.id, Item.kind == "episode")
                    .order_by(Item.episode_no)
                ).all()
                episodes = [e for e in episodes if e.id in ready]
                all_episodes.extend(episodes)
                ep_progress = _progress_map(session, [e.id for e in episodes], user.id)
                ep_payloads = [
                    episode_summary(e, progress=ep_progress.get(e.id))
                    for e in episodes
                ]
                watched = sum(1 for e in episodes if ep_progress.get(e.id) and ep_progress[e.id].finished)
                seasons_payload.append(
                    {
                        "id": season.id,
                        "season_no": season.season_no,
                        "title": season.title,
                        "poster": item_summary(season)["poster"],
                        "episode_count": len(episodes),
                        "watched_count": watched,
                        "episodes": ep_payloads,
                    }
                )
            if item.kind == "season":
                episodes_payload = next(
                    (
                        s["episodes"]
                        for s in seasons_payload
                        if s["id"] == item.id
                    ),
                    [],
                )
            if all_episodes:
                all_progress = _progress_map(session, [e.id for e in all_episodes], user.id)
                if item.kind == "episode":
                    # 剧集详情页的播放按钮必须播放「当前这一集」，
                    # 不能再用整部剧的「第一集未看」作为目标。
                    target = item
                elif item.kind == "season":
                    target = _choose_play_target(session, item, user.id)
                else:
                    target = _choose_play_target(session, target_series, user.id)
                try:
                    index = all_episodes.index(target)
                except ValueError:
                    index = -1
                if index >= 0:
                    next_episode_id = (
                        all_episodes[index + 1].id
                        if index + 1 < len(all_episodes)
                        else None
                    )
                    prev_episode_id = (
                        all_episodes[index - 1].id if index > 0 else None
                    )
                watched = sum(
                    1
                    for e in all_episodes
                    if all_progress.get(e.id) and all_progress[e.id].finished
                )
                detail["series_progress"] = {
                    "watched": watched,
                    "total": len(all_episodes),
                    "ratio": round(watched / len(all_episodes), 4)
                    if all_episodes
                    else 0,
                }
                detail["play_target_id"] = target.id
        elif item.kind == "episode" and parent:
            episodes = session.exec(
                select(Item)
                .where(Item.parent_id == parent.id, Item.kind == "episode")
                .order_by(Item.episode_no)
            ).all()
            episodes = [e for e in episodes if e.id in ready]
            try:
                index = [e.id for e in episodes].index(item.id)
            except ValueError:
                index = -1
            if index >= 0:
                next_episode_id = (
                    episodes[index + 1].id if index + 1 < len(episodes) else None
                )
                prev_episode_id = episodes[index - 1].id if index > 0 else None
            detail["play_target_id"] = item.id
        else:
            detail["play_target_id"] = item.id

        return {
            "item": detail,
            "library": library_info,
            "series": series_summary,
            "parent": parent_summary,
            "seasons": seasons_payload,
            "episodes": episodes_payload,
            "media_files": media_files,
            "progress": progress_payload(progress.get(item.id)),
            "next_episode_id": next_episode_id,
            "prev_episode_id": prev_episode_id,
            "needs_attention": needs_attention,
        }


# ---------------------------------------------------------------------------
# 手动修正
# ---------------------------------------------------------------------------


@router.post("/{item_id}/unlock")
def unlock_item(item_id: int, engine=Depends(get_engine)):
    """恢复自动刮削：清空锁定字段，随后由前端触发一次刷新。"""
    with Session(engine) as session:
        item = _get_item(session, item_id)
        target = item
        guard = 0
        while target.kind not in {"movie", "series", "video"} and target.parent_id:
            target = session.get(Item, target.parent_id) or target
            guard += 1
            if guard > 6:
                break
        target.locked_fields = None
        target.updated_at = utcnow()
        session.add(target)
        session.commit()
        return {"ok": True, "item_id": target.id, "locked_fields": []}


@router.get("/{item_id}/match-candidates")
async def match_candidates(
    item_id: int,
    q: str | None = Query(None),
    provider: str | None = Query(None),
    _admin: CurrentUser = Depends(require_admin),
    engine=Depends(get_engine),
    settings: SettingsService = Depends(get_settings),
    images: ImageService = Depends(get_images),
):
    service = ScrapeService(engine, settings, images)
    try:
        candidates = await service.candidates(item_id, q, provider)
    finally:
        await service.close()
    return {"candidates": candidates}


@router.post("/{item_id}/match")
async def manual_match(
    item_id: int,
    body: MatchBody,
    _admin: CurrentUser = Depends(require_admin),
    engine=Depends(get_engine),
    settings: SettingsService = Depends(get_settings),
    images: ImageService = Depends(get_images),
):
    service = ScrapeService(engine, settings, images)
    try:
        result = await service.bind(item_id, body.provider, body.provider_id)
    finally:
        await service.close()
    if result.get("status") == "failed":
        raise APIError(
            400,
            "MATCH_FAILED",
            result.get("message") or "绑定失败",
            {"reason": result.get("reason")},
        )
    return result


@router.post("/{item_id}/unmatch")
async def unmatch(
    item_id: int,
    _admin: CurrentUser = Depends(require_admin),
    engine=Depends(get_engine),
    settings: SettingsService = Depends(get_settings),
    images: ImageService = Depends(get_images),
):
    service = ScrapeService(engine, settings, images)
    try:
        result = await service.unmatch(item_id)
    finally:
        await service.close()
    return result


@router.post("/{item_id}/refresh")
async def refresh_item(
    item_id: int,
    _admin: CurrentUser = Depends(require_admin),
    engine=Depends(get_engine),
    tasks: TaskManager = Depends(get_tasks),
):
    with Session(engine) as session:
        _get_item(session, item_id)
    return {"task_id": tasks.start_refresh_item(item_id), "status": "running"}


# ---------------------------------------------------------------------------
# 字段编辑 / 海报
# ---------------------------------------------------------------------------


@router.patch("/{item_id}")
def patch_item(
    item_id: int,
    body: ItemPatch,
    _admin: CurrentUser = Depends(require_admin),
    engine=Depends(get_engine),
):
    allowed = {
        "title",
        "original_title",
        "year",
        "overview",
        "tagline",
        "certification",
        "collection",
        "sort_title",
    }
    with Session(engine) as session:
        item = _get_item(session, item_id)
        fields = body.model_fields_set & allowed
        if not fields:
            raise APIError(400, "NO_FIELDS", "没有可修改的字段")
        locked = parse_json(item.locked_fields, [])
        if not isinstance(locked, list):
            locked = []
        for field in fields:
            value = getattr(body, field)
            if field == "collection":
                item.collection = (
                    json.dumps(value, ensure_ascii=False) if value else None
                )
            elif field == "title":
                if not value or not str(value).strip():
                    raise APIError(400, "INVALID_TITLE", "标题不能为空")
                item.title = str(value).strip()
                item.sort_title = normalize_title(item.title)
            elif field == "sort_title":
                item.sort_title = normalize_title(str(value or item.title))
            else:
                setattr(item, field, value)
            if field not in locked:
                locked.append(field)
        item.locked_fields = json.dumps(locked, ensure_ascii=False)
        item.updated_at = utcnow()
        session.add(item)
        session.commit()
        payload = item_summary(item)
        payload["locked_fields"] = locked
    return payload


@router.post("/{item_id}/poster")
async def upload_poster(
    item_id: int,
    file: UploadFile = File(...),
    kind: str = Form("poster"),
    engine=Depends(get_engine),
    images: ImageService = Depends(get_images),
):
    if kind not in {"poster", "backdrop", "logo"}:
        raise APIError(400, "INVALID_KIND", "kind 只能是 poster / backdrop / logo")
    data = await file.read()
    if not data:
        raise APIError(400, "EMPTY_FILE", "文件为空")
    if len(data) > 12 * 1024 * 1024:
        raise APIError(400, "FILE_TOO_LARGE", "图片不能超过 12MB")
    sha = hashlib.sha1(data).hexdigest()
    if not images.save_variants(sha, kind, data):
        raise APIError(400, "INVALID_IMAGE", "无法识别该图片格式")
    field = {"poster": "poster_path", "backdrop": "backdrop_path", "logo": "logo_path"}[kind]
    with Session(engine) as session:
        item = _get_item(session, item_id)
        setattr(item, field, sha)
        locked = parse_json(item.locked_fields, [])
        if not isinstance(locked, list):
            locked = []
        if field not in locked:
            locked.append(field)
        item.locked_fields = json.dumps(locked, ensure_ascii=False)
        if kind == "backdrop":
            color = await images.color_for(None, sha)
            if color:
                item.color_primary = color
        item.updated_at = utcnow()
        session.add(item)
        session.commit()
        size = {"poster": 500, "backdrop": 1280, "logo": 400}[kind]
        url = f"/img/{sha}_{size}.webp"
    return {"ok": True, "sha": sha, "url": url}


# ---------------------------------------------------------------------------
# 播放进度 / 已看
# ---------------------------------------------------------------------------


@router.post("/{item_id}/progress")
def report_progress(
    item_id: int,
    body: ProgressBody,
    request: Request,
    engine=Depends(get_engine),
):
    """v0.9: 上报播放进度，支持 Cookie 或 play_token 鉴权，按 user_id 隔离。"""
    # 网页用 Cookie；伴侣 App 内置播放器用 Bearer play_token（§12.7）
    current_user = authorize_item_access(request, item_id)
    if not current_user:
        raise APIError(401, "UNAUTHORIZED", "请先登录")

    with Session(engine) as session:
        item = _get_item(session, item_id)
        if item.kind not in {"movie", "episode", "video"}:
            raise APIError(
                400, "PROGRESS_ITEM_INVALID", "进度只能写入电影 / 剧集 / 视频"
            )

        # 检查用户是否有权访问该条目所属的库
        accessible_ids = get_accessible_library_ids(current_user, engine)
        if accessible_ids is not None and item.library_id not in accessible_ids:
            raise APIError(403, "FORBIDDEN", "无权访问该条目")

        row = session.exec(
            select(PlayProgress).where(
                PlayProgress.user_id == current_user.id,
                PlayProgress.item_id == item_id
            )
        ).first()
        if (
            body.client_key
            and row is not None
            and row.last_client_key == body.client_key
        ):
            return {
                "position_ms": row.position_ms,
                "duration_ms": row.duration_ms,
                "finished": bool(row.finished),
                "updated_at": row.updated_at,
                "duplicate": True,
            }
        duration = body.duration_ms if body.duration_ms and body.duration_ms > 0 else None
        position = max(0, int(body.position_ms or 0))
        if duration:
            position = min(position, duration)
        finished = bool(body.finished)
        if duration and position / duration > 0.9:
            finished = True
        if finished:
            position = 0
        if row is None:
            row = PlayProgress(
                user_id=current_user.id,
                item_id=item_id,
                position_ms=position,
                duration_ms=duration,
                finished=finished,
                updated_at=utcnow(),
                last_client_key=body.client_key,
            )
        else:
            if (
                not finished
                and not row.finished
                and row.position_ms - position > 5000
            ):
                # 防御：不允许非完成状态下进度大幅倒退
                return {
                    "position_ms": row.position_ms,
                    "duration_ms": row.duration_ms,
                    "finished": bool(row.finished),
                    "updated_at": row.updated_at,
                    "ignored": True,
                }
            row.position_ms = position
            row.duration_ms = duration or row.duration_ms
            row.finished = finished
            row.dismissed = False
            row.last_client_key = body.client_key
            row.updated_at = utcnow()
        session.add(row)
        session.commit()
        return {
            "position_ms": row.position_ms,
            "duration_ms": row.duration_ms,
            "finished": bool(row.finished),
            "updated_at": row.updated_at,
        }


@router.post("/{item_id}/watched")
def mark_watched(
    item_id: int,
    body: WatchedBody,
    user: CurrentUser = Depends(get_current_user),
    engine=Depends(get_engine),
):
    """v0.9: 标记已看/未看，按 user_id 隔离。"""
    with Session(engine) as session:
        item = _get_item(session, item_id)

        # 检查用户是否有权访问该条目所属的库
        accessible_ids = get_accessible_library_ids(user, engine)
        if accessible_ids is not None and item.library_id not in accessible_ids:
            raise APIError(403, "FORBIDDEN", "无权访问该条目")

        if item.kind == "series":
            sequence = _episode_sequence(session, item)
        elif item.kind == "season":
            sequence = session.exec(
                select(Item).where(
                    Item.parent_id == item.id, Item.kind == "episode"
                )
            ).all()
        else:
            sequence = [item]
        if not sequence:
            raise APIError(400, "NO_EPISODE", "该条目下没有可标记的内容")
        for entry in sequence:
            row = session.exec(
                select(PlayProgress).where(
                    PlayProgress.user_id == user.id,
                    PlayProgress.item_id == entry.id
                )
            ).first()
            if row is None:
                row = PlayProgress(
                    user_id=user.id,
                    item_id=entry.id,
                    updated_at=utcnow()
                )
            row.position_ms = 0
            row.finished = bool(body.finished)
            row.updated_at = utcnow()
            if row.duration_ms is None:
                row.duration_ms = None
            session.add(row)
        session.commit()
    return {"ok": True, "count": len(sequence), "finished": bool(body.finished)}


# ---------------------------------------------------------------------------
# 合并重复条目（P2）
# ---------------------------------------------------------------------------


@router.post("/{item_id}/merge")
def merge_item(
    item_id: int,
    body: MergeBody,
    _admin: CurrentUser = Depends(require_admin),
    engine=Depends(get_engine),
):
    with Session(engine) as session:
        target = _get_item(session, item_id)
        source = _get_item(session, body.source_id)
        if target.kind != source.kind:
            raise APIError(400, "KIND_MISMATCH", "只能合并同类型条目")
        if target.kind not in {"movie", "video"}:
            raise APIError(400, "MERGE_UNSUPPORTED", "当前仅支持电影 / 视频合并")
        for media in session.exec(
            select(MediaFile).where(MediaFile.item_id == source.id)
        ).all():
            media.item_id = target.id
            session.add(media)
        for row in session.exec(
            select(PlayProgress).where(PlayProgress.item_id == source.id)
        ).all():
            session.delete(row)
        session.delete(source)
        target.updated_at = utcnow()
        session.add(target)
        session.commit()
    return {"ok": True, "target_id": item_id, "merged_from": body.source_id}


@router.delete("/{item_id}/continue")
@router.post("/{item_id}/dismiss-continue")
def dismiss_continue(
    item_id: int,
    user: CurrentUser = Depends(get_current_user),
    engine=Depends(get_engine),
):
    """v0.9: 从「继续观看」移除该条目（保留其播放进度与已看记录），按 user_id 隔离。"""
    with Session(engine) as session:
        item = _get_item(session, item_id)

        # 检查用户是否有权访问该条目所属的库
        accessible_ids = get_accessible_library_ids(user, engine)
        if accessible_ids is not None and item.library_id not in accessible_ids:
            raise APIError(403, "FORBIDDEN", "无权访问该条目")

        if item.kind == "series":
            sequence = _episode_sequence(session, item)
            seq_ids = [ep.id for ep in sequence]
            if seq_ids:
                rows = session.exec(
                    select(PlayProgress).where(
                        PlayProgress.user_id == user.id,
                        PlayProgress.item_id.in_(seq_ids)
                    )
                ).all()
                for row in rows:
                    row.dismissed = True
                    session.add(row)
        else:
            row = session.exec(
                select(PlayProgress).where(
                    PlayProgress.user_id == user.id,
                    PlayProgress.item_id == item_id
                )
            ).first()
            if row is not None:
                row.dismissed = True
                session.add(row)
        session.commit()
    return {"ok": True, "item_id": item_id}

