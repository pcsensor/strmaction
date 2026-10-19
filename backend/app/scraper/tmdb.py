"""TMDB API v3 Provider（附录 D.2）。"""

from __future__ import annotations

import base64
import json
from typing import Any

from ..config_store import SettingsService
from .base import (
    Candidate,
    CanonicalMeta,
    CastMember,
    EpisodeMeta,
    Kind,
    ProviderError,
    ProviderHealth,
    ProviderHTTP,
    SeasonDetail,
    SeasonSummary,
)
from .cache import cache_key, cache_load, cache_store
from .registry import register_provider

IMAGE_BASE = "https://image.tmdb.org/t/p/original"


def _year(date: str | None) -> int | None:
    if not date or len(date) < 4:
        return None
    try:
        return int(date[:4])
    except ValueError:
        return None


def _image_url(path: str | None) -> str | None:
    if not path:
        return None
    if path.startswith("http"):
        return path
    return f"{IMAGE_BASE}{path}"


def _lang_rank(code: str | None, prefer: str) -> int:
    prefer = (prefer or "zh").lower()
    code = (code or "").lower()
    if prefer.startswith("zh"):
        if code.startswith("zh"):
            return 0
    elif code == prefer:
        return 0
    if code in {"", "xx"}:
        return 1
    if code == "en":
        return 2
    return 3


def pick_image(
    images: dict[str, Any] | None,
    key: str,
    *,
    prefer_lang: str = "zh",
    aspect: tuple[float, float] | None = None,
) -> str | None:
    """语言优先 → 评分（票数 < 3 视作 0）→ 背景图长宽比过滤。"""
    if not images:
        return None
    items = images.get(key) or []
    scored: list[tuple[int, float, str]] = []
    for item in items:
        path = item.get("file_path")
        if not path:
            continue
        if aspect:
            ratio = item.get("aspect_ratio")
            if ratio and not (aspect[0] <= float(ratio) <= aspect[1]):
                continue
        votes = int(item.get("vote_count") or 0)
        score = float(item.get("vote_average") or 0) if votes >= 3 else 0.0
        scored.append((_lang_rank(item.get("iso_639_1"), prefer_lang), -score, path))
    if not scored:
        return None
    scored.sort()
    return scored[0][2]


def _pick_certification_movie(data: dict[str, Any]) -> str | None:
    results = (data.get("release_dates") or {}).get("results") or []
    for country in ("CN", "US", "HK", "TW"):
        for entry in results:
            if entry.get("iso_3166_1") != country:
                continue
            for release in entry.get("release_dates") or []:
                cert = (release.get("certification") or "").strip()
                if cert:
                    return cert
    return None


def _pick_certification_tv(data: dict[str, Any]) -> str | None:
    results = (data.get("content_ratings") or {}).get("results") or []
    for country in ("CN", "US", "HK", "TW"):
        for entry in results:
            if entry.get("iso_3166_1") == country and entry.get("rating"):
                return entry["rating"]
    return None


def _pick_trailer(data: dict[str, Any]) -> str | None:
    videos = ((data.get("videos") or {}).get("results")) or []
    best: tuple[int, int, str] | None = None
    for video in videos:
        if video.get("site") != "YouTube":
            continue
        if video.get("type") not in {"Trailer", "Teaser"}:
            continue
        key = video.get("key")
        if not key:
            continue
        type_rank = 0 if video.get("type") == "Trailer" else 1
        official_rank = 0 if video.get("official") else 1
        rank = (type_rank, official_rank, key)
        if best is None or rank < best:
            best = rank
    return best[2] if best else None


def _cast(data: dict[str, Any]) -> list[CastMember]:
    out: list[CastMember] = []
    credits = data.get("credits") or {}
    for member in (credits.get("cast") or [])[:20]:
        profile = member.get("profile_path")
        out.append(
            CastMember(
                name=member.get("name") or "",
                role=member.get("character") or None,
                avatar_url=_image_url(profile),
                kind="cast",
            )
        )
    for member in (credits.get("crew") or []):
        if member.get("job") not in {"Director", "Writer", "Screenplay"}:
            continue
        if len([c for c in out if c.kind != "cast"]) >= 6:
            break
        out.append(
            CastMember(
                name=member.get("name") or "",
                role=member.get("job"),
                avatar_url=_image_url(member.get("profile_path")),
                kind="director" if member.get("job") == "Director" else "writer",
            )
        )
    return out


