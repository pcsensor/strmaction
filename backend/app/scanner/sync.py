"""扫描入库：增量、移动归并、缺失标记、条目结构维护。"""

from __future__ import annotations

import json
import os
import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from sqlalchemy import delete
from sqlmodel import Session, select

from ..config_store import SettingsService
from ..models import (
    ImageTask,
    Item,
    Library,
    MediaFile,
    PlayProgress,
    PlaySession,
    PlayToken,
    Setting,
    utcnow,
)
from ..parser import PARSER_VERSION, Parsed, parse_path
from ..serializers import ready_item_ids
from ..text import normalize_title
from .walker import WalkEntry, iter_strm_files, read_strm

ProgressCB = Callable[[dict[str, Any]], None]


def _loads(value: str | None) -> dict:
    if not value:
        return {}
    try:
        data = json.loads(value)
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, TypeError):
        return {}


def _stable_key(item: Item) -> str:
    raw = _loads(item.parse_payload)
    return raw.get("group_title") or raw.get("parse_title") or item.title or ""


def _better_title(item: Item) -> bool:
    """只有未匹配/失败的条目才允许用解析结果覆盖标题。"""
    return item.match_state in {"pending", "failed"} and not item.locked_fields


@dataclass
class ScanStats:
    scanned: int = 0
    skipped: int = 0
    parsed: int = 0
    added_items: int = 0
    added_files: int = 0
    updated_files: int = 0
    moved_files: int = 0
    missing: int = 0
    restored: int = 0
    deleted_items: int = 0
    invalid: int = 0
    invalid_examples: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "scanned": self.scanned,
            "skipped": self.skipped,
            "parsed": self.parsed,
            "added_items": self.added_items,
            "added_files": self.added_files,
            "updated_files": self.updated_files,
            "moved_files": self.moved_files,
            "missing": self.missing,
            "restored": self.restored,
            "deleted_items": self.deleted_items,
            "invalid": self.invalid,
            "invalid_examples": self.invalid_examples[:20],
        }


class ItemIndex:
    """扫描期间的条目索引，避免逐文件全表查询。"""

    def __init__(self, items: list[Item]):
        self.by_id: dict[int, Item] = {i.id: i for i in items if i.id is not None}
        self.movies: dict[str, list[Item]] = defaultdict(list)
        self.series: dict[str, list[Item]] = defaultdict(list)
        self.folders: dict[tuple[int | None, str], Item] = {}
        self.seasons: dict[tuple[int, int], Item] = {}
        self.seasons_by_title: dict[tuple[int, str], Item] = {}
        self.episodes: dict[tuple[int, int], Item] = {}
        self.videos: dict[tuple[int | None, str], Item] = {}
        self.tree_videos: dict[tuple[int | None, str], Item] = {}
        self.children: dict[int | None, list[Item]] = defaultdict(list)
        for item in items:
            self._add(item)

    def _add(self, item: Item) -> None:
        if item.id is not None:
            self.by_id[item.id] = item
        self.children[item.parent_id].append(item)
        key = normalize_title(_stable_key(item))
        if item.kind == "movie":
            self.movies[key].append(item)
        elif item.kind == "series":
            self.series[key].append(item)
        elif item.kind == "folder":
            self.folders[(item.parent_id, normalize_title(item.title))] = item
        elif item.kind == "season" and item.parent_id is not None:
            self.seasons[(item.parent_id, item.season_no or 0)] = item
            self.seasons_by_title[(item.parent_id, normalize_title(item.title))] = item
        elif item.kind == "episode" and item.parent_id is not None:
            self.episodes[(item.parent_id, item.episode_no or 0)] = item
        elif item.kind == "video":
            self.videos[(item.parent_id, normalize_title(item.title))] = item
            self.tree_videos[(item.parent_id, item.title.strip().lower())] = item

    def find_movie(self, key: str, year: int | None) -> Item | None:
        candidates = self.movies.get(normalize_title(key), [])
        for item in candidates:
            if item.year == year:
                return item
        for item in candidates:
            if year is None or item.year is None or abs(item.year - year) <= 1:
                return item
        return None

    def find_series(self, key: str, year: int | None) -> Item | None:
        candidates = self.series.get(normalize_title(key), [])
        for item in candidates:
            if item.year == year:
                return item
        for item in candidates:
            if year is None or item.year is None or abs(item.year - year) <= 1:
                return item
        return None


