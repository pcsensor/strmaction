"""播放分发 API（§12）。

v0.8：默认路径为伴侣 App 内置 Media3；服务端只负责下发 URL / 请求头 / play_token。
进度回传支持 Cookie 与 `Authorization: Bearer <play_token>`（见 §12.7）。
v0.9：支持多用户权限检查，play_token 绑定 user_id。
"""

from __future__ import annotations

import mimetypes
from pathlib import Path

from fastapi import APIRouter, Depends, Request
from fastapi.responses import FileResponse
from sqlmodel import Session, select

from ..deps import authorize_item_access, get_engine, get_settings, get_current_user, get_accessible_library_ids
from ..errors import APIError
from ..models import Item, Library, MediaFile, PlayProgress
from ..preferences import effective_player, get_preference
from ..schemas import CurrentUser
from ..players import (
    ClipboardAdapter,
    PlayContext,
    clean_headers,
    headers_hint,
    mask_url,
    normalize_mode,
    parse_headers,
)
from ..players.cache import normalize_cache_limit
from ..schemas import PlayBody
from ..serializers import episode_code, series_of
from ..text import natural_sort_key
from .items import _choose_play_target, _episode_sequence

router = APIRouter(tags=["play"])

SUBTITLE_EXTENSIONS = {".srt", ".ass", ".ssa", ".vtt"}
SUBTITLE_MIME = {
    ".srt": "application/x-subrip",
    ".ass": "text/x-ssa",
    ".ssa": "text/x-ssa",
    ".vtt": "text/vtt",
}


def cache_limit_mb(player: dict | None) -> int:
    """播放缓存上限（MB）。0 表示最小预读，由客户端按自身能力执行。"""
    return normalize_cache_limit((player or {}).get("cache_limit_mb"))


# ---------------------------------------------------------------------------
# 请求头 / 字幕
# ---------------------------------------------------------------------------


def resolve_headers(library: Library | None, settings) -> dict[str, str]:
    # 库级请求头覆盖全局默认值，但不要丢掉全局默认值里的其他字段
    headers = clean_headers(settings.player().get("play_headers") or {})
    if library is not None:
        headers.update(parse_headers(library.play_headers))
    return headers


def _subtitle_label(path: Path, media_stem: str) -> str:
    stem = path.stem
    if stem.lower().startswith(media_stem.lower()):
        stem = stem[len(media_stem) :]
    stem = stem.strip(" ._-[]()（）")
    return stem or path.suffix.lstrip(".").upper()


def list_subtitles(media: MediaFile) -> list[dict[str, str]]:
    """同目录下的外挂字幕（SmartStrm 复制过来的 .srt/.ass）。"""
    try:
        path = Path(media.abs_path)
        directory = path.parent
        if not directory.is_dir():
            return []
        media_stem = path.stem
        found: list[dict[str, str]] = []
        for entry in sorted(directory.iterdir(), key=lambda p: p.name.lower()):
            if not entry.is_file() or entry.suffix.lower() not in SUBTITLE_EXTENSIONS:
                continue
            if not entry.stem.lower().startswith(media_stem.lower()[:12]):
                continue
            found.append(
                {
                    "label": _subtitle_label(entry, media_stem),
                    "lang": _lang_from_label(entry.name),
                    "path": str(entry),
                    "filename": entry.name,
                }
            )
        return found
    except OSError:
        return []


def _lang_from_label(name: str) -> str:
    lowered = name.lower()
    mapping = [
        ("zh-hans", "zh"),
        ("zh-cn", "zh"),
        ("chs", "zh"),
        ("chi", "zh"),
        ("简体", "zh"),
        ("繁", "zh"),
        ("cht", "zh"),
        ("zh", "zh"),
        ("eng", "en"),
        ("en", "en"),
        ("jpn", "ja"),
        ("ja", "ja"),
    ]
    for needle, lang in mapping:
        if needle in lowered:
            return lang
    return "und"


