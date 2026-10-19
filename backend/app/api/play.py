"""播放分发 API（§12）。

v0.8：默认路径为伴侣 App 内置 Media3；服务端只负责下发 URL / 请求头 / play_token。
进度回传支持 Cookie 与 `Authorization: Bearer <play_token>`（见 §12.7）。
"""

from __future__ import annotations

import mimetypes
from pathlib import Path

from fastapi import APIRouter, Depends, Request
from fastapi.responses import FileResponse
from sqlmodel import Session, select

from ..deps import authorize_item_access, get_engine, get_settings
from ..errors import APIError
from ..models import Item, Library, MediaFile, PlayProgress
from ..players import (
    ClipboardAdapter,
    MpvIpcAdapter,
    PlayContext,
    WebIntentAdapter,
    clean_headers,
    headers_hint,
    mask_url,
    normalize_mode,
    parse_headers,
)
from ..schemas import PlayBody
from ..serializers import episode_code, series_of
from .items import _choose_play_target, _episode_sequence

router = APIRouter(tags=["play"])

SUBTITLE_EXTENSIONS = {".srt", ".ass", ".ssa", ".vtt"}
SUBTITLE_MIME = {
    ".srt": "application/x-subrip",
    ".ass": "text/x-ssa",
    ".ssa": "text/x-ssa",
    ".vtt": "text/vtt",
}


# ---------------------------------------------------------------------------
# 请求头 / 字幕
# ---------------------------------------------------------------------------


def resolve_headers(library: Library | None, settings) -> dict[str, str]:
    headers = parse_headers(library.play_headers if library else None)
    if headers:
        return headers
    return clean_headers(settings.player().get("play_headers") or {})


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
    session: Session, target: Item, series: Item | None
) -> tuple[int | None, str | None, str | None]:
    """下一集 → 跳过已看，避免连播到看过的一集（§12.10）。"""
    if not series or target.kind != "episode":
        return None, None, None
    sequence = _episode_sequence(session, series)
    ids = [episode.id for episode in sequence]
    if target.id not in ids:
        return None, None, None
    progress_rows = session.exec(
        select(PlayProgress).where(PlayProgress.item_id.in_(ids))
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


def _mpv_available(settings, engine, context: PlayContext) -> bool:
    try:
        return MpvIpcAdapter(settings, engine).available(context)
    except Exception:  # pragma: no cover - 环境探测失败按不可用处理
        return False


def resolve_mode(requested: str | None, context: PlayContext, settings, engine) -> str:
    mode = normalize_mode(requested, settings)
    if mode == "auto":
        if context.is_companion:
            return "builtin"
        if context.is_android:
            return "browser_intent"
        return "desktop_mpv" if _mpv_available(settings, engine, context) else "copy"
    if mode == "builtin" and not context.is_companion:
        # 浏览器里没有原生播放器：Android 走 intent://，其余复制链接
        return "browser_intent" if context.is_android else "copy"
    if mode == "external_mpv" and not context.is_companion:
        return "browser_intent" if context.is_android else "copy"
    if mode == "desktop_mpv" and not _mpv_available(settings, engine, context):
        return "copy"
    return mode


def _pick_media(session: Session, item_id: int, media_file_id: int | None) -> MediaFile:
    row = None
    if media_file_id:
        row = session.get(MediaFile, media_file_id)
        if row is None or row.item_id != item_id or row.invalid:
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
    engine=Depends(get_engine),
    settings=Depends(get_settings),
):
    body = body or PlayBody()
    with Session(engine) as session:
        item = session.get(Item, item_id)
        if item is None or item.deleted_at:
            raise APIError(404, "ITEM_NOT_FOUND", "条目不存在")
        target = _choose_play_target(session, item)
        media = _pick_media(session, target.id, body.media_file_id)
        progress = session.exec(
            select(PlayProgress).where(PlayProgress.item_id == target.id)
        ).first()
        resume_ms = 0
        if progress and not progress.finished:
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
            session, target, series_obj
        )
        # 播放器「选集」：同一部剧的全部剧集（跨季按季/集排序）。
        playlist: list[dict] = []
        current_index = -1
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

    token, expires_at = request.app.state.app_state.auth.create_play_token(target_id)

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
    mode = resolve_mode(body.mode, context, settings, engine)

    subtitle_payload = [
        {
            "label": entry["label"],
            "lang": entry["lang"],
            "filename": entry["filename"],
            "format": Path(entry["filename"]).suffix.lstrip(".").lower(),
            "mime": SUBTITLE_MIME.get(
                Path(entry["filename"]).suffix.lower(), "text/plain"
            ),
            "url": f"/api/items/{target_id}/subtitles/{index}?pt={token}",
        }
        for index, entry in enumerate(subtitles)
    ]

    result: dict = {
        "mode": mode,
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
        "progress_interval_ms": int(settings.player().get("progress_interval_ms") or 5000),
        "fallback_on_error": bool(settings.player().get("fallback_on_error", True)),
        "mpv_package": str(settings.player().get("mpv_package") or "is.xyz.mpv"),
        "subtitles": subtitle_payload,
        "media_file_id": media_id,
        "progress_updated_at": progress_updated_at,
        "next_item_id": next_episode_id,
        "next_title": next_title,
        "next_episode_code": next_code,
        "series_title": series_obj.title if series_obj else None,
        "playlist": playlist,
        "current_index": current_index,
    }

    # 非原生路径：让服务端适配器生成 intent / spawn / 复制提示
    if mode == "browser_intent":
        adapter = WebIntentAdapter()
        result.update(
            await adapter.build(
                item=target,
                media=media,
                title=play_title,
                resume_ms=resume_ms,
                context=context,
            )
        )
        result["mode"] = "browser_intent"
        result["play_url"] = play_url
        result["headers"] = headers
        result["play_token"] = token
        result["next_item_id"] = next_episode_id
        result["subtitles"] = subtitle_payload
    elif mode == "copy":
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
    elif mode == "desktop_mpv":
        adapter = MpvIpcAdapter(settings, engine)
        built = await adapter.build(
            item=target,
            media=media,
            title=play_title,
            resume_ms=resume_ms,
            context=context,
        )
        result.update(built)
        result["mode"] = built.get("mode") or "desktop_mpv"
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
    engine=Depends(get_engine),
):
    """外挂字幕下载：Cookie 或 `?pt=play_token`（Media3 不便带自定义头）。"""
    authorize_item_access(request, item_id)
    with Session(engine) as session:
        item = session.get(Item, item_id)
        if item is None or item.deleted_at:
            raise APIError(404, "ITEM_NOT_FOUND", "条目不存在")
        target = _choose_play_target(session, item)
        media = _pick_media(session, target.id, None)
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
