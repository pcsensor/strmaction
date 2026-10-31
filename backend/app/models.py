"""SQLModel 表定义。

字段与开发文档 §7 等价，另有少量扩展字段（以注释标明）：
- item.deleted_at / item.parse_confidence / item.parse_payload / item.air_date
- media_file.invalid / missing_count / version / labels / part
- play_progress.last_client_key（进度回传幂等）
- setting（设置页持久化，优先于 config.yaml）
"""

from __future__ import annotations

from datetime import datetime, timezone
import json

from sqlmodel import Field, SQLModel


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Library(SQLModel, table=True):
    __tablename__ = "library"

    id: int | None = Field(default=None, primary_key=True)
    name: str
    root_path: str = Field(index=True)
    type: str = "movie"  # movie | tv | home | course
    provider: str = "tmdb"
    language: str = "zh-CN"
    scan_cron: str | None = None
    enabled: bool = True
    created_at: str = Field(default_factory=utcnow)
    last_scan_at: str | None = None
    # 扩展：库级覆盖
    provider_priority: str | None = None  # JSON array，如 ["tvdb","tmdb"]
    tvdb_season_type: str | None = None  # default | absolute | dvd
    template: str | None = None  # 目录模板
    auto_scrape: bool = True
    play_headers: str | None = None  # JSON object：该库播放时下发给播放器的请求头（v0.8）


class Item(SQLModel, table=True):
    __tablename__ = "item"

    id: int | None = Field(default=None, primary_key=True)
    library_id: int = Field(foreign_key="library.id", index=True)
    parent_id: int | None = Field(default=None, foreign_key="item.id", index=True)
    kind: str = "movie"  # movie | series | season | episode | video | folder
    title: str = ""
    original_title: str | None = None
    sort_title: str | None = None
    year: int | None = None
    season_no: int | None = None
    episode_no: int | None = None
    overview: str | None = None
    tagline: str | None = None
    runtime_min: int | None = None
    rating: float | None = None
    provider: str | None = None
    provider_id: str | None = None
    external_ids: str | None = None  # JSON
    genres: str | None = None  # JSON array
    cast: str | None = None  # JSON array
    certification: str | None = None
    alt_titles: str | None = None  # JSON array
    trailer_key: str | None = None
    collection: str | None = None  # JSON
    poster_path: str | None = None  # 图片 sha1
    backdrop_path: str | None = None
    logo_path: str | None = None
    still_path: str | None = None
    color_primary: str | None = None
    locked_fields: str | None = None  # JSON array
    meta_hash: str | None = None
    match_state: str = "pending"  # pending | auto | manual | failed | skipped
    status: str | None = None  # Returning / Ended
    air_date: str | None = None
    created_at: str = Field(default_factory=utcnow)
    updated_at: str = Field(default_factory=utcnow)
    # 扩展
    deleted_at: str | None = None
    parse_confidence: float | None = None
    parse_payload: str | None = None  # JSON: 解析结果，便于重刮

    def get_locked_fields(self) -> set[str]:
        if not self.locked_fields:
            return set()
        try:
            val = json.loads(self.locked_fields)
            return set(val) if isinstance(val, list) else set()
        except (json.JSONDecodeError, TypeError):
            return set()

    def set_locked_fields(self, fields: list[str] | set[str] | None) -> None:
        if not fields:
            self.locked_fields = None
        else:
            self.locked_fields = json.dumps(sorted(list(fields)), ensure_ascii=False)

    def is_field_locked(self, field: str) -> bool:
        return field in self.get_locked_fields()


class MediaFile(SQLModel, table=True):
    __tablename__ = "media_file"

    id: int | None = Field(default=None, primary_key=True)
    item_id: int = Field(foreign_key="item.id", index=True)
    library_id: int = Field(index=True)
    rel_path: str
    abs_path: str = Field(unique=True, index=True)
    url: str = ""
    size_bytes: int | None = None
    mtime: int | None = None
    missing: bool = False
    created_at: str = Field(default_factory=utcnow)
    # 扩展
    invalid: bool = False
    missing_count: int = 0
    version: str | None = None
    part: int | None = None
    labels: str | None = None  # JSON array