def _aliases(data: dict[str, Any], kind: Kind) -> list[str]:
    alt = data.get("alternative_titles") or {}
    items = alt.get("titles") if kind == "movie" else alt.get("results")
    seen: set[str] = set()
    out: list[str] = []
    for item in items or []:
        title = (item.get("title") or "").strip()
        if title and title not in seen:
            seen.add(title)
            out.append(title)
    return out[:20]


def map_meta(data: dict[str, Any], kind: Kind, provider_id: str) -> CanonicalMeta:
    is_tv = kind == "tv"
    title = data.get("name" if is_tv else "title") or ""
    original = data.get("original_name" if is_tv else "original_title") or None
    if not title:
        title = original or ""
    year = _year(data.get("first_air_date" if is_tv else "release_date"))
    images = data.get("images") or {}
    poster = pick_image(images, "posters", prefer_lang="zh") or data.get("poster_path")
    backdrop = (
        pick_image(images, "backdrops", prefer_lang="zh", aspect=(1.6, 1.9))
        or data.get("backdrop_path")
    )
    logo = pick_image(images, "logos", prefer_lang="zh")
    runtime = data.get("runtime")
    if is_tv:
        runtimes = data.get("episode_run_time") or []
        runtime = runtimes[0] if runtimes else None
    external: dict[str, str] = {"tmdb": str(provider_id)}
    ext = data.get("external_ids") or {}
    if ext.get("imdb_id"):
        external["imdb"] = ext["imdb_id"]
    if ext.get("tvdb_id"):
        external["tvdb"] = str(ext["tvdb_id"])
    collection = None
    if data.get("belongs_to_collection"):
        coll = data["belongs_to_collection"]
        collection = {"id": coll.get("id"), "name": coll.get("name")}

    seasons: list[SeasonSummary] = []
    if is_tv:
        for season in data.get("seasons") or []:
            seasons.append(
                SeasonSummary(
                    season_no=int(season.get("season_number") or 0),
                    name=season.get("name"),
                    episode_count=int(season.get("episode_count") or 0),
                    poster_url=_image_url(season.get("poster_path")),
                    air_date=season.get("air_date"),
                )
            )

    rating = data.get("vote_average")
    return CanonicalMeta(
        provider="tmdb",
        provider_id=str(provider_id),
        kind=kind,
        title=title,
        original_title=original,
        aliases=_aliases(data, kind),
        year=year,
        overview=data.get("overview") or None,
        tagline=data.get("tagline") or None,
        rating=float(rating) if rating else None,
        runtime_min=int(runtime) if runtime else None,
        genres=[g.get("name") for g in data.get("genres") or [] if g.get("name")],
        certification=(
            _pick_certification_tv(data) if is_tv else _pick_certification_movie(data)
        ),
        status=data.get("status"),
        cast=_cast(data),
        trailer_key=_pick_trailer(data),
        collection=collection,
        poster_url=_image_url(poster),
        backdrop_url=_image_url(backdrop),
        logo_url=_image_url(logo),
        external_ids=external,
        seasons=seasons,
    )


