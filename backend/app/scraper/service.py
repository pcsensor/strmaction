"""刮削主流程：搜索 → 打分 → 绑定 → 写库 → 下图 → 取色（附录 D.5）。"""

from __future__ import annotations

import asyncio
import json
import re
from dataclasses import asdict
from typing import Any

from sqlmodel import Session, select

from ..config_store import SettingsService
from ..images import ImageService
from ..models import Item, Library, MediaFile, utcnow
from ..text import normalize_title
from .base import (
    Candidate,
    CanonicalMeta,
    CastMember,
    EpisodeMeta,
    Kind,
    MetadataProvider,
    ProviderError,
    SeasonDetail,
)
from .matcher import classify, episode_penalty, rank_candidates
from .merge import fill_missing
from .nfo import find_nfo, parse_nfo
from .tmdb import TmdbProvider
from .tvdb import TvdbProvider

_SINGLEFLIGHT: dict[int, asyncio.Lock] = {}

LOCKABLE_FIELDS = {
    "title",
    "original_title",
    "year",
    "overview",
    "tagline",
    "runtime_min",
    "rating",
    "genres",
    "cast",
    "certification",
    "trailer_key",
    "collection",
    "poster_path",
    "backdrop_path",
    "logo_path",
    "color_primary",
}


def _loads(value: str | None) -> Any:
    if not value:
        return None
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return None


def _locked(item: Item) -> set[str]:
    value = _loads(item.locked_fields)
    return set(value) if isinstance(value, list) else set()


class ProviderRegistry:
    def __init__(self, settings: SettingsService):
        self.settings = settings
        self._providers: dict[str, MetadataProvider] = {}

    def get(self, name: str) -> MetadataProvider | None:
        if name in self._providers:
            return self._providers[name]
        provider: MetadataProvider | None = None
        if name == "tmdb":
            provider = TmdbProvider(self.settings)
        elif name == "tvdb":
            provider = TvdbProvider(self.settings)
        if provider is not None:
            self._providers[name] = provider
        return provider

    async def close(self) -> None:
        for provider in self._providers.values():
            close = getattr(provider, "close", None)
            if close:
                try:
                    await close()
                except Exception:
                    pass
        self._providers.clear()


