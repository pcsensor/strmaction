"""Pydantic 出入参。"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


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


class PlayerPreferencePatch(BaseModel):
    """v1.2 用户播放偏好。字段为 None 表示清除覆盖、跟随全局。"""

    model_config = ConfigDict(extra="forbid")

    mode: Literal[
        "builtin", "external_mpv", "browser_intent", "desktop_mpv", "copy", "auto"
    ] | None = None
    fallback_on_error: bool | None = None


class ProviderTestBody(BaseModel):
    provider: str


class MergeBody(BaseModel):
    source_id: int


class ImportBody(BaseModel):
    data: dict[str, Any]
    settings: bool = False


# v0.9 多用户体系
class UserCreate(BaseModel):
    username: str = Field(min_length=3, max_length=50)
    password: str = Field(min_length=8)
    display_name: str | None = None
    role: Literal["admin", "user"] = "user"
    library_ids: list[int] = Field(default_factory=list)


class UserPatch(BaseModel):
    password: str | None = Field(default=None, min_length=8)
    display_name: str | None = None
    enabled: bool | None = None
    role: Literal["admin", "user"] | None = None


class UserLibrariesUpdate(BaseModel):
    library_ids: list[int]


class UserOut(BaseModel):
    id: int
    username: str
    display_name: str | None
    role: str
    enabled: bool
    library_count: int | None = None
    last_login_at: str | None = None
    created_at: str
    updated_at: str


class UserDetail(BaseModel):
    id: int
    username: str
    display_name: str | None
    role: str
    enabled: bool
    libraries: list[dict[str, Any]]
    last_login_at: str | None = None
    created_at: str
    updated_at: str
    created_by: int | None = None


class CurrentUser(BaseModel):
    id: int
    username: str
    role: str
    display_name: str | None
