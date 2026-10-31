"""FastAPI 依赖：从 app.state 取服务实例。"""

from __future__ import annotations

from fastapi import Depends, Request
from sqlmodel import Session, select

from .config import ConfigManager
from .config_store import SettingsService
from .db import Database
from .errors import APIError
from .images import ImageService
from .jobs import SchedulerService, TaskManager
from .models import Library, User, UserLibraryAccess
from .schemas import CurrentUser
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


def current_user_legacy(request: Request) -> str | None:
    """遗留方法：返回用户名。v0.9 后建议使用 get_current_user。"""
    return getattr(request.state, "user", None)


def get_current_user(request: Request) -> CurrentUser:
    """v0.9 多用户鉴权：从 session 获取当前用户信息。"""
    state = get_state(request)
    session_user = getattr(request.state, "session_user", None)

    if not session_user:
        raise APIError(401, "UNAUTHORIZED", "请先登录")

    # session_user 是从 security.py 中间件设置的
    return session_user


def require_admin(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
    """要求管理员权限。"""
    if user.role != "admin":
        raise APIError(403, "FORBIDDEN", "需要管理员权限")
    return user


def get_accessible_library_ids(
    user: CurrentUser, engine, *, include_disabled: bool = False
) -> list[int] | None:
    """
    获取用户可访问的媒体库 ID 列表。

    返回：
    - None: 仅当管理员且 include_disabled=True，表示包含禁用库在内的全部库
    - list[int]: 用户可见/可访问的库 ID 列表
    """
    with Session(engine) as db:
        if user.role == "admin":
            if include_disabled:
                return None
            return list(
                db.exec(select(Library.id).where(Library.enabled == True)).all()  # noqa: E712
            )

        query = (
            select(UserLibraryAccess.library_id)
            .join(Library, Library.id == UserLibraryAccess.library_id)
            .where(UserLibraryAccess.user_id == user.id)
        )
        if not include_disabled:
            query = query.where(Library.enabled == True)  # noqa: E712
        return list(db.exec(query).all())


def authorize_item_access(request: Request, item_id: int) -> CurrentUser | None:
    """
    Cookie 会话或 play_token 二选一；都不可用时返回 401/403（§12.7）。

    v0.9: 返回 CurrentUser 对象，用于后续权限检查。
    """
    # 优先使用 Cookie 会话
    session_user = getattr(request.state, "session_user", None)
    if session_user:
        return session_user

    # 降级使用 play_token（原生播放器）
    token = getattr(request.state, "play_token", None)
    if not token:
        raise APIError(401, "UNAUTHORIZED", "请先登录")

    state = request.app.state.app_state
    result = state.auth.validate_play_token(token, item_id)

    if result == "ok":
        # 从 play_token 获取 user_id，构造 CurrentUser
        token_user = state.auth.get_user_from_play_token(token)
        return token_user

    if result == "expired":
        raise APIError(401, "PLAY_TOKEN_EXPIRED", "播放凭证已过期，请回到列表重新播放")
    if result == "mismatch":
        raise APIError(403, "PLAY_TOKEN_MISMATCH", "播放凭证与条目不匹配")
    raise APIError(401, "PLAY_TOKEN_INVALID", "播放凭证无效，请回到列表重新播放")
