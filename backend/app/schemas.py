"""Pydantic 出入参。"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class LoginBody(BaseModel):
    username: str = "admin"
    password: str


class SetupBody(BaseModel):
    password: str
    username: str | None = None


class PasswordBody(BaseModel):
    current_password: str
    new_password: str


class LibraryCreate(BaseModel):
    name: str
    root_path: str
    type: Literal["movie", "tv", "home", "course"] = "movie"
    scan_cron: str | None = None
    provider_priority: list[str] | None = None
    tvdb_season_type: str | None = None
    template: str | None = None
    auto_scrape: bool = True
    enabled: bool = True
    play_headers: dict[str, str] | None = None


class LibraryPatch(BaseModel):
    name: str | None = None
    root_path: str | None = None
    type: Literal["movie", "tv", "home", "course"] | None = None
    scan_cron: str | None = None
    provider_priority: list[str] | None = None
    tvdb_season_type: str | None = None
    template: str | None = None
    auto_scrape: bool | None = None
    enabled: bool | None = None
    play_headers: dict[str, str] | None = None


class ItemPatch(BaseModel):
    title: str | None = None
    original_title: str | None = None
    year: int | None = None
    overview: str | None = None
    tagline: str | None = None
    certification: str | None = None
    collection: dict[str, Any] | None = None
    sort_title: str | None = None


class MatchBody(BaseModel):
    provider: str
    provider_id: str


class ProgressBody(BaseModel):
    position_ms: int = 0
    duration_ms: int | None = None
    finished: bool = False
    client_key: str | None = None


class WatchedBody(BaseModel):
    finished: bool = True


class PlayBody(BaseModel):
    mode: str | None = None
    media_file_id: int | None = None


class ProviderTestBody(BaseModel):
    provider: str


class MergeBody(BaseModel):
    source_id: int


class ImportBody(BaseModel):
    data: dict[str, Any]
    settings: bool = False