def _next_unwatched(
    session: Session, target: Item, series: Item | None, user_id: int
) -> tuple[int | None, str | None, str | None]:
    """v0.9: 下一集 → 跳过已看，按 user_id 过滤。"""
    if not series or target.kind != "episode":
        return None, None, None
    sequence = _episode_sequence(session, series)
    if not sequence:
        return None, None, None
    playable = set(session.exec(select(MediaFile.item_id).where(
        MediaFile.item_id.in_([episode.id for episode in sequence]),
        MediaFile.invalid == False, MediaFile.missing == False,
    )).all())
    sequence = [episode for episode in sequence if episode.id in playable]
    ids = [episode.id for episode in sequence]
    if target.id not in ids:
        return None, None, None
    progress_rows = session.exec(
        select(PlayProgress).where(
            PlayProgress.user_id == user_id,
            PlayProgress.item_id.in_(ids)
        )
    ).all()
    watched = {row.item_id for row in progress_rows if row.finished}
    for episode in sequence[ids.index(target.id) + 1 :]:
        if episode.id in watched:
            continue
        return episode.id, episode.title, episode_code(episode)
    return None, None, None


# ---------------------------------------------------------------------------
# 播放模式解析
# ---------------------------------------------------------------------------


def resolve_mode_detail(
    requested: str | None,
    context: PlayContext,
    settings,
    engine,
    player: dict | None = None,
) -> tuple[str, str | None]:
    """返回 (实际 mode, 降级原因)；原因仅用于向用户解释，不影响播放。"""
    player = player or settings.player()
    mode = normalize_mode(requested, player)
    if mode == "builtin" and not context.is_companion:
        return "copy", "requires_companion"
    return mode, None


def resolve_mode(
    requested: str | None,
    context: PlayContext,
    settings,
    engine,
    player: dict | None = None,
) -> str:
    return resolve_mode_detail(
        requested,
        context,
        settings,
        engine,
        player=player,
    )[0]


def _pick_media(session: Session, item_id: int, media_file_id: int | None) -> MediaFile:
    row = None
    if media_file_id:
        row = session.get(MediaFile, media_file_id)
        if row is None or row.item_id != item_id or row.invalid or row.missing:
            raise APIError(404, "MEDIA_NOT_FOUND", "指定的媒体文件不存在")
    else:
        rows = session.exec(
            select(MediaFile)
            .where(
                MediaFile.item_id == item_id,
                MediaFile.invalid == False,  # noqa: E712
                MediaFile.missing == False,  # noqa: E712
            )
            .order_by(MediaFile.id)
        ).all()
        if not rows:
            raise APIError(404, "NO_MEDIA", "该条目没有可播放的 .strm 文件")
        # 优先非分段的第一段
        rows.sort(key=lambda m: (m.part or 0, m.id or 0))
        row = rows[0]
    if row is None or not row.url:
        raise APIError(404, "NO_MEDIA", "播放地址为空")
    return row


# ---------------------------------------------------------------------------
# 播放
# ---------------------------------------------------------------------------