class ScrapeService:
    def __init__(
        self,
        engine,
        settings: SettingsService,
        images: ImageService,
        registry: ProviderRegistry | None = None,
    ):
        self.engine = engine
        self.settings = settings
        self.images = images
        self.registry = registry or ProviderRegistry(settings)

    async def close(self) -> None:
        await self.registry.close()

    # -- 单条 -------------------------------------------------------------
    async def scrape_item(
        self, item_id: int, *, force: bool = False, manual: bool = False
    ) -> dict[str, Any]:
        lock = _SINGLEFLIGHT.setdefault(item_id, asyncio.Lock())
        async with lock:
            try:
                return await self._scrape(item_id, force=force, manual=manual)
            except Exception as exc:  # pragma: no cover - 防御
                self._set_failed(item_id, f"内部错误: {exc}")
                return {"status": "failed", "item_id": item_id, "reason": str(exc)}

    async def _scrape(
        self, item_id: int, *, force: bool, manual: bool
    ) -> dict[str, Any]:
        with Session(self.engine) as session:
            item = session.get(Item, item_id)
            if item is None:
                return {"status": "missing", "item_id": item_id}
            target = self._resolve_target(session, item)
            if target is None:
                return {"status": "skipped", "item_id": item_id, "reason": "no_target"}
            library = session.get(Library, target.library_id)
            if library is None or library.type in {"home", "course"}:
                return {"status": "skipped", "item_id": target.id}
            if target.match_state == "manual" and not force and not manual:
                return {"status": "skipped", "item_id": target.id, "reason": "manual"}
            kind: Kind = "movie" if target.kind == "movie" else "tv"
            media = session.exec(
                select(MediaFile)
                .where(
                    MediaFile.item_id.in_(
                        self._media_item_ids(session, target)
                    ),
                    MediaFile.invalid == False,  # noqa: E712
                    MediaFile.missing == False,  # noqa: E712
                )
                .limit(1)
            ).first()
            parsed = _loads(target.parse_payload) or {}
            query_title = (
                parsed.get("group_title")
                or parsed.get("parse_title")
                or target.title
            )
            query_year = parsed.get("year") or target.year
            explicit_ids: dict[str, str] = {}
            for source in (parsed.get("explicit_ids"), _loads(target.external_ids)):
                if isinstance(source, dict):
                    for key, value in source.items():
                        if key in {"tmdb", "tvdb", "imdb"} and value:
                            explicit_ids.setdefault(key, str(value))
            priority = self.settings.priority_for_library(library)
            season_type = self.settings.tvdb_season_type(library)
            episodes, seasons = self._children(session, target)

        # ① 本地 .nfo 完全接管
        if media is not None:
            nfo_path = find_nfo(media.abs_path, kind, library.root_path)
            if nfo_path is not None:
                data = parse_nfo(nfo_path)
                if data:
                    meta = self._meta_from_nfo(data, kind)
                    return await self._persist(
                        target.id,
                        meta,
                        state="auto",
                        score=1.0,
                        filled=[],
                        season_type=season_type,
                        force=force,
                    )

        providers: list[MetadataProvider] = []
        for name in priority:
            provider = self.registry.get(name)
            if provider is None:
                continue
            if not bool(getattr(provider, "enabled", False)):
                continue
            if getattr(provider, "season_type", None) is not None:
                provider.season_type = season_type  # type: ignore[attr-defined]
            providers.append(provider)
        if not providers:
            self._mark_skipped(target.id, "no_provider")
            return {"status": "skipped", "item_id": target.id, "reason": "no_provider"}

        errors: list[str] = []
        winning: tuple[MetadataProvider, CanonicalMeta, float] | None = None
        for provider in providers:
            explicit = explicit_ids.get(provider.name)
            if not explicit and provider.name == "tmdb" and explicit_ids.get("imdb"):
                try:
                    explicit = await provider.resolve_external(  # type: ignore[attr-defined]
                        explicit_ids["imdb"], kind
                    )
                except ProviderError as exc:
                    errors.append(f"{provider.name}:{exc.kind}")
                    explicit = None
            if explicit:
                try:
                    meta = await provider.fetch(explicit, kind=kind)
                    winning = (provider, meta, 1.0)
                    break
                except ProviderError as exc:
                    errors.append(f"{provider.name}:{exc.kind}")
                    continue
            try:
                candidates = await provider.search(
                    title=query_title, year=query_year, kind=kind
                )
            except ProviderError as exc:
                errors.append(f"{provider.name}:{exc.kind}")
                continue
            if not candidates:
                errors.append(f"{provider.name}:no_match")
                continue
            ranked = rank_candidates(query_title, query_year, candidates)
            best_score, best = ranked[0]
            if best_score < 0.60:
                errors.append(f"{provider.name}:low_score")
                continue
            try:
                meta = await provider.fetch(best.provider_id, kind=kind)
            except ProviderError as exc:
                errors.append(f"{provider.name}:{exc.kind}")
                continue
            # 集数明显不符时降权
            if kind == "tv":
                max_episode = max((ep.episode_no or 0 for ep in episodes), default=0)
                total_episodes = sum(s.episode_count for s in meta.seasons) or None
                best_score = episode_penalty(best_score, max_episode, total_episodes)
            winning = (provider, meta, best_score)
            break

        if winning is None:
            self._set_failed(target.id, "no_match", errors)
            return {
                "status": "failed",
                "item_id": target.id,
                "reason": "no_match",
                "errors": errors,
            }

        provider, meta, score = winning
        filled: list[str] = []
        # 跨源补空（只补空，季集不混用）
        other_ids = {
            key: value
            for key, value in (meta.external_ids or {}).items()
            if key in {"tmdb", "tvdb"} and key != provider.name and value
        }
        for other_name, other_id in other_ids.items():
            other = self.registry.get(other_name)
            if other is None or not bool(getattr(other, "enabled", False)):
                continue
            try:
                other_meta = await other.fetch(str(other_id), kind=kind)
                filled = fill_missing(meta, other_meta)
            except ProviderError:
                pass
            break

        state = "manual" if manual else classify(score, self.settings.match_threshold())
        return await self._persist(
            target.id,
            meta,
            state=state,
            score=score,
            filled=filled,
            season_type=season_type,
            force=force,
        )

    # -- 持久化 -----------------------------------------------------------
    async def _persist(
        self,
        item_id: int,
        meta: CanonicalMeta,
        *,
        state: str,
        score: float,
        filled: list[str],
        season_type: str,
        force: bool,
    ) -> dict[str, Any]:
        episodes, seasons = self._children_by_id(item_id)
        season_details: dict[int, SeasonDetail] = {}
        absolute_episodes: list[EpisodeMeta] | None = None
        warnings: list[str] = []
        provider = self.registry.get(meta.provider)

        if meta.kind == "tv" and provider is not None and hasattr(provider, "fetch_season"):
            if season_type == "absolute" and hasattr(provider, "fetch_absolute"):
                try:
                    detail = await provider.fetch_absolute(meta.provider_id)  # type: ignore[attr-defined]
                    absolute_episodes = detail.episodes
                except ProviderError as exc:
                    warnings.append(f"absolute:{exc.kind}")
            else:
                season_numbers = sorted(
                    {ep.season_no for ep in episodes if ep.season_no is not None}
                )
                if not season_numbers:
                    season_numbers = [
                        s.season_no
                        for s in meta.seasons
                        if s.season_no and s.season_no > 0
                    ][:10]
                for number in season_numbers:
                    if number == 0:
                        continue
                    try:
                        season_details[number] = await provider.fetch_season(  # type: ignore[union-attr]
                            meta.provider_id, number
                        )
                    except ProviderError as exc:
                        warnings.append(f"season {number}:{exc.kind}")

        hash_payload: dict[str, Any] = meta.payload()
        hash_payload["episodes"] = self._episode_hash_payload(
            episodes, season_details, absolute_episodes
        )
        payload_hash = __import__("hashlib").sha1(
            json.dumps(hash_payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest()

        jobs: list[tuple[int, str, str, str | None]] = []
        with Session(self.engine) as session:
            root = session.get(Item, item_id)
            if root is None:
                return {"status": "missing", "item_id": item_id}
            unchanged = root.meta_hash == payload_hash and not force
            episodes_db, _ = self._children(session, root)
            self._apply_item(session, root, meta, state)
            self._apply_seasons(session, root, meta, jobs)
            if not unchanged:
                self._apply_episodes(
                    session,
                    episodes_db,
                    season_details,
                    absolute_episodes,
                    jobs,
                )
                root.meta_hash = payload_hash
                root.updated_at = utcnow()
                session.add(root)
            session.commit()

        # 主图同步下载（poster/backdrop/logo），头像/剧照异步
        poster_sha = await self.images.ensure(meta.poster_url, "poster")
        backdrop_sha = await self.images.ensure(meta.backdrop_url, "backdrop")
        logo_sha = await self.images.ensure(meta.logo_url, "logo")
        color = None
        if backdrop_sha:
            color = await self.images.color_for(meta.backdrop_url, backdrop_sha)

        with Session(self.engine) as session:
            root = session.get(Item, item_id)
            if root is not None:
                locked = _locked(root)
                if poster_sha and "poster_path" not in locked:
                    root.poster_path = poster_sha
                if backdrop_sha and "backdrop_path" not in locked:
                    root.backdrop_path = backdrop_sha
                if color and "color_primary" not in locked:
                    root.color_primary = color
                if logo_sha and "logo_path" not in locked:
                    root.logo_path = logo_sha
                cast = _loads(root.cast)
                if isinstance(cast, list):
                    for index, member in enumerate(cast):
                        avatar_url = (
                            member.get("avatar_url")
                            if isinstance(member, dict)
                            else None
                        )
                        if avatar_url:
                            jobs.append((root.id, "thumb", avatar_url, f"cast:{index}"))
                root.updated_at = utcnow()
                session.add(root)
                session.commit()

        for job in jobs:
            self.images.enqueue(*job)

        return {
            "status": "ok",
            "item_id": item_id,
            "provider": meta.provider,
            "provider_id": meta.provider_id,
            "match_state": state,
            "score": round(score, 4),
            "filled": filled,
            "warnings": warnings,
            "unchanged": unchanged,
        }

    def _apply_item(
        self, session: Session, item: Item, meta: CanonicalMeta, state: str
    ) -> None:
        locked = _locked(item)
        if "title" not in locked and meta.title:
            item.title = meta.title
        if "original_title" not in locked and meta.original_title:
            item.original_title = meta.original_title
        if "year" not in locked and meta.year:
            item.year = meta.year
        if "overview" not in locked and meta.overview:
            item.overview = meta.overview
        if "tagline" not in locked and meta.tagline:
            item.tagline = meta.tagline
        if "runtime_min" not in locked and meta.runtime_min:
            item.runtime_min = meta.runtime_min
        if "rating" not in locked and meta.rating:
            item.rating = meta.rating
        if "genres" not in locked and meta.genres:
            item.genres = json.dumps(meta.genres, ensure_ascii=False)
        if "certification" not in locked and meta.certification:
            item.certification = meta.certification
        if meta.status:
            item.status = meta.status
        if "trailer_key" not in locked and meta.trailer_key:
            item.trailer_key = meta.trailer_key
        if "collection" not in locked and meta.collection:
            item.collection = json.dumps(meta.collection, ensure_ascii=False)
        if not locked & {"cast"} and meta.cast:
            item.cast = json.dumps(
                [
                    {
                        "name": c.name,
                        "role": c.role,
                        "avatar_url": c.avatar_url,
                        "avatar": None,
                        "kind": c.kind,
                    }
                    for c in meta.cast
                ],
                ensure_ascii=False,
            )
        if meta.aliases:
            item.alt_titles = json.dumps(meta.aliases, ensure_ascii=False)
        item.provider = meta.provider
        item.provider_id = str(meta.provider_id)
        item.external_ids = json.dumps(meta.external_ids, ensure_ascii=False)
        item.match_state = state
        item.sort_title = normalize_title(item.title)
        item.updated_at = utcnow()
        session.add(item)

    def _apply_seasons(
        self,
        session: Session,
        root: Item,
        meta: CanonicalMeta,
        jobs: list[tuple[int, str, str, str | None]],
    ) -> None:
        if meta.kind != "tv" or not meta.seasons:
            return
        mapping = {s.season_no: s for s in meta.seasons}
        rows = session.exec(
            select(Item).where(Item.parent_id == root.id, Item.kind == "season")
        ).all()
        for season in rows:
            summary = mapping.get(season.season_no or 0)
            if summary and summary.poster_url:
                jobs.append((season.id, "poster", summary.poster_url, "poster_path"))
                session.add(season)

    def _apply_episodes(
        self,
        session: Session,
        episodes: list[Item],
        season_details: dict[int, SeasonDetail],
        absolute_episodes: list[EpisodeMeta] | None,
        enqueue_jobs: list[tuple[int, str, str, str | None]],
    ) -> None:
        mapping: dict[tuple[int, int], EpisodeMeta] = {}
        for season_no, detail in season_details.items():
            for episode in detail.episodes:
                mapping[(season_no, episode.episode_no)] = episode

        if absolute_episodes:
            ordered = sorted(
                episodes, key=lambda e: (e.season_no or 0, e.episode_no or 0)
            )
            for episode, meta in zip(ordered, absolute_episodes):
                self._apply_episode(session, episode, meta, enqueue_jobs)
            return

        for episode in episodes:
            key = (episode.season_no or 0, episode.episode_no or 0)
            meta = mapping.get(key)
            if meta is None:
                continue
            self._apply_episode(session, episode, meta, enqueue_jobs)

    def _apply_episode(
        self,
        session: Session,
        episode: Item,
        meta: EpisodeMeta,
        enqueue_jobs: list[tuple[int, str, str, str | None]],
    ) -> None:
        locked = _locked(episode)
        if "title" not in locked and meta.title:
            episode.title = meta.title
        if "overview" not in locked and meta.overview:
            episode.overview = meta.overview
        if "runtime_min" not in locked and meta.runtime_min:
            episode.runtime_min = meta.runtime_min
        if meta.air_date:
            episode.air_date = meta.air_date
        episode.match_state = "auto"
        if meta.still_url:
            enqueue_jobs.append((episode.id, "still", meta.still_url, "still_path"))
        episode.updated_at = utcnow()
        session.add(episode)

    # -- 手动绑定 ---------------------------------------------------------
    async def bind(
        self, item_id: int, provider_name: str, provider_id: str
    ) -> dict[str, Any]:
        provider = self.registry.get(provider_name)
        if provider is None or not bool(getattr(provider, "enabled", False)):
            return {"status": "failed", "reason": "provider_unavailable"}
        with Session(self.engine) as session:
            item = session.get(Item, item_id)
            if item is None:
                return {"status": "missing"}
            target = self._resolve_target(session, item)
            library = session.get(Library, target.library_id) if target else None
            if target is None or library is None:
                return {"status": "failed", "reason": "no_target"}
            kind: Kind = "movie" if target.kind == "movie" else "tv"
            season_type = self.settings.tvdb_season_type(library)
        if getattr(provider, "season_type", None) is not None:
            provider.season_type = season_type  # type: ignore[attr-defined]
        if provider_name == "tmdb" and str(provider_id).lower().startswith("tt"):
            try:
                resolved = await provider.resolve_external(  # type: ignore[attr-defined]
                    str(provider_id), kind
                )
            except ProviderError as exc:
                return {"status": "failed", "reason": exc.kind, "message": exc.message}
            if not resolved:
                return {
                    "status": "failed",
                    "reason": "notfound",
                    "message": "该 IMDb ID 在 TMDB 中没有对应条目",
                }
            provider_id = resolved
        try:
            meta = await provider.fetch(str(provider_id), kind=kind)
        except ProviderError as exc:
            return {"status": "failed", "reason": exc.kind, "message": exc.message}
        return await self._persist(
            target.id,
            meta,
            state="manual",
            score=1.0,
            filled=[],
            season_type=season_type,
            force=True,
        )

    async def unmatch(self, item_id: int) -> dict[str, Any]:
        with Session(self.engine) as session:
            target = self._resolve_target(session, session.get(Item, item_id))
            if target is None:
                return {"status": "missing"}
            parsed = _loads(target.parse_payload) or {}
            target.match_state = "failed"
            target.provider = None
            target.provider_id = None
            target.external_ids = None
            target.meta_hash = None
            # 回到文件名兜底展示
            fallback_title = (
                parsed.get("group_title")
                or parsed.get("parse_title")
                or target.title
            )
            if fallback_title:
                target.title = str(fallback_title)
                target.sort_title = normalize_title(target.title)
            if parsed.get("year"):
                target.year = parsed.get("year")
            for field in (
                "overview",
                "tagline",
                "runtime_min",
                "rating",
                "genres",
                "cast",
                "certification",
                "alt_titles",
                "trailer_key",
                "collection",
                "status",
                "poster_path",
                "backdrop_path",
                "logo_path",
                "color_primary",
            ):
                setattr(target, field, None)
            target.updated_at = utcnow()
            session.add(target)
            session.commit()
            return {"status": "ok", "item_id": target.id, "match_state": "failed"}

    # -- 候选 -------------------------------------------------------------
    async def candidates(
        self,
        item_id: int,
        query: str | None,
        provider_name: str | None = None,
    ) -> list[dict[str, Any]]:
        with Session(self.engine) as session:
            item = self._resolve_target(session, session.get(Item, item_id))
            if item is None:
                return []
            parsed = _loads(item.parse_payload) or {}
            query = (
                query
                or parsed.get("group_title")
                or parsed.get("parse_title")
                or item.title
            )
            year = parsed.get("year") or item.year
            kind: Kind = "movie" if item.kind == "movie" else "tv"
            library = session.get(Library, item.library_id)
            priority = (
                self.settings.priority_for_library(library)
                if library
                else ["tmdb", "tvdb"]
            )
        names = [provider_name] if provider_name else priority
        out: list[dict[str, Any]] = []
        for name in names:
            provider = self.registry.get(name)
            if provider is None or not bool(getattr(provider, "enabled", False)):
                continue
            try:
                candidates = await provider.search(title=query, year=year, kind=kind)
            except ProviderError:
                continue
            ranked = rank_candidates(query, year, candidates)
            for score, candidate in ranked[:12]:
                out.append(
                    {
                        "provider": candidate.provider,
                        "provider_id": candidate.provider_id,
                        "title": candidate.title,
                        "original_title": candidate.original_title,
                        "year": candidate.year,
                        "overview": candidate.overview,
                        "poster_url": candidate.poster_url,
                        "score": round(score, 4),
                        "kind": kind,
                    }
                )
        out.sort(key=lambda c: c["score"], reverse=True)
        return out

    # -- 辅助 -------------------------------------------------------------
    def _resolve_target(self, session: Session, item: Item | None) -> Item | None:
        if item is None:
            return None
        current = item
        guard = 0
        while current is not None and current.kind not in {"movie", "series", "video"}:
            if current.parent_id is None:
                return None
            current = session.get(Item, current.parent_id)
            guard += 1
            if guard > 6:
                return None
        if current is None or current.kind == "video":
            return None
        return current

    def _media_item_ids(self, session: Session, target: Item) -> list[int]:
        if target.kind == "movie":
            return [target.id]
        ids = [target.id]
        for season in session.exec(
            select(Item).where(Item.parent_id == target.id, Item.kind == "season")
        ).all():
            ids.append(season.id)
            for episode in session.exec(
                select(Item).where(Item.parent_id == season.id, Item.kind == "episode")
            ).all():
                ids.append(episode.id)
        return ids

    def _children(
        self, session: Session, target: Item
    ) -> tuple[list[Item], list[Item]]:
        seasons = session.exec(
            select(Item)
            .where(Item.parent_id == target.id, Item.kind == "season")
            .order_by(Item.season_no)
        ).all()
        season_ids = [s.id for s in seasons]
        episodes: list[Item] = []
        if season_ids:
            episodes = session.exec(
                select(Item)
                .where(Item.parent_id.in_(season_ids), Item.kind == "episode")
                .order_by(Item.season_no, Item.episode_no)
            ).all()
        return episodes, seasons

    def _children_by_id(self, item_id: int) -> tuple[list[Item], list[Item]]:
        with Session(self.engine) as session:
            target = session.get(Item, item_id)
            if target is None:
                return [], []
            return self._children(session, target)

    def _episode_hash_payload(
        self,
        episodes: list[Item],
        season_details: dict[int, SeasonDetail],
        absolute: list[EpisodeMeta] | None,
    ) -> list[dict[str, Any]]:
        if absolute:
            return [
                {
                    "t": e.title,
                    "o": e.overview,
                    "r": e.runtime_min,
                    "s": e.still_url,
                }
                for e in absolute
            ]
        out = []
        for episode in episodes:
            detail = season_details.get(episode.season_no or 0)
            meta = None
            if detail:
                for item in detail.episodes:
                    if item.episode_no == episode.episode_no:
                        meta = item
                        break
            if meta:
                out.append(
                    {
                        "t": meta.title,
                        "o": meta.overview,
                        "r": meta.runtime_min,
                        "s": meta.still_url,
                    }
                )
        return out

    def _meta_from_nfo(self, data: dict[str, Any], kind: Kind) -> CanonicalMeta:
        cast = [
            CastMember(
                name=member.get("name") or "",
                role=member.get("role"),
                avatar_url=member.get("avatar"),
                kind=member.get("kind", "cast"),
            )
            for member in data.get("cast") or []
        ]
        return CanonicalMeta(
            provider="nfo",
            provider_id=data.get("path") or "nfo",
            kind=kind,
            title=data.get("title") or "",
            original_title=data.get("original_title"),
            year=data.get("year"),
            overview=data.get("overview"),
            tagline=data.get("tagline"),
            rating=data.get("rating"),
            runtime_min=data.get("runtime_min"),
            genres=list(data.get("genres") or []),
            certification=data.get("certification"),
            status=data.get("status"),
            cast=cast,
            trailer_key=data.get("trailer_key"),
            poster_url=data.get("poster"),
            backdrop_url=data.get("backdrop"),
            external_ids=dict(data.get("external_ids") or {}),
        )

    def _mark_skipped(self, item_id: int, reason: str) -> None:
        with Session(self.engine) as session:
            item = session.get(Item, item_id)
            if item is None or item.match_state == "manual":
                return
            # 已有成功刮削结果的条目，不应因为一次「没配置 Key」的刷新而降级
            if item.provider and item.provider_id:
                return
            item.match_state = "skipped"
            item.updated_at = utcnow()
            session.add(item)
            session.commit()

    def _set_failed(self, item_id: int, reason: str, errors: list[str] | None = None) -> None:
        with Session(self.engine) as session:
            item = session.get(Item, item_id)
            if item is None or item.match_state == "manual":
                return
            item.match_state = "failed"
            item.updated_at = utcnow()
            session.add(item)
            session.commit()

    # -- 批量 -------------------------------------------------------------
    async def scrape_items(
        self,
        item_ids: list[int],
        *,
        force: bool = False,
        progress_cb=None,
    ) -> dict[str, Any]:
        stats = {"total": len(item_ids), "ok": 0, "failed": 0, "skipped": 0}
        failures: list[dict[str, Any]] = []
        for index, item_id in enumerate(item_ids):
            result = await self.scrape_item(item_id, force=force)
            status = result.get("status")
            if status == "ok":
                stats["ok"] += 1
            elif status in {"failed", "missing"}:
                stats["failed"] += 1
                failures.append(
                    {
                        "item_id": item_id,
                        "reason": result.get("reason") or status,
                        "errors": result.get("errors"),
                    }
                )
            else:
                stats["skipped"] += 1
            if progress_cb and (index % 5 == 0 or index == len(item_ids) - 1):
                progress_cb(
                    {
                        "done": index + 1,
                        "total": len(item_ids),
                        "stats": stats,
                        "failures": failures[-20:],
                    }
                )
        stats["failures"] = failures[-100:]
        return stats