@register_provider("tmdb")
class TmdbProvider:
    name = "tmdb"
    supports: set[Kind] = {"movie", "tv"}

    def __init__(self, settings: SettingsService):
        config = settings.provider_config("tmdb")
        self.config = config
        self.api_key = (config.get("api_key") or "").strip()
        self.language = config.get("language") or settings.language() or "zh-CN"
        self.engine = settings.engine
        self.http: ProviderHTTP | None = None
        if self.api_key:
            self.http = ProviderHTTP(
                base_url=config.get("base_url") or "https://api.themoviedb.org/3",
                provider="tmdb",
                proxy=config.get("proxy") or settings.scraper().get("proxy") or "",
                rate_limit=float(config.get("rate_limit") or 8),
            )

    @property
    def enabled(self) -> bool:
        return bool(self.api_key)

    async def close(self) -> None:
        if self.http:
            await self.http.close()

    def _params(self) -> dict[str, Any]:
        params: dict[str, Any] = {
            "language": self.language,
            "include_adult": "false",
            "region": "CN",
        }
        # v4 Bearer Token 以 eyJ 开头；v3 Key 走 query 参数
        if not self.api_key.startswith("eyJ"):
            params["api_key"] = self.api_key
        return params

    def _headers(self) -> dict[str, str]:
        if self.api_key.startswith("eyJ"):
            return {"Authorization": f"Bearer {self.api_key}"}
        return {}

    async def _cached(
        self,
        path: str,
        params: dict[str, Any],
        *,
        tag: str,
        ttl_days: int,
    ) -> dict[str, Any]:
        if self.http is None:
            raise ProviderError("config", "未配置 TMDB API Key")
        key = cache_key("tmdb", tag, path, params)
        hit = cache_load(self.engine, "tmdb", key)
        if hit is not None:
            return hit
        data = await self.http.request(
            "GET", path, params=params, headers=self._headers()
        )
        cache_store(self.engine, "tmdb", key, data, ttl_days)
        return data

    # -- 接口 -------------------------------------------------------------
    async def search(
        self, *, title: str, year: int | None, kind: Kind
    ) -> list[Candidate]:
        if not title:
            return []
        params = self._params()
        params["query"] = title
        if year:
            params["year" if kind == "movie" else "first_air_date_year"] = str(year)
        path = "/search/movie" if kind == "movie" else "/search/tv"
        data = await self._cached(path, params, tag="search", ttl_days=7)
        out: list[Candidate] = []
        for rank, item in enumerate(data.get("results") or []):
            item_year = _year(
                item.get("release_date" if kind == "movie" else "first_air_date")
            )
            poster = _image_url(item.get("poster_path"))
            out.append(
                Candidate(
                    provider="tmdb",
                    provider_id=str(item.get("id")),
                    title=item.get("title" if kind == "movie" else "name") or "",
                    original_title=item.get(
                        "original_title" if kind == "movie" else "original_name"
                    ),
                    year=item_year,
                    kind=kind,
                    overview=item.get("overview"),
                    poster_url=poster,
                    popularity=float(item.get("popularity") or 0),
                    aliases=[item.get("original_title" if kind == "movie" else "original_name") or ""],
                    raw=item,
                )
            )
        return out

    async def fetch(self, provider_id: str, *, kind: Kind) -> CanonicalMeta:
        params = self._params()
        append = (
            "credits,videos,images,external_ids,alternative_titles,release_dates"
            if kind == "movie"
            else "credits,videos,images,external_ids,alternative_titles,content_ratings"
        )
        params["append_to_response"] = append
        path = f"/{'movie' if kind == 'movie' else 'tv'}/{provider_id}"
        data = await self._cached(path, params, tag="detail", ttl_days=30)
        meta = map_meta(data, kind, provider_id)

        # 中文简介/标题缺失时回落英文（仅补空，不覆盖）
        if not meta.overview or not meta.title:
            en_params = dict(params)
            en_params["language"] = "en-US"
            try:
                en_data = await self._cached(
                    path, en_params, tag="detail_en", ttl_days=30
                )
                en_meta = map_meta(en_data, kind, provider_id)
                if not meta.overview:
                    meta.overview = en_meta.overview
                if not meta.title:
                    meta.title = en_meta.title
                if not meta.original_title:
                    meta.original_title = en_meta.original_title
            except ProviderError:
                pass
        return meta

    async def resolve_external(self, external_id: str, kind: Kind) -> str | None:
        """把 imdb id（tt...）解析成 TMDB id。"""
        params = self._params()
        params["external_source"] = "imdb_id"
        data = await self._cached(
            f"/find/{external_id}", params, tag="find", ttl_days=30
        )
        results = data.get("movie_results" if kind == "movie" else "tv_results") or []
        for item in results:
            if item.get("id"):
                return str(item["id"])
        return None

    async def fetch_season(self, provider_id: str, season_no: int) -> SeasonDetail:
        params = self._params()
        path = f"/tv/{provider_id}/season/{season_no}"
        data = await self._cached(
            path, params, tag=f"season:{season_no}", ttl_days=30
        )
        episodes: list[EpisodeMeta] = []
        for item in data.get("episodes") or []:
            number = item.get("episode_number")
            if number is None:
                continue
            episodes.append(
                EpisodeMeta(
                    episode_no=int(number),
                    title=item.get("name"),
                    overview=item.get("overview"),
                    runtime_min=int(item["runtime"]) if item.get("runtime") else None,
                    air_date=item.get("air_date"),
                    still_url=_image_url(item.get("still_path")),
                )
            )
        return SeasonDetail(season_no=season_no, episodes=episodes)

    async def health(self) -> ProviderHealth:
        import time

        started = time.monotonic()
        if not self.enabled or self.http is None:
            return ProviderHealth(False, "config", "未配置 TMDB API Key")
        try:
            await self.http.request(
                "GET", "/configuration", params=self._params(), headers=self._headers()
            )
            return ProviderHealth(
                True,
                "ok",
                "TMDB 连接正常",
                int((time.monotonic() - started) * 1000),
            )
        except ProviderError as exc:
            return ProviderHealth(
                False,
                exc.kind,
                exc.message,
                int((time.monotonic() - started) * 1000),
            )
