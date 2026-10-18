"""FastAPI 依赖：从 app.state 取服务实例。"""

from __future__ import annotations

from fastapi import Request

from .config import ConfigManager
from .config_store import SettingsService
from .db import Database
from .errors import APIError
from .images import ImageService
from .jobs import SchedulerService, TaskManager
from .security import AuthService


class AppState:
    def __init__(
        self,
        config: ConfigManager,
        db: Database,
        settings: SettingsService,
        auth: AuthService,
        images: ImageService,
        tasks: TaskManager,
        scheduler: SchedulerService,
    ):
        self.config = config
        self.db = db
        self.settings = settings
        self.auth = auth
        self.images = images
        self.tasks = tasks
        self.scheduler = scheduler

    @property
    def engine(self):
        return self.db.engine


def get_state(request: Request) -> AppState:
    return request.app.state.app_state


def get_settings(request: Request) -> SettingsService:
    return get_state(request).settings


def get_db(request: Request) -> Database:
    return get_state(request).db


def get_engine(request: Request):
    return get_state(request).db.engine


def get_auth(request: Request) -> AuthService:
    return get_state(request).auth


def get_images(request: Request) -> ImageService:
    return get_state(request).images


def get_tasks(request: Request) -> TaskManager:
    return get_state(request).tasks


def get_scheduler(request: Request) -> SchedulerService:
    return get_state(request).scheduler


def current_user(request: Request) -> str | None:
    return getattr(request.state, "user", None)


def authorize_item_access(request: Request, item_id: int) -> None:
    """Cookie 会话或 play_token 二选一；都不可用时返回 401/403（§12.7）。"""
    if getattr(request.state, "user", None):
        return
    token = getattr(request.state, "play_token", None)
    if not token:
        raise APIError(401, "UNAUTHORIZED", "请先登录")
    state = request.app.state.app_state
    result = state.auth.validate_play_token(token, item_id)
    if result == "ok":
        return
    if result == "expired":
        raise APIError(401, "PLAY_TOKEN_EXPIRED", "播放凭证已过期，请回到列表重新播放")
    if result == "mismatch":
        raise APIError(403, "PLAY_TOKEN_MISMATCH", "播放凭证与条目不匹配")
    raise APIError(401, "PLAY_TOKEN_INVALID", "播放凭证无效，请回到列表重新播放")