class PlayProgress(SQLModel, table=True):
    __tablename__ = "play_progress"

    id: int | None = Field(default=None, primary_key=True)
    user_id: int | None = Field(default=None, foreign_key="user.id", index=True)
    item_id: int = Field(foreign_key="item.id", index=True)
    position_ms: int = 0
    duration_ms: int | None = None
    finished: bool = False
    dismissed: bool = False
    updated_at: str = Field(default_factory=utcnow)
    last_client_key: str | None = None
    revision: int = 0
    client_session: str | None = None
    client_sequence: int = 0


class PlaySession(SQLModel, table=True):
    __tablename__ = "play_session"

    token: str = Field(primary_key=True)
    item_id: int
    created_at: str = Field(default_factory=utcnow)
    expires_at: str
    consumed: bool = False


class PlayToken(SQLModel, table=True):
    """v0.8 播放凭证：item 级、限时、只能写该条目进度（§12.7）。v0.9 新增 user_id。"""

    __tablename__ = "play_token"

    token: str = Field(primary_key=True)
    user_id: int | None = Field(default=None, foreign_key="user.id", index=True)
    item_id: int = Field(foreign_key="item.id", index=True)
    created_at: str = Field(default_factory=utcnow)
    expires_at: str
    revoked: bool = False


class TaskLog(SQLModel, table=True):
    __tablename__ = "task_log"

    id: int | None = Field(default=None, primary_key=True)
    kind: str = "scan"  # scan | scrape | image | refresh
    library_id: int | None = None
    status: str = "running"  # running | success | failed
    message: str | None = None
    stats: str | None = None  # JSON
    started_at: str = Field(default_factory=utcnow)
    finished_at: str | None = None


class ScrapeCache(SQLModel, table=True):
    __tablename__ = "scrape_cache"

    id: int | None = Field(default=None, primary_key=True)
    provider: str
    query_hash: str = Field(index=True)
    payload: str
    expires_at: str


class ProviderToken(SQLModel, table=True):
    __tablename__ = "provider_token"

    provider: str = Field(primary_key=True)
    token: str
    expires_at: str | None = None
    updated_at: str = Field(default_factory=utcnow)


class ImageTask(SQLModel, table=True):
    __tablename__ = "image_task"

    id: int | None = Field(default=None, primary_key=True)
    item_id: int = Field(foreign_key="item.id", index=True)
    kind: str = "poster"  # poster | backdrop | logo | still | avatar
    remote_url: str = ""
    status: str = "pending"  # pending | downloading | done | failed | broken
    retry: int = 0
    error: str | None = None
    updated_at: str = Field(default_factory=utcnow)
    # 扩展：下载结果的 sha1，便于复用
    sha: str | None = None
    target_field: str | None = None  # 回调写入 item 的字段


class Setting(SQLModel, table=True):
    __tablename__ = "setting"

    key: str = Field(primary_key=True)
    value: str = ""
    updated_at: str = Field(default_factory=utcnow)


class User(SQLModel, table=True):
    """v0.9 多用户体系：管理员 + 普通用户。"""

    __tablename__ = "user"

    id: int | None = Field(default=None, primary_key=True)
    username: str = Field(unique=True, index=True)
    password_hash: str
    role: str = "user"  # admin | user
    display_name: str | None = None
    enabled: bool = True
    created_at: str = Field(default_factory=utcnow)
    updated_at: str = Field(default_factory=utcnow)
    last_login_at: str | None = None
    created_by: int | None = Field(default=None, foreign_key="user.id")


class UserPreference(SQLModel, table=True):
    """v1.2 用户级偏好：播放方式等。NULL 表示跟随全局默认。"""

    __tablename__ = "user_preference"

    user_id: int = Field(foreign_key="user.id", primary_key=True)
    player_mode: str | None = None
    fallback_on_error: bool | None = None
    updated_at: str = Field(default_factory=utcnow)


class UserLibraryAccess(SQLModel, table=True):
    """用户-媒体库授权关系。管理员无需此表记录（自动拥有全部库）。"""

    __tablename__ = "user_library_access"

    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.id", index=True)
    library_id: int = Field(foreign_key="library.id", index=True)
    created_at: str = Field(default_factory=utcnow)


class Session(SQLModel, table=True):
    """登录会话（支持服务端登出/吊销）。v0.9 新增 user_id / role。"""

    __tablename__ = "session"

    jti: str = Field(primary_key=True)
    user_id: int | None = Field(default=None, foreign_key="user.id", index=True)
    username: str
    role: str = "user"  # admin | user
    created_at: str = Field(default_factory=utcnow)
    expires_at: str
