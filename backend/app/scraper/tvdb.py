"""TVDB v4 Provider（附录 D.3）。"""

from __future__ import annotations

import asyncio
import base64
import json
import time
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlmodel import Session

from ..config_store import SettingsService
from ..models import ProviderToken, utcnow
from .registry import register_provider
from .base import (
    Candidate,
    CanonicalMeta,
    EpisodeMeta,
    Kind,
    ProviderError,
    ProviderHealth,
    ProviderHTTP,
    SeasonDetail,
    SeasonSummary,
)
from .cache import cache_key, cache_load, cache_store


def _jwt_exp(token: str) -> datetime | None:
    try:
        payload = token.split(".")[1]
        padding = "=" * (-len(payload) % 4)
        data = json.loads(base64.urlsafe_b64decode(payload + padding))
        exp = int(data["exp"])
        return datetime.fromtimestamp(exp, timezone.utc)
    except (IndexError, KeyError, ValueError, json.JSONDecodeError):
        return None


def _year(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, int):
        return value
    text = str(value)
    if len(text) >= 4 and text[:4].isdigit():
        return int(text[:4])
    return None


def _translation(payload: Any) -> dict[str, Any]:
    """TVDB translations 字段结构在不同版本间有差异，做兼容提取。"""
    if isinstance(payload, dict):
        if isinstance(payload.get("data"), dict):
            return payload["data"]
        return payload
    return {}


def pick_artwork(
    artworks: list[dict[str, Any]], kind: str, language: str = "zho"
) -> str | None:
    candidates = [
        a
        for a in artworks
        if (a.get("type") or "").lower() == kind and a.get("image")
    ]
    if not candidates:
        return None

    def rank(item: dict[str, Any]) -> tuple[int, float]:
        lang = (item.get("language") or "").lower()
        if lang == language:
            lang_rank = 0
        elif lang in {"", "eng"}:
            lang_rank = 1
        else:
            lang_rank = 2
        return lang_rank, -float(item.get("score") or 0)

    candidates.sort(key=rank)
    return candidates[0]["image"]