@router.post("/play/{item_id}")
async def play(
    item_id: int,
    request: Request,
    body: PlayBody | None = None,
    user: CurrentUser = Depends(get_current_user),
    engine=Depends(get_engine),
    settings=Depends(get_settings),
):
    """v0.9: 播放分发，检查用户权限，play_token 绑定 user_id。"""
    body = body or PlayBody()
    with Session(engine) as session:
        item = session.get(Item, item_id)
        if item is None or item.deleted_at:
            raise APIError(404, "ITEM_NOT_FOUND", "条目不存在")

        # 检查用户是否有权访问该条目所属的库
        accessible_ids = get_accessible_library_ids(user, engine)
        if accessible_ids is not None and item.library_id not in accessible_ids:
            raise APIError(403, "FORBIDDEN", "无权访问该条目")

        target = _choose_play_target(session, item, user.id)
        media = _pick_media(session, target.id, body.media_file_id)
        progress = session.exec(
            select(PlayProgress).where(
                PlayProgress.user_id == user.id,
                PlayProgress.item_id == target.id
            )
        ).first()
        resume_ms = 0
        if progress and not progress.finished and not progress.dismissed:
            resume_ms = max(0, progress.position_ms)
        series = series_of(session, target)
        series_obj = series if series and series.kind == "series" else None
        series_id = series_obj.id if series_obj else None
        library = session.get(Library, target.library_id)
        play_title = target.title
        if series_obj and target.kind == "episode":
            code = episode_code(target)
            play_title = " ".join(
                x for x in [series_obj.title, code, target.title] if x
            ).strip()
        next_episode_id, next_title, next_code = _next_unwatched(
            session, target, series_obj, user.id
        )
        playlist: list[dict] = []
        current_index = -1
        parent_folder = session.get(Item, target.parent_id) if target.parent_id else None
        if series_obj is not None:
            sequence = _episode_sequence(session, series_obj)
            sequence_ids = [episode.id for episode in sequence]
            if sequence_ids:
                # 选集只列可播放的集数，避免选中缺失/损坏的文件
                playable_ids = {
                    row
                    for row in session.exec(
                        select(MediaFile.item_id).where(
                            MediaFile.item_id.in_(sequence_ids),
                            MediaFile.invalid == False,  # noqa: E712
                            MediaFile.missing == False,  # noqa: E712
                        )
                    ).all()
                    if row
                }
                sequence = [
                    episode
                    for episode in sequence
                    if episode.id in playable_ids or episode.id == target.id
                ]
                sequence_ids = [episode.id for episode in sequence]
                progress_rows = session.exec(
                    select(PlayProgress).where(
                        PlayProgress.user_id == user.id,
                        PlayProgress.item_id.in_(sequence_ids)
                    )
                ).all()
                watched_ids = {row.item_id for row in progress_rows if row.finished}
                for index, episode in enumerate(sequence):
                    playlist.append(
                        {
                            "id": episode.id,
                            "title": episode.title,
                            "season_no": episode.season_no,
                            "episode_no": episode.episode_no,
                            "code": episode_code(episode),
                            "watched": episode.id in watched_ids,
                            "current": episode.id == target.id,
                        }
                    )
                    if episode.id == target.id:
                        current_index = index
        elif target.kind == "video" and parent_folder is not None:
            sibling_videos = session.exec(
                select(Item).where(
                    Item.parent_id == parent_folder.id,
                    Item.kind == "video",
                    Item.deleted_at == None,  # noqa: E711
                )
            ).all()
            sibling_ids = [v.id for v in sibling_videos if v.id]
            if sibling_ids:
                playable_ids = {
                    row
                    for row in session.exec(
                        select(MediaFile.item_id).where(
                            MediaFile.item_id.in_(sibling_ids),
                            MediaFile.invalid == False,  # noqa: E712
                            MediaFile.missing == False,  # noqa: E712
                        )
                    ).all()
                    if row
                }
                sibling_videos = [
                    v for v in sibling_videos
                    if v.id in playable_ids or v.id == target.id
                ]
                sibling_videos.sort(key=lambda x: natural_sort_key(x.title))
                progress_rows = session.exec(
                    select(PlayProgress).where(
                        PlayProgress.user_id == user.id,
                        PlayProgress.item_id.in_([v.id for v in sibling_videos if v.id])
                    )
                ).all()
                watched_ids = {row.item_id for row in progress_rows if row.finished}
                for index, video in enumerate(sibling_videos):
                    playlist.append(
                        {
                            "id": video.id,
                            "title": video.title,
                            "season_no": None,
                            "episode_no": video.episode_no,
                            "code": f"P{video.episode_no:02d}" if video.episode_no else None,
                            "watched": video.id in watched_ids,
                            "current": video.id == target.id,
                        }
                    )
                    if video.id == target.id:
                        current_index = index
                if current_index >= 0 and current_index + 1 < len(sibling_videos):
                    next_v = sibling_videos[current_index + 1]
                    next_episode_id = next_v.id
                    next_title = next_v.title
                    next_code = f"P{next_v.episode_no:02d}" if next_v.episode_no else None
        target_id = target.id
        target_kind = target.kind
        duration_ms = progress.duration_ms if progress else None
        if not duration_ms and target.runtime_min:
            duration_ms = int(target.runtime_min) * 60_000
        progress_updated_at = progress.updated_at if progress else None
        media_id = media.id
        play_url = media.url
        library_name = library.name if library else None
        headers = resolve_headers(library, settings)
        subtitles = list_subtitles(media)
        media_path = media.abs_path

    token, expires_at = request.app.state.app_state.auth.create_play_token(user.id, target_id)

    user_agent = request.headers.get("user-agent", "")
    is_companion = (
        "StrmActionCompanion" in user_agent
        or request.headers.get("x-strmaction-companion") is not None
    )
    context = PlayContext(
        user_agent=user_agent,
        is_android="Android" in user_agent,
        is_companion=is_companion,
        client_ip=request.client.host if request.client else "",
        headers=headers,
    )
    # 个人播放偏好优先于全局默认；请求体里的显式 mode 优先级最高。
    player = effective_player(settings, get_preference(engine, user.id))
    requested_mode = normalize_mode(body.mode, player)
    mode, downgrade_reason = resolve_mode_detail(
        body.mode,
        context,
        settings,
        engine,
        player=player,
    )

    subtitle_payload = [
        {
            "label": entry["label"],
            "lang": entry["lang"],
            "filename": entry["filename"],
            "format": Path(entry["filename"]).suffix.lstrip(".").lower(),
            "mime": SUBTITLE_MIME.get(
                Path(entry["filename"]).suffix.lower(), "text/plain"
            ),
            "url": f"/api/items/{target_id}/subtitles/{index}?pt={token}&media_file_id={media_id}",
        }
        for index, entry in enumerate(subtitles)
    ]

    result: dict = {
        "mode": mode,
        "requested_mode": requested_mode,
        "downgraded": downgrade_reason is not None,
        "downgrade_reason": downgrade_reason,
        "target": mode,
        "action": None,
        "fallback_url": play_url,
        "tip": "",
        "play_url": play_url,
        "resume_ms": resume_ms,
        "duration_ms": duration_ms,
        "item_id": target_id,
        "kind": target_kind,
        "series_id": series_id,
        "library": library_name,
        "title": play_title,
        "headers": headers,
        "headers_hint": headers_hint(headers),
        "play_token": token,
        "play_token_expires_at": expires_at,
        "progress_interval_ms": int(player.get("progress_interval_ms") or 5000),
        "cache_limit_mb": cache_limit_mb(player),
        "buffer_limit_mb": player.get("buffer_limit_mb"),
        "disk_cache_limit_mb": player.get("disk_cache_limit_mb"),
        "subtitles": subtitle_payload,
        "media_file_id": media_id,
        "progress_updated_at": progress_updated_at,
        "next_item_id": next_episode_id,
        "next_title": next_title,
        "next_episode_code": next_code,
        "series_title": series_obj.title if series_obj else (parent_folder.title if parent_folder else None),
        "playlist": playlist,
        "current_index": current_index,
        "previous_item_id": playlist[current_index - 1]["id"] if current_index > 0 else None,
        "manual_next_item_id": playlist[current_index + 1]["id"] if 0 <= current_index < len(playlist) - 1 else None,
    }

    if mode == "copy":
        adapter = ClipboardAdapter()
        result.update(
            await adapter.build(
                item=target,
                media=media,
                title=play_title,
                resume_ms=resume_ms,
                context=context,
            )
        )
        result["mode"] = "copy"
        result["play_url"] = play_url
        result["headers"] = headers
        result["play_token"] = token
        result["next_item_id"] = next_episode_id
        result["subtitles"] = subtitle_payload

    print(
        f"[play] item={target_id} mode={result.get('mode')} "
        f"url={mask_url(play_url)} media={Path(media_path).name}"
    )
    return result


