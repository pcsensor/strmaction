"""鉴权 API。"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request, Response

from .. import __version__
from ..config_store import SettingsService
from ..deps import get_auth, get_settings
from ..errors import APIError
from ..schemas import LoginBody, PasswordBody, SetupBody
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
    user = auth.validate_session(request.cookies.get(SESSION_COOKIE))
    if user:
        request.state.user = user
    return {
        "needs_setup": auth.needs_setup(),
        "authenticated": bool(user),
        "username": user,
        "version": __version__,
    }


@router.post("/setup")
def setup(
    body: SetupBody,
    request: Request,
    response: Response,
    auth: AuthService = Depends(get_auth),
    settings: SettingsService = Depends(get_settings),
):
    if not auth.needs_setup():
        raise APIError(409, "ALREADY_SETUP", "管理员密码已设置")
    problem = auth.check_password_strength(body.password)
    if problem:
        raise APIError(400, "WEAK_PASSWORD", problem)
    username = (body.username or settings.username() or "admin").strip() or "admin"
    if username != settings.username():
        settings.update({"auth": {"username": username}})
    auth.set_password(body.password)
    auth.reset_failures(_client_key(request, username))
    token, expires = auth.create_session(username)
    _set_session_cookie(response, request, token, expires)
    return {"ok": True, "username": username}


@router.post("/login")
def login(
    body: LoginBody,
    request: Request,
    response: Response,
    auth: AuthService = Depends(get_auth),
    settings: SettingsService = Depends(get_settings),
):
    if auth.needs_setup():
        raise APIError(428, "SETUP_REQUIRED", "尚未设置管理员密码")
    key = _client_key(request, body.username)
    if auth.is_locked(key):
        raise APIError(429, "TOO_MANY_ATTEMPTS", "登录失败次数过多，请 5 分钟后再试")
    if body.username != settings.username() or not auth.verify_password(body.password):
        auth._record_failure(key)
        raise APIError(401, "INVALID_CREDENTIALS", "用户名或密码错误")
    auth.reset_failures(key)
    if not auth.settings.password_hash().startswith("$argon2"):
        # config.yaml 中填写明文密码时，首次成功登录后升级为 argon2
        auth.set_password(body.password)
    token, expires = auth.create_session(body.username)
    _set_session_cookie(response, request, token, expires)
    return {"ok": True, "username": body.username, "expires_at": expires.isoformat()}


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
    auth: AuthService = Depends(get_auth),
    settings: SettingsService = Depends(get_settings),
):
    if not auth.verify_password(body.current_password):
        raise APIError(401, "INVALID_CREDENTIALS", "当前密码错误")
    problem = auth.check_password_strength(body.new_password)
    if problem:
        raise APIError(400, "WEAK_PASSWORD", problem)
    auth.set_password(body.new_password)
    auth.revoke_session(request.cookies.get(SESSION_COOKIE))
    token, expires = auth.create_session(settings.username())
    _set_session_cookie(response, request, token, expires)
    return {"ok": True}