@register_provider("tvdb")
class TvdbProvider:
    name = "tvdb"
    supports: set[Kind] = {"movie", "tv"}

    def __init__(self, settings: SettingsService):
        config = settings.provider_config("tvdb")
        self.config = config
        self.settings = settings
        self.engine = settings.engine
        self.api_key = (config.get("api_key") or "").strip()
        self.pin = (config.get("pin") or "").strip()
        self.base_url = (config.get("base_url") or "https://api4.thetvdb.com/v4").rstrip("/")
        self.language = config.get("language") or "zho"
        self.season_type = config.get("season_type") or "default"
        self.http: ProviderHTTP | None = None
        self._token: str | None = None
        self._token_expires: datetime | None = None
        self._login_lock = asyncio.Lock()
        if self.api_key:
            self.http = ProviderHTTP(
                base_url=self.base_url,
                provider="tvdb",
                proxy=config.get("proxy") or settings.scraper().get("proxy") or "",
                rate_limit=float(config.get("rate_limit") or 4),
            )

    @property
    def enabled(self) -> bool:
        return bool(self.api_key)

    async def close(self) -> None:
        if self.http:
            await self.http.close()

    # -- 鉴权 -------------------------------------------------------------
    def _load_token(self) -> None:
        with Session(self.engine) as session:
            row = session.get(ProviderToken, "tvdb")
            if row is None:
                return
            expires = None
            if row.expires_at:
                try:
                    expires = datetime.fromisoformat(row.expires_at)
                except ValueError:
                    expires = None
            if expires and expires > datetime.now(timezone.utc) + timedelta(hours=24):
                self._token = row.token
                self._token_expires = expires

    async def _login(self, force: bool = False) -> str:
        async with self._login_lock:
            return await self._login_locked(force)

    async def _login_locked(self, force: bool) -> str:
        if self.http is None:
            raise ProviderError("config", "未配置 TVDB API Key")
        if not self.api_key:
            raise ProviderError("config", "未配置 TVDB API Key")
        if not force and self._token:
            return self._token
        body: dict[str, Any] = {"apikey": self.api_key}
        if self.pin:
            body["pin"] = self.pin
        try:
            data = await self.http.request("POST", "/login", json_body=body)
        except ProviderError as exc:
            if exc.kind == "auth":
                raise ProviderError("auth", "TVDB 登录失败，请检查 API Key / PIN") from exc
            raise
        token = (
            (data.get("data") or {}).get("token")
            if isinstance(data, dict)
            else None
        )
        if not token:
            raise ProviderError("auth", "TVDB 登录响应缺少 token")
        exp = _jwt_exp(token)
        if exp is None:
            exp = datetime.now(timezone.utc) + timedelta(days=1)
        # 提前 24h 续期
        stored_exp = exp - timedelta(hours=24)
        self._token = token
        self._token_expires = stored_exp
        with Session(self.engine) as session:
            row = session.get(ProviderToken, "tvdb")
            if row is None:
                row = ProviderToken(
                    provider="tvdb",
                    token=token,
                    expires_at=stored_exp.isoformat(timespec="seconds"),
                    updated_at=utcnow(),
                )
            else:
                row.token = token
                row.expires_at = stored_exp.isoformat(timespec="seconds")
                row.updated_at = utcnow()
            session.add(row)
            session.commit()
        return token

    async def _ensure_token(self, force: bool = False) -> str:
        if force:
            # 如果另一个并发请求刚刚刷新过 token，直接复用，避免 401 风暴时
            # 每个任务都强制重新登录。
            async with self._login_lock:
                if (
                    self._token
                    and self._token_expires
                    and self._token_expires > datetime.now(timezone.utc)
                ):
                    return self._token
                return await self._login_locked(force=True)
        if self._token is None:
            self._load_token()
        if self._token and self._token_expires:
            if self._token_expires <= datetime.now(timezone.utc):
                return await self._login(force=True)
            return self._token
        return await self._login()

    async def _request(
        self,
        method: str,
        path: str,
        params: dict[str, Any] | None = None,
        *,
        tag: str,
        ttl_days: int = 0,
    ) -> dict[str, Any]:
        if self.http is None:
            raise ProviderError("config", "未配置 TVDB API Key")
        if ttl_days:
            key = cache_key("tvdb", tag, path, params, self.language)
            hit = cache_load(self.engine, "tvdb", key)
            if hit is not None:
                return hit
        token = await self._ensure_token()
        try:
            data = await self.http.request(
                method,
                path,
                params=params,
                headers={"Authorization": f"Bearer {token}"},
            )
        except ProviderError as exc:
            if exc.kind != "auth":
                raise
            # 让并发请求知道旧 token 已失效，由第一个拿到锁的请求刷新。
            self._token = None
            self._token_expires = None
            token = await self._ensure_token(force=True)
            data = await self.http.request(
                method,
                path,
                params=params,
                headers={"Authorization": f"Bearer {token}"},
            )
        except Exception:
            raise
        if ttl_days:
            cache_store(self.engine, "tvdb", key, data, ttl_days)  # type: ignore[possibly-undefined]
        return data

    # -- 图片 -------------------------------------------------------------
    async def _artworks(self, provider_id: str, kind: Kind) -> list[dict[str, Any]]:
        path = (
            f"/series/{provider_id}/artworks"
            if kind == "tv"
            else f"/movies/{provider_id}/artworks"
        )
        try:
            data = await self._request(
                "GET", path, {"lang": self.language}, tag=f"art:{path}", ttl_days=30
            )
        except ProviderError:
            try:
                data = await self._request(
                    "GET", path, tag=f"art:{path}:all", ttl_days=30
                )
            except ProviderError:
                return []
        payload = data.get("data")
        if isinstance(payload, dict):
            return payload.get("artworks") or []
        if isinstance(payload, list):
            return payload
        return data.get("artworks") or []

    async def _translations(self, provider_id: str, kind: Kind) -> dict[str, Any]:
        path = (
            f"/series/{provider_id}/translations/{self.language}"
            if kind == "tv"
            else f"/movies/{provider_id}/translations/{self.language}"
        )
        try:
            data = await self._request("GET", path, tag=f"trans:{path}", ttl_days=30)
        except ProviderError:
            return {}
        return _translation(data.get("data", data))

    # -- 接口 -------------------------------------------------------------
    async def search(
        self, *, title: str, year: int | None, kind: Kind
    ) -> list[Candidate]:
        if not title:
            return []
        params = {"query": title, "type": "series" if kind == "tv" else "movie", "limit": 20}
        data = await self._request("GET", "/search", params, tag="search", ttl_days=7)
        rows = data.get("data") or []
        out: list[Candidate] = []
        for item in rows:
            if not isinstance(item, dict):
                continue
            provider_id = item.get("objectID") or item.get("tvdb_id") or item.get("id")
            if not provider_id:
                continue
            translations = item.get("translations") or {}
            translated = _translation(
                translations.get(self.language) if isinstance(translations, dict) else None
            )
            name = (
                translated.get("name")
                or item.get("name")
                or item.get("title")
                or ""
            )
            item_year = _year(item.get("year") or item.get("firstAired") or item.get("first_air_time"))
            out.append(
                Candidate(
                    provider="tvdb",
                    provider_id=str(provider_id),
                    title=name,
                    original_title=item.get("name") or item.get("title"),
                    year=item_year,
                    kind=kind,
                    overview=translated.get("overview") or item.get("overview"),
                    poster_url=item.get("image_url") or item.get("thumbnail"),
                    popularity=float(item.get("score") or 0),
                    aliases=[item.get("name") or ""],
                    raw=item,
                )
            )
        return out

    async def fetch(
        self, provider_id: str, *, kind: Kind, season_type: str | None = None
    ) -> CanonicalMeta:
        stype = season_type or self.season_type or "default"
        if kind == "tv":
            data = await self._request(
                "GET",
                f"/series/{provider_id}/extended",
                {"meta": "translations,episodes"},
                tag=f"series:{provider_id}",
                ttl_days=30,
            )
        else:
            data = await self._request(
                "GET",
                f"/movies/{provider_id}/extended",
                {"meta": "translations"},
                tag=f"movie:{provider_id}",
                ttl_days=30,
            )
        payload = data.get("data") or {}
        if not isinstance(payload, dict) or not payload:
            raise ProviderError("notfound", "TVDB 详情为空")

        translation = await self._translations(provider_id, kind)
        artworks = await self._artworks(provider_id, kind)
        title = (
            translation.get("name")
            or payload.get("name")
            or payload.get("title")
            or ""
        )
        year = _year(payload.get("year") or payload.get("firstAired"))
        aliases = []
        for alias in payload.get("aliases") or []:
            name = alias.get("name") if isinstance(alias, dict) else alias
            if name:
                aliases.append(str(name))

        external: dict[str, str] = {"tvdb": str(provider_id)}
        for remote in payload.get("remoteIds") or []:
            source = str(remote.get("sourceName") or "").lower()
            value = str(remote.get("id") or "")
            if not value:
                continue
            if "themoviedb" in source or source == "tmdb":
                external.setdefault("tmdb", value)
            elif "imdb" in source:
                external.setdefault("imdb", value)

        certification = None
        for rating in payload.get("contentRatings") or []:
            if rating.get("name"):
                certification = rating["name"]
                if str(rating.get("country") or "").upper() in {"USA", "US", "CHN", "CN"}:
                    break

        seasons: list[SeasonSummary] = []
        seen_seasons: set[int] = set()
        for season in payload.get("seasons") or []:
            number = season.get("number")
            if number is None:
                continue
            season_type_name = ((season.get("type") or {}).get("type") or "").lower()
            if stype not in {"default", "official"}:
                if season_type_name and season_type_name not in {stype, "official"}:
                    continue
            number = int(number)
            if number in seen_seasons:
                continue
            seen_seasons.add(number)
            episodes = season.get("episodes") or []
            seasons.append(
                SeasonSummary(
                    season_no=number,
                    name=season.get("name"),
                    episode_count=len(episodes),
                    poster_url=season.get("image"),
                    air_date=season.get("firstAired") or season.get("airDate"),
                )
            )

        genres = [
            (g.get("name") if isinstance(g, dict) else str(g))
            for g in payload.get("genres") or []
        ]
        status_obj = payload.get("status")
        status = (
            status_obj.get("name") if isinstance(status_obj, dict) else status_obj
        )
        runtime = payload.get("averageRuntime") or payload.get("runtime")
        score = payload.get("score")
        collection = None
        if kind == "movie" and payload.get("belongsToCollection"):
            collection = payload["belongsToCollection"]

        return CanonicalMeta(
            provider="tvdb",
            provider_id=str(provider_id),
            kind=kind,
            title=title,
            original_title=payload.get("name") or payload.get("title"),
            aliases=aliases,
            year=year,
            overview=translation.get("overview") or payload.get("overview"),
            tagline=translation.get("tagline") or payload.get("tagline"),
            rating=float(score) if score else None,
            runtime_min=int(runtime) if runtime else None,
            genres=[g for g in genres if g],
            certification=certification,
            status=status,
            cast=[],
            trailer_key=None,
            collection=collection,
            poster_url=pick_artwork(artworks, "poster", self.language),
            backdrop_url=pick_artwork(artworks, "background", self.language),
            logo_url=pick_artwork(artworks, "clearlogo", self.language),
            external_ids=external,
            seasons=seasons,
        )

    async def _episodes(
        self,
        provider_id: str,
        *,
        season: int | None,
        season_type: str | None = None,
    ) -> list[EpisodeMeta]:
        stype = season_type or self.season_type or "default"
        if stype == "official":
            stype = "default"
        out: list[EpisodeMeta] = []
        page = 0
        while page < 50:
            params: dict[str, Any] = {"page": page}
            if season is not None:
                params["season"] = season
            data = await self._request(
                "GET",
                f"/series/{provider_id}/episodes/{stype}",
                params,
                tag=f"eps:{provider_id}:{stype}:{season}",
                ttl_days=30,
            )
            rows = data.get("data") or []
            if not rows:
                break
            for item in rows:
                number = item.get("number")
                if number is None:
                    number = item.get("absoluteNumber")
                if number is None:
                    continue
                out.append(
                    EpisodeMeta(
                        episode_no=int(number),
                        title=item.get("name"),
                        overview=item.get("overview"),
                        runtime_min=int(item["runtime"]) if item.get("runtime") else None,
                        air_date=item.get("aired"),
                        still_url=item.get("image"),
                    )
                )
            links = data.get("links") or {}
            if not links.get("next"):
                break
            page += 1
        return out

    async def fetch_season(
        self, provider_id: str, season_no: int, season_type: str | None = None
    ) -> SeasonDetail:
        episodes = await self._episodes(
            provider_id, season=season_no, season_type=season_type
        )
        return SeasonDetail(season_no=season_no, episodes=episodes)

    async def fetch_absolute(
        self, provider_id: str, season_type: str | None = None
    ) -> SeasonDetail:
        """动漫绝对集号：按 TVDB absolute 顺序返回全部集。"""
        episodes = await self._episodes(
            provider_id, season=None, season_type=season_type or "absolute"
        )
        if not episodes:
            episodes = await self._episodes(
                provider_id, season=None, season_type=season_type or "default"
            )
        if episodes:
            episodes.sort(key=lambda e: e.episode_no)
        return SeasonDetail(season_no=1, episodes=episodes)

    async def health(self) -> ProviderHealth:
        started = time.monotonic()
        if not self.enabled:
            return ProviderHealth(False, "config", "未配置 TVDB API Key")
        try:
            await self._login(force=True)
            return ProviderHealth(
                True, "ok", "TVDB 登录成功", int((time.monotonic() - started) * 1000)
            )
        except ProviderError as exc:
            return ProviderHealth(
                False, exc.kind, exc.message, int((time.monotonic() - started) * 1000)
            )