@router.get("/items/{item_id}/subtitles/{index}")
def download_subtitle(
    item_id: int,
    index: int,
    request: Request,
    media_file_id: int | None = None,
    engine=Depends(get_engine),
):
    """v0.9: 外挂字幕下载：Cookie 或 `?pt=play_token`，支持多用户权限检查。"""
    current_user = authorize_item_access(request, item_id)
    if not current_user:
        raise APIError(401, "UNAUTHORIZED", "请先登录")

    with Session(engine) as session:
        item = session.get(Item, item_id)
        if item is None or item.deleted_at:
            raise APIError(404, "ITEM_NOT_FOUND", "条目不存在")

        # 检查用户是否有权访问该条目所属的库
        accessible_ids = get_accessible_library_ids(current_user, engine)
        if accessible_ids is not None and item.library_id not in accessible_ids:
            raise APIError(403, "FORBIDDEN", "无权访问该条目")

        target = _choose_play_target(session, item, current_user.id)
        media = _pick_media(session, target.id, media_file_id)
        subtitles = list_subtitles(media)
        if index < 0 or index >= len(subtitles):
            raise APIError(404, "SUBTITLE_NOT_FOUND", "字幕不存在")
        entry = subtitles[index]
        path = Path(entry["path"])

    if not path.is_file():
        raise APIError(404, "SUBTITLE_NOT_FOUND", "字幕文件已丢失")
    suffix = path.suffix.lower()
    media_type = SUBTITLE_MIME.get(suffix) or mimetypes.guess_type(path.name)[0] or "text/plain"
    return FileResponse(
        path,
        media_type=media_type,
        filename=path.name,
        headers={"Cache-Control": "no-store"},
    )
