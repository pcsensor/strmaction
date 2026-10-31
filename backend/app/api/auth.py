"""鉴权 API。"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import text
from sqlmodel import Session, select

from .. import __version__
from ..config_store import SettingsService
from ..deps import get_auth, get_settings, get_current_user, get_engine
from ..errors import APIError
from ..models import User
from ..schemas import LoginBody, PasswordBody, SetupBody, CurrentUser
from ..security import SESSION_COOKIE, AuthService

router = APIRouter(prefix="/auth", tags=["auth"])

COOKIE_MAX_AGE = 30 * 24 * 3600


def _client_key(request: Request, username: str) -> str:
    ip = request.client.host if request.client else "unknown"
    return f"{ip}:{username}"


def _set_session_cookie(
    response: Response, request: Request, token: str, expires: datetime
) -> None:
    base_url = ""
    try:
        base_url = request.app.state.app_state.settings.server().get("base_url") or ""
    except Exception:
        base_url = ""
    secure = base_url.startswith("https://") or request.url.scheme == "https"
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=COOKIE_MAX_AGE,
        expires=expires,
        httponly=True,
        samesite="lax",
        secure=secure,
        path="/",
    )


@router.get("/state")
def auth_state(request: Request, auth: AuthService = Depends(get_auth)):
    session_user = auth.validate_session(request.cookies.get(SESSION_COOKIE))
    if session_user:
        request.state.session_user = session_user
    return {
        "needs_setup": auth.needs_setup(),
        "authenticated": bool(session_user),
        "user": session_user.model_dump() if session_user else None,
        "version": __version__,
    }


@router.post("/setup")
def setup(
    body: SetupBody,
    request: Request,
    response: Response,
    auth: AuthService = Depends(get_auth),
    settings: SettingsService = Depends(get_settings),
    engine=Depends(get_engine),
):
    """v0.9: 初次设置，创建第一个管理员账号。"""
    # 快速失败：已完成初始化后，避免未认证请求触发 Argon2 计算。
    if not auth.needs_setup():
        raise APIError(409, "ALREADY_SETUP", "管理员密码已设置")
    problem = auth.check_password_strength(body.password)
    if problem:
        raise APIError(400, "WEAK_PASSWORD", problem)

    username = (body.username or settings.username() or "admin").strip() or "admin"
    # Argon2 开销较大，放到写事务之外，避免首次设置期间长时间持有 SQLite 写锁。
    password_hash = auth.hash_password(body.password)

    with Session(engine) as db:
        # 先拿到 SQLite 写锁，再检查并创建；两个并发首次设置请求会被串行化。
        db.exec(text("BEGIN IMMEDIATE"))
        if not auth.needs_setup(db):
            raise APIError(409, "ALREADY_SETUP", "管理员密码已设置")

        # 查找是否已有账号（如之前存在的占位 admin），有则更新，无则创建
        admin = db.exec(select(User).where(User.username == username)).first()
        if admin:
            admin.password_hash = password_hash
            admin.role = "admin"
            admin.enabled = True
        else:
            admin = User(
                username=username,
                password_hash=password_hash,
                role="admin",
                display_name="管理员",
                enabled=True,
            )
            db.add(admin)
        db.commit()
        db.refresh(admin)

        auth.reset_failures(_client_key(request, username))
        token, expires = auth.create_session(admin)
        _set_session_cookie(response, request, token, expires)

        return {"ok": True, "username": username, "user_id": admin.id}


@router.post("/login")
def login(
    body: LoginBody,
    request: Request,
    response: Response,
    auth: AuthService = Depends(get_auth),
):
    """v0.9: 多用户登录。"""
    if auth.needs_setup():
        raise APIError(428, "SETUP_REQUIRED", "尚未设置管理员密码")

    key = _client_key(request, body.username)
    with auth.login_lock(key):
        if auth.is_locked(key):
            raise APIError(429, "TOO_MANY_ATTEMPTS", "登录失败次数过多，请 5 分钟后再试")
        user = auth.verify_user(body.username, body.password)
        if not user:
            auth._record_failure(key)
            raise APIError(401, "INVALID_CREDENTIALS", "用户名或密码错误")
        auth.reset_failures(key)
    token, expires = auth.create_session(user)
    _set_session_cookie(response, request, token, expires)

    return {
        "ok": True,
        "user": {
            "id": user.id,
            "username": user.username,
            "role": user.role,
            "display_name": user.display_name,
        },
        "expires_at": expires.isoformat(),
    }


@router.post("/logout")
def logout(
    request: Request,
    response: Response,
    auth: AuthService = Depends(get_auth),
):
    auth.revoke_session(request.cookies.get(SESSION_COOKIE))
    response.delete_cookie(SESSION_COOKIE, path="/")
    return {"ok": True}


@router.post("/password")
def change_password(
    body: PasswordBody,
    response: Response,
    request: Request,
    user: CurrentUser = Depends(get_current_user),
    auth: AuthService = Depends(get_auth),
    engine=Depends(get_engine),
):
    """v1.2: 修改当前用户密码（所有登录用户均可修改自己的密码）。"""

    with Session(engine) as db:
        db_user = db.get(User, user.id)
        if not db_user:
            raise APIError(404, "USER_NOT_FOUND", "用户不存在")

        if not auth.verify_password(body.current_password, db_user.password_hash):
            raise APIError(401, "INVALID_CREDENTIALS", "当前密码错误")

        problem = auth.check_password_strength(body.new_password)
        if problem:
            raise APIError(400, "WEAK_PASSWORD", problem)

        db_user.password_hash = auth.hash_password(body.new_password)
        db.add(db_user)
        db.commit()
        db.refresh(db_user)

        # 注销该用户全部会话，再为当前设备创建新会话
        auth.revoke_user_sessions(db_user.id)
        token, expires = auth.create_session(db_user)
        _set_session_cookie(response, request, token, expires)

        return {"ok": True}