class ScannerService:
    def __init__(self, session_factory, settings: SettingsService):
        if callable(session_factory):
            self.session_factory = session_factory
        else:
            engine = session_factory
            self.session_factory = lambda: Session(engine)
        self.settings = settings

    # -- 公共入口 ---------------------------------------------------------
    def scan_library(
        self, library_id: int, progress_cb: ProgressCB | None = None
    ) -> dict[str, Any]:
        with self.session_factory() as session:
            library = session.get(Library, library_id)
            if library is None:
                return {"error": "library_not_found"}
            stats = self._scan(session, library, progress_cb)
            session.commit()
            return stats

    # -- 主流程 -----------------------------------------------------------
    def _scan(
        self, session: Session, library: Library, progress_cb: ProgressCB | None
    ) -> dict[str, Any]:
        stats = ScanStats()
        config = self.settings.scanner()
        season_type = self.settings.tvdb_season_type(library)
        entries: list[WalkEntry] = iter_strm_files(
            library.root_path,
            ignore=config.get("ignore"),
            max_depth=int(config.get("max_depth") or 6),
            follow_symlinks=bool(config.get("follow_symlinks")),
        )
        stats.scanned = len(entries)

        existing_items = session.exec(
            select(Item).where(Item.library_id == library.id)
        ).all()
        index = ItemIndex([i for i in existing_items if not i.deleted_at])
        parser_current = self._parser_version_current(session, library)

        media_files = session.exec(
            select(MediaFile).where(MediaFile.library_id == library.id)
        ).all()
        by_path: dict[str, MediaFile] = {m.abs_path: m for m in media_files}
        by_url: dict[str, MediaFile] = {}
        for media in media_files:
            if media.url:
                by_url.setdefault(media.url, media)
        entry_paths = {e.abs_path for e in entries}

        seen: set[str] = set()
        course_sequence: dict[tuple[int, int], list[int]] = defaultdict(list)
        for media in media_files:
            if media.item_id is not None:
                item = index.by_id.get(media.item_id)
                if item and item.kind == "episode" and item.parent_id:
                    course_sequence[item.parent_id].append(item.episode_no or 0)

        for position, entry in enumerate(entries):
            if progress_cb and position and position % 100 == 0:
                # 回调可能写任务日志，必须先释放本事务的写锁
                session.commit()
                progress_cb({"phase": "walk", "done": position, "total": len(entries)})
            seen.add(entry.abs_path)
            old = by_path.get(entry.abs_path)
            try:
                if (
                    old
                    and old.mtime == entry.mtime
                    and old.size_bytes == entry.size
                    and parser_current
                ):
                    if old.missing:
                        old.missing = False
                        old.missing_count = 0
                        stats.restored += 1
                        self._restore_item_hierarchy(session, old.item_id)
                    stats.skipped += 1
                    continue

                content = read_strm(entry.abs_path)
                if not content.valid:
                    stats.invalid += 1
                    if len(stats.invalid_examples) < 20:
                        stats.invalid_examples.append(entry.rel_path)
                    if old:
                        old.invalid = True
                        old.missing = False
                        old.mtime = entry.mtime
                        old.size_bytes = entry.size
                    continue

                parsed = parse_path(
                    library.type,
                    entry.rel_path,
                    template=library.template,
                    season_type=season_type,
                    root_name=os.path.basename(library.root_path.rstrip("/\\")) or None,
                )
                stats.parsed += 1

                moved = False
                if old is None:
                    candidate = by_url.get(content.url)
                    if (
                        candidate is not None
                        and candidate.abs_path != entry.abs_path
                        and candidate.abs_path not in entry_paths
                    ):
                        by_url.pop(content.url, None)
                        old = candidate
                        moved = True
                        stats.moved_files += 1

                moved_item = None
                if moved and old is not None and old.item_id:
                    candidate_item = session.get(Item, old.item_id)
                    if candidate_item is not None and self._compatible_item(
                        candidate_item, parsed
                    ):
                        moved_item = candidate_item

                if moved_item is not None:
                    item = self._reuse_moved_item(moved_item, parsed)
                    session.add(item)
                else:
                    item = self._resolve_item(
                        session, library, index, parsed, entry, stats, course_sequence, existing_media=old
                    )
                old_abs = old.abs_path if old else None
                media, created = self._upsert_media(
                    session,
                    library,
                    item,
                    entry,
                    content.url,
                    parsed,
                    existing=old,
                )
                if created:
                    stats.added_files += 1
                else:
                    stats.updated_files += 1
                if old_abs and old_abs != entry.abs_path:
                    by_path.pop(old_abs, None)
                by_path[media.abs_path] = media
                by_url.setdefault(content.url, media)
                media.missing = False
                media.missing_count = 0
                media.invalid = False
                self._restore_item_hierarchy(session, media.item_id)
            except Exception as exc:  # pragma: no cover - 单文件失败不阻塞扫描
                stats.invalid_examples.append(f"{entry.rel_path} ({exc})")
                continue

        # 缺失标记
        for media in media_files:
            if media.abs_path in seen:
                continue
            if media.missing:
                media.missing_count = (media.missing_count or 0) + 1
            else:
                media.missing = True
                media.missing_count = (media.missing_count or 0) + 1
                stats.missing += 1
            if media.missing_count >= 3 and media.item_id:
                item = session.get(Item, media.item_id)
                if item and not item.deleted_at:
                    others = session.exec(
                        select(MediaFile).where(
                            MediaFile.item_id == item.id,
                            MediaFile.missing == False,  # noqa: E712
                            MediaFile.invalid == False,  # noqa: E712
                        )
                    ).all()
                    if not others:
                        item.deleted_at = utcnow()
                        item.updated_at = utcnow()
                        session.add(item)
                        stats.deleted_items += 1

        self._prune_orphans(session, library.id)
        # 纯剧集内容的「电影」库：把库类型纠正为 tv，避免 UI 继续显示「电影 / 0 部电影」。
        # 以清理后的实际条目为准，增量跳过时也能纠正。
        remaining_kinds = {
            row
            for row in session.exec(
                select(Item.kind).where(
                    Item.library_id == library.id,
                    Item.deleted_at == None,  # noqa: E711
                )
            ).all()
        }
        if library.type == "movie" and "episode" in remaining_kinds and "movie" not in remaining_kinds:
            library.type = "tv"
        self._mark_parser_version(session, library.id or 0)
        library.last_scan_at = utcnow()
        session.add(library)
        session.flush()

        result = stats.to_dict()
        ready_ids = ready_item_ids(session, library.id)
        result["items_total"] = len(ready_ids)
        result["files_total"] = len(
            session.exec(
                select(MediaFile).where(
                    MediaFile.library_id == library.id,
                    MediaFile.invalid == False,  # noqa: E712
                    MediaFile.missing == False,  # noqa: E712
                )
            ).all()
        )
        # 先提交，再触发可能写数据库的进度回调
        session.commit()
        if progress_cb:
            progress_cb({"phase": "done", "stats": result})
        return result

    def _restore_item_hierarchy(self, session: Session, item_id: int | None) -> None:
        """当媒体文件重新出现时，解除条目及其祖先节点的软删除状态。"""
        if not item_id:
            return
        item = session.get(Item, item_id)
        if not item:
            return
        if item.deleted_at:
            item.deleted_at = None
            item.updated_at = utcnow()
            session.add(item)
        parent_node = session.get(Item, item.parent_id) if item.parent_id else None
        while parent_node:
            if parent_node.deleted_at:
                parent_node.deleted_at = None
                parent_node.updated_at = utcnow()
                session.add(parent_node)
            parent_node = session.get(Item, parent_node.parent_id) if parent_node.parent_id else None

    # -- 条目解析到结构 ---------------------------------------------------
    def _compatible_item(self, item: Item, parsed: Parsed) -> bool:
        if parsed.kind == "movie":
            return item.kind == "movie"
        if parsed.kind == "series":
            return item.kind == "series"
        if parsed.kind == "episode":
            return (
                item.kind == "episode"
                and item.season_no == (parsed.season or 1)
                and item.episode_no == parsed.episode
            )
        if parsed.kind == "video":
            return item.kind in {"video", "episode"}
        return False

    def _reuse_moved_item(self, item: Item, parsed: Parsed) -> Item:
        """文件改名/移动但内容 URL 不变：沿用原条目，保住播放进度。"""
        payload = parsed.to_dict()
        if parsed.kind == "movie":
            payload["parse_title"] = parsed.title
        elif parsed.kind == "episode":
            payload["group_title"] = parsed.group_title or item.title
        item.parse_payload = json.dumps(payload, ensure_ascii=False)
        item.parse_confidence = parsed.confidence
        item.deleted_at = None
        if item.match_state != "manual" and not item.locked_fields:
            if parsed.kind == "movie" and parsed.title:
                item.title = parsed.title
                item.sort_title = normalize_title(item.title)
            if parsed.kind == "episode" and parsed.episode:
                item.title = f"第{parsed.episode}集"
                item.sort_title = normalize_title(item.title)
            if item.year is None and parsed.year:
                item.year = parsed.year
        item.updated_at = utcnow()
        return item

    def _resolve_item(
        self,
        session: Session,
        library: Library,
        index: ItemIndex,
        parsed: Parsed,
        entry: WalkEntry,
        stats: ScanStats,
        course_sequence: dict[int, list[int]],
        existing_media: MediaFile | None = None,
    ) -> Item:
        stype = library.type
        # 剧集结构优先于库类型：电影库/电视剧库里混入的剧集都要按
        # series → season → episode 入库，否则整季会被当成一部电影的多版本。
        if parsed.kind == "episode" and stype not in {"home", "course"}:
            return self._resolve_episode(session, library, index, parsed, stats)
        if stype in {"home", "course"}:
            return self._resolve_tree_item(session, library, index, parsed, stats, existing_media=existing_media)
        if stype == "movie" or (stype == "tv" and parsed.kind == "movie"):
            return self._resolve_movie(session, library, index, parsed, stats)
        if stype == "tv":
            return self._resolve_tv_orphan(session, library, index, parsed, stats)
        return self._resolve_movie(session, library, index, parsed, stats)

    def _new_item(
        self,
        session: Session,
        library: Library,
        index: ItemIndex,
        *,
        kind: str,
        title: str,
        parent_id: int | None = None,
        year: int | None = None,
        season_no: int | None = None,
        episode_no: int | None = None,
        match_state: str = "pending",
        parse_payload: dict | None = None,
    ) -> Item:
        item = Item(
            library_id=library.id or 0,
            parent_id=parent_id,
            kind=kind,
            title=title or "未命名",
            original_title=None,
            sort_title=normalize_title(title) or None,
            year=year,
            season_no=season_no,
            episode_no=episode_no,
            match_state=match_state,
            parse_payload=json.dumps(parse_payload or {}, ensure_ascii=False),
            created_at=utcnow(),
            updated_at=utcnow(),
        )
        session.add(item)
        session.flush()
        index._add(item)
        return item

    def _resolve_movie(
        self,
        session: Session,
        library: Library,
        index: ItemIndex,
        parsed: Parsed,
        stats: ScanStats,
    ) -> Item:
        key = parsed.title
        item = index.find_movie(key, parsed.year)
        raw = {
            "parse_title": parsed.title,
            "year": parsed.year,
            "confidence": parsed.confidence,
            "explicit_ids": parsed.explicit_ids,
            "parser": parsed.parser,
        }
        if item is None:
            item = self._new_item(
                session,
                library,
                index,
                kind="movie",
                title=parsed.title,
                year=parsed.year,
                match_state="failed" if parsed.confidence < 0.5 else "pending",
                parse_payload=raw,
            )
            item.parse_confidence = parsed.confidence
            session.add(item)
            stats.added_items += 1
        else:
            if _better_title(item):
                item.title = parsed.title or item.title
                item.sort_title = normalize_title(item.title)
            if item.year is None and parsed.year:
                item.year = parsed.year
            item.parse_payload = json.dumps(raw, ensure_ascii=False)
            item.parse_confidence = parsed.confidence
            item.updated_at = utcnow()
            session.add(item)
            bucket = index.movies.setdefault(normalize_title(item.title), [])
            if item not in bucket:
                bucket.append(item)
        return item

    def _resolve_episode(
        self,
        session: Session,
        library: Library,
        index: ItemIndex,
        parsed: Parsed,
        stats: ScanStats,
    ) -> Item:
        series_title = parsed.group_title or parsed.title or "其他"
        series = index.find_series(series_title, parsed.year)
        raw_series = {
            "group_title": series_title,
            "year": parsed.year,
            "confidence": parsed.confidence,
            "explicit_ids": parsed.explicit_ids,
            "parser": parsed.parser,
        }
        if series is None:
            series = self._new_item(
                session,
                library,
                index,
                kind="series",
                title=series_title,
                year=parsed.year,
                match_state="failed" if parsed.confidence < 0.5 else "pending",
                parse_payload=raw_series,
            )
            stats.added_items += 1
        else:
            if _better_title(series) and parsed.confidence >= 0.5:
                series.title = series_title or series.title
                series.sort_title = normalize_title(series.title)
            if series.year is None and parsed.year:
                series.year = parsed.year
            series.parse_payload = json.dumps(raw_series, ensure_ascii=False)
            series.updated_at = utcnow()
            session.add(series)
            bucket = index.series.setdefault(normalize_title(series.title), [])
            if series not in bucket:
                bucket.append(series)

        season_no = parsed.season or 1
        season = index.seasons.get((series.id, season_no))
        if season is None:
            season = self._new_item(
                session,
                library,
                index,
                kind="season",
                title=f"第{season_no}季",
                parent_id=series.id,
                season_no=season_no,
                match_state="pending",
                parse_payload={"season_no": season_no},
            )
            stats.added_items += 1
        episode_no = parsed.episode or 1
        episode = index.episodes.get((season.id, episode_no))
        if episode is None:
            episode = self._new_item(
                session,
                library,
                index,
                kind="episode",
                title=f"第{episode_no}集",
                parent_id=season.id,
                season_no=season_no,
                episode_no=episode_no,
                match_state="pending",
                parse_payload={
                    "episode_no": episode_no,
                    "season_no": season_no,
                    "group_title": series_title,
                    "year": parsed.year,
                },
            )
            stats.added_items += 1
        else:
            if _better_title(episode):
                episode.title = f"第{episode_no}集"
                episode.sort_title = normalize_title(episode.title)
            episode.updated_at = utcnow()
            session.add(episode)
        return episode

    def _resolve_home(
        self,
        session: Session,
        library: Library,
        index: ItemIndex,
        parsed: Parsed,
        stats: ScanStats,
    ) -> Item:
        parent: Item | None = None
        if parsed.group_title:
            norm = normalize_title(parsed.group_title)
            for candidate in index.series.get(norm, []):
                if candidate.parent_id is None:
                    parent = candidate
                    break
            if parent is None:
                parent = self._new_item(
                    session,
                    library,
                    index,
                    kind="series",
                    title=parsed.group_title,
                    match_state="skipped",
                    parse_payload={"group_title": parsed.group_title},
                )
                stats.added_items += 1
        norm_title = normalize_title(parsed.title)
        video = index.videos.get((parent.id if parent else None, norm_title))
        if video is None:
            video = self._new_item(
                session,
                library,
                index,
                kind="video",
                title=parsed.title,
                parent_id=parent.id if parent else None,
                match_state="skipped",
                parse_payload={"parse_title": parsed.title},
            )
            stats.added_items += 1
        else:
            if _better_title(video):
                video.title = parsed.title or video.title
                video.sort_title = normalize_title(video.title)
            video.updated_at = utcnow()
            session.add(video)
        return video

    def _resolve_tv_orphan(
        self,
        session: Session,
        library: Library,
        index: ItemIndex,
        parsed: Parsed,
        stats: ScanStats,
    ) -> Item:
        norm = normalize_title("其他")
        parent = None
        for candidate in index.series.get(norm, []):
            if candidate.parent_id is None:
                parent = candidate
                break
        if parent is None:
            parent = self._new_item(
                session,
                library,
                index,
                kind="series",
                title="其他",
                match_state="skipped",
                parse_payload={"group_title": "其他"},
            )
            stats.added_items += 1
        title = parsed.title or parsed.raw_name
        video = index.videos.get((parent.id, normalize_title(title)))
        if video is None:
            video = self._new_item(
                session,
                library,
                index,
                kind="video",
                title=title,
                parent_id=parent.id,
                match_state="skipped",
                parse_payload={"parse_title": title},
            )
            stats.added_items += 1
        return video

    def _resolve_tree_item(
        self,
        session: Session,
        library: Library,
        index: ItemIndex,
        parsed: Parsed,
        stats: ScanStats,
        existing_media: MediaFile | None = None,
    ) -> Item:
        """课程 / 家庭视频：按实际物理目录保留层级，支持任意多级层级。

        中间各层目录均为 Item(kind='folder')，最后一层直接包含的视频为 Item(kind='video')。
        """
        current_parent_id: int | None = None
        for depth, folder_name in enumerate(parsed.folder_parts):
            clean_name = folder_name.strip()
            norm_folder = normalize_title(clean_name)
            folder = index.folders.get((current_parent_id, norm_folder))
            if folder is None:
                match = re.match(
                    r"^\s*(?:\[(\d{1,4})\]|(\d{1,4}))\s*(?:--|-|–|—|[\s._\-])*\s*",
                    clean_name,
                )
                folder_no = (
                    int(match.group(1) or match.group(2))
                    if match
                    else (depth + 1)
                )
                folder = self._new_item(
                    session,
                    library,
                    index,
                    kind="folder",
                    title=clean_name,
                    parent_id=current_parent_id,
                    episode_no=folder_no,
                    match_state="skipped",
                    parse_payload={
                        "folder_path": parsed.folder_parts[: depth + 1]
                    },
                )
                stats.added_items += 1
                index.folders[(current_parent_id, norm_folder)] = folder
            current_parent_id = folder.id

        title = parsed.title or parsed.raw_name
        video_key = title.strip().lower()

        video: Item | None = None
        # 1. 如果此前已有 MediaFile 绑定到本目录下的某个有效视频，优先精准定位
        if existing_media and existing_media.item_id:
            cand = index.by_id.get(existing_media.item_id)
            if cand and cand.parent_id == current_parent_id and cand.kind == "video" and not getattr(cand, "_claimed", False):
                video = cand

        # 2. 否则按当前目录下精确文件名查找
        if video is None:
            cand = index.tree_videos.get((current_parent_id, video_key))
            if cand and not getattr(cand, "_claimed", False):
                video = cand

        if video is None:
            video = self._new_item(
                session,
                library,
                index,
                kind="video",
                title=title,
                parent_id=current_parent_id,
                episode_no=None,
                match_state="skipped",
                parse_payload={
                    "parse_title": title,
                    "folder_parts": parsed.folder_parts,
                },
            )
            stats.added_items += 1
            index.tree_videos[(current_parent_id, video_key)] = video
        else:
            changed = False
            if video.title != title:
                video.title = title
                video.sort_title = normalize_title(title)
                changed = True
            if video.episode_no is not None:
                video.episode_no = None
                changed = True
            if changed:
                video.updated_at = utcnow()
                session.add(video)
            index.tree_videos[(current_parent_id, video_key)] = video

        setattr(video, "_claimed", True)
        return video

    # -- 媒体文件 ---------------------------------------------------------
    def _upsert_media(
        self,
        session: Session,
        library: Library,
        item: Item,
        entry: WalkEntry,
        url: str,
        parsed: Parsed,
        existing: MediaFile | None = None,
    ) -> tuple[MediaFile, bool]:
        media = existing
        if media is None or media.abs_path != entry.abs_path:
            found = session.exec(
                select(MediaFile).where(MediaFile.abs_path == entry.abs_path)
            ).first()
            if found is not None:
                if found.library_id != (library.id or 0):
                    raise ValueError("路径已被其他媒体库占用")
                media = found
        created = media is None
        if media is None:
            media = MediaFile(
                item_id=item.id or 0,
                library_id=library.id or 0,
                rel_path=entry.rel_path,
                abs_path=entry.abs_path,
                url=url,
                size_bytes=entry.size,
                mtime=entry.mtime,
                missing=False,
                invalid=False,
                missing_count=0,
                version=parsed.version,
                part=parsed.part,
                labels=json.dumps(parsed.labels, ensure_ascii=False),
                created_at=utcnow(),
            )
            session.add(media)
            session.flush()
        else:
            media.item_id = item.id or media.item_id
            media.library_id = library.id or media.library_id
            media.rel_path = entry.rel_path
            media.abs_path = entry.abs_path
            media.url = url
            media.size_bytes = entry.size
            media.mtime = entry.mtime
            media.invalid = False
            media.version = parsed.version
            media.part = parsed.part
            media.labels = json.dumps(parsed.labels, ensure_ascii=False)
            session.add(media)
        return media, created

    # -- 解析规则版本 -----------------------------------------------------
    @staticmethod
    def _parser_version_key(library_id: int) -> str:
        return f"scanner:parser_version:{library_id}"

    def _parser_version_current(self, session: Session, library: Library) -> bool:
        row = session.get(Setting, self._parser_version_key(library.id or 0))
        return row is not None and row.value == str(PARSER_VERSION)

    def _mark_parser_version(self, session: Session, library_id: int) -> None:
        key = self._parser_version_key(library_id)
        row = session.get(Setting, key)
        if row is None:
            row = Setting(key=key, value=str(PARSER_VERSION), updated_at=utcnow())
        else:
            row.value = str(PARSER_VERSION)
            row.updated_at = utcnow()
        session.add(row)

    @staticmethod
    def _delete_item_dependents(session: Session, item_id: int) -> None:
        """删除指向 item 的子表行，否则 SQLite 外键会阻止清理旧条目。

        典型场景：旧版本把整季入成一条 movie，升级重扫后该 movie 被拆成
        series/season/episode，旧 movie 上残留的播放进度/缓存/凭证会让
        `DELETE FROM item` 触发 FOREIGN KEY constraint failed。
        """
        for model in (ImageTask, PlayProgress, PlaySession, PlayToken):
            session.exec(delete(model).where(model.item_id == item_id))

    # -- 清理 -------------------------------------------------------------
    def _prune_orphans(self, session: Session, library_id: int) -> None:
        items = session.exec(select(Item).where(Item.library_id == library_id)).all()
        media_item_ids = {
            m.item_id
            for m in session.exec(
                select(MediaFile).where(MediaFile.library_id == library_id)
            ).all()
        }
        by_id = {i.id: i for i in items if i.id is not None}
        children: dict[int | None, list[int]] = defaultdict(list)
        for item in items:
            if item.id is not None:
                children[item.parent_id].append(item.id)

        deletable: list[Item] = []
        # 自底向上：先删除空 episode/video/movie，再删除空 season/series/folder
        order = {"episode": 0, "video": 0, "movie": 0, "season": 1, "series": 2, "folder": 3}
        for item in sorted(items, key=lambda i: order.get(i.kind, 3), reverse=True):
            if item.id is None:
                continue
            if item.id in media_item_ids:
                continue
            if children.get(item.id):
                # 子项可能马上被删除，稍后由第二轮处理
                continue
            if item.deleted_at:
                deletable.append(item)
                continue
            deletable.append(item)

        # 迭代直到没有新的空节点
        changed = True
        while changed:
            changed = False
            for item in list(items):
                if item in deletable or item.id is None:
                    continue
                if item.id in media_item_ids:
                    continue
                live_children = [
                    c
                    for c in children.get(item.id, [])
                    if c not in {d.id for d in deletable}
                ]
                if not live_children:
                    deletable.append(item)
                    changed = True

        # 先删叶子，再删父级，避免自引用外键约束失败
        deletable.sort(key=lambda i: order.get(i.kind, 3))
        current_level = None
        for item in deletable:
            level = order.get(item.kind, 3)
            if current_level is not None and level != current_level:
                session.flush()
            if item.id is not None:
                self._delete_item_dependents(session, item.id)
            session.delete(item)
            current_level = level
        if deletable:
            session.flush()


def missing_cleanup(
    session: Session, settings: SettingsService, retention_days: int = 7
) -> int:
    """物理清理软删除超过保留期的条目。"""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=retention_days)).isoformat(
        timespec="seconds"
    )
    deleted = 0
    rows = session.exec(select(Item).where(Item.deleted_at != None)).all()  # noqa: E711
    for item in rows:
        if item.deleted_at and item.deleted_at < cutoff:
            session.delete(item)
            deleted += 1
    if deleted:
        session.commit()
    return deleted
