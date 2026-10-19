"""元数据 Provider 接口与统一数据结构（附录 D.1）。"""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

import httpx

Kind = Literal["movie", "tv"]


class ProviderError(Exception):
    """按附录 D.9 分类的 provider 错误。"""

    def __init__(self, kind: str, message: str, status: int | None = None):
        super().__init__(message)
        self.kind = kind  # auth | rate | network | notfound | parse | config
        self.message = message
        self.status = status


@dataclass
class CastMember:
    name: str
    role: str | None = None
    avatar_url: str | None = None
    avatar: str | None = None  # 本地 sha1
    kind: str = "cast"  # cast | director | writer


@dataclass
class SeasonSummary:
    season_no: int
    name: str | None = None
    episode_count: int = 0
    poster_url: str | None = None
    air_date: str | None = None


@dataclass
class EpisodeMeta:
    episode_no: int
    title: str | None = None
    overview: str | None = None
    runtime_min: int | None = None
    air_date: str | None = None
    still_url: str | None = None


@dataclass
class SeasonDetail:
    season_no: int
    episodes: list[EpisodeMeta] = field(default_factory=list)


@dataclass
class Candidate:
    provider: str
    provider_id: str
    title: str
    original_title: str | None
    year: int | None
    kind: Kind
    overview: str | None = None
    poster_url: str | None = None
    popularity: float = 0.0
    aliases: list[str] = field(default_factory=list)
    raw: dict = field(default_factory=dict)


@dataclass
class CanonicalMeta:
    provider: str
    provider_id: str
    kind: Kind
    title: str
    original_title: str | None = None
    aliases: list[str] = field(default_factory=list)
    year: int | None = None
    overview: str | None = None
    tagline: str | None = None
    rating: float | None = None
    runtime_min: int | None = None
    genres: list[str] = field(default_factory=list)
    certification: str | None = None
    status: str | None = None
    cast: list[CastMember] = field(default_factory=list)
    trailer_key: str | None = None
    collection: dict | None = None
    poster_url: str | None = None
    backdrop_url: str | None = None
    logo_url: str | None = None
    external_ids: dict[str, str] = field(default_factory=dict)
    seasons: list[SeasonSummary] = field(default_factory=list)

    def payload(self) -> dict[str, Any]:
        """用于 meta_hash 的稳定 payload。"""
        return {
            "provider": self.provider,
            "provider_id": self.provider_id,
            "kind": self.kind,
            "title": self.title,
            "original_title": self.original_title,
            "aliases": self.aliases,
            "year": self.year,
            "overview": self.overview,
            "tagline": self.tagline,
            "rating": self.rating,
            "runtime_min": self.runtime_min,
            "genres": self.genres,
            "certification": self.certification,
            "status": self.status,
            "cast": [c.name for c in self.cast],
            "trailer_key": self.trailer_key,
            "collection": self.collection,
            "poster_url": self.poster_url,
            "backdrop_url": self.backdrop_url,
            "logo_url": self.logo_url,
            "external_ids": self.external_ids,
            "seasons": [s.__dict__ for s in self.seasons],
        }

    def meta_hash(self) -> str:
        raw = json.dumps(self.payload(), ensure_ascii=False, sort_keys=True)
        return hashlib.sha1(raw.encode("utf-8")).hexdigest()


@dataclass
class ProviderHealth:
    ok: bool
    status: str = "ok"  # ok | auth | network | config | rate
    message: str = ""
    latency_ms: int = 0


class MetadataProvider(Protocol):
    name: str
    supports: set[Kind]

    async def search(self, *, title: str, year: int | None, kind: Kind) -> list[Candidate]: ...

    async def fetch(self, provider_id: str, *, kind: Kind) -> CanonicalMeta: ...

    async def fetch_season(self, provider_id: str, season_no: int) -> SeasonDetail: ...

    async def health(self) -> ProviderHealth: ...


# ---------------------------------------------------------------------------
# 限流
# ---------------------------------------------------------------------------


class TokenBucket:
    """按 provider 独立的异步令牌桶。"""

    def __init__(self, rate_per_second: float, burst: float | None = None):
        self.rate = max(float(rate_per_second or 1), 0.1)
        self.capacity = max(float(burst or self.rate), 1.0)
        self.tokens = self.capacity
        self.updated = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        async with self._lock:
            now = time.monotonic()
            self.tokens = min(
                self.capacity, self.tokens + (now - self.updated) * self.rate
            )
            self.updated = now
            if self.tokens < 1:
                wait = (1 - self.tokens) / self.rate
                await asyncio.sleep(wait)
                self.tokens = 0
                self.updated = time.monotonic()
            else:
                self.tokens -= 1


# ---------------------------------------------------------------------------
# HTTP 客户端
# ---------------------------------------------------------------------------


class ProviderHTTP:
    def __init__(
        self,
        *,
        base_url: str,
        provider: str,
        proxy: str = "",
        rate_limit: float = 4,
        timeout: float = 20,
        headers: dict[str, str] | None = None,
    ):
        self.base_url = (base_url or "").rstrip("/")
        self.provider = provider
        self.bucket = TokenBucket(rate_limit)
        client_kwargs: dict[str, Any] = {
            "timeout": httpx.Timeout(timeout, connect=10),
            "follow_redirects": True,
            "headers": {
                "User-Agent": "StrmAction/1.0 (+https://github.com/strmaction)",
                **(headers or {}),
            },
        }
        if proxy:
            client_kwargs["proxy"] = proxy
        self.client = httpx.AsyncClient(**client_kwargs)

    async def close(self) -> None:
        await self.client.aclose()

    def _url(self, path: str) -> str:
        if path.startswith("http://") or path.startswith("https://"):
            return path
        return f"{self.base_url}/{path.lstrip('/')}"

    async def request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        url = self._url(path)
        last_error: ProviderError | None = None
        delays = [1, 4, 16]
        for attempt in range(3):
            await self.bucket.acquire()
            try:
                response = await self.client.request(
                    method, url, params=params, json=json_body, headers=headers
                )
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                last_error = ProviderError("network", f"网络错误: {exc}")
                if attempt < 2:
                    await asyncio.sleep(delays[attempt])
                    continue
                raise last_error

            if response.status_code in {401, 403}:
                raise ProviderError("auth", f"鉴权失败 ({response.status_code})", response.status_code)
            if response.status_code == 404:
                raise ProviderError("notfound", "资源不存在 (404)", 404)
            if response.status_code == 429:
                retry_after = response.headers.get("Retry-After")
                try:
                    wait = float(retry_after) if retry_after else delays[attempt]
                except ValueError:
                    wait = delays[attempt]
                last_error = ProviderError("rate", "触发限流 (429)", 429)
                if attempt < 2:
                    await asyncio.sleep(max(wait, 1))
                    continue
                raise last_error
            if response.status_code >= 500:
                last_error = ProviderError(
                    "network", f"上游错误 ({response.status_code})", response.status_code
                )
                if attempt < 2:
                    await asyncio.sleep(delays[attempt])
                    continue
                raise last_error
            if response.status_code >= 400:
                raise ProviderError(
                    "parse",
                    f"请求失败 ({response.status_code}): {response.text[:200]}",
                    response.status_code,
                )
            if not response.content:
                return {}
            try:
                data = response.json()
            except ValueError as exc:
                raise ProviderError("parse", f"JSON 解析失败: {exc}") from exc
            if not isinstance(data, dict):
                return {"data": data}
            return data
        raise last_error or ProviderError("network", "未知网络错误")
