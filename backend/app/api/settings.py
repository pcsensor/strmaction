"""设置 API（v1.2）。

- 全局设置 / Provider 测试：仅管理员；
- 个人播放偏好：所有登录用户；
- 关于信息：所有登录用户（数据目录仅管理员可见）。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends, Request

from .. import __version__
from ..config_store import SettingsService
from ..deps import (
    get_current_user,
    get_engine,
    get_scheduler,
    get_settings,
    require_admin,
)
from ..errors import APIError
from ..jobs import SchedulerService
from ..players import PlayContext, clean_headers
from ..players.cache import normalize_cache_limit
from ..preferences import (
    allowed_player_modes,
    available_player_modes,
    defaults_summary,
    effective_player,
    effective_summary,
    get_preference,
    preference_payload,
    save_preference,
)
from ..schemas import CurrentUser, PlayerPreferencePatch, ProviderTestBody
from ..scraper.service import ProviderRegistry

router = APIRouter(tags=["settings"])

PRIORITY_KEYS = {"movie", "tv", "home", "course"}
PROVIDERS = {"tmdb", "tvdb"}
PLAYER_MODES = {"builtin", "external_mpv", "browser_intent", "desktop_mpv", "copy", "auto"}


def _validate(patch: dict[str, Any]) -> None:
    scraper = patch.get("scraper") or {}
    priority = scraper.get("provider_priority")
    if priority is not None:
        if not isinstance(priority, dict):
            raise APIError(400, "INVALID_SETTINGS", "provider_priority 必须是对象")
        for key, value in priority.items():
            if key not in PRIORITY_KEYS:
                raise APIError(400, "INVALID_SETTINGS", f"未知的库类型: {key}")
            if not isinstance(value, list) or any(v not in PROVIDERS for v in value):
                raise APIError(400, "INVALID_SETTINGS", f"{key} 的源优先级不合法")
    tvdb = scraper.get("tvdb") or {}
    if "season_type" in tvdb and tvdb["season_type"] not in {"default", "absolute", "dvd"}:
        raise APIError(400, "INVALID_SETTINGS", "TVDB season_type 不合法")
    player = patch.get("player") or {}
    for key in ("default", "mode"):
        if key in player and player[key] not in PLAYER_MODES:
            raise APIError(400, "INVALID_SETTINGS", "默认播放器不合法")
    if "play_headers" in player and not isinstance(player["play_headers"], dict):
        raise APIError(400, "INVALID_SETTINGS", "play_headers 必须是对象")
    auth = patch.get("auth") or {}
    if "password_hash" in auth:
        raise APIError(400, "INVALID_SETTINGS", "请使用修改密码接口")


def _sanitize(patch: dict[str, Any]) -> dict[str, Any]:
    """清洗播放器相关字段，避免把非法的请求头/间隔写进配置。"""
    player = patch.get("player")
    if isinstance(player, dict):
        if "play_headers" in player:
            player["play_headers"] = clean_headers(player.get("play_headers") or {})
        if "progress_interval_ms" in player:
            try:
                interval = int(player["progress_interval_ms"])
            except (TypeError, ValueError):
                interval = 5000
            player["progress_interval_ms"] = min(max(interval, 2000), 60000)
        if "play_token_ttl_hours" in player:
            try:
                hours = int(player["play_token_ttl_hours"])
            except (TypeError, ValueError):
                hours = 12
            player["play_token_ttl_hours"] = min(max(hours, 1), 72)
        if "cache_limit_mb" in player:
            # 0 表示最小预读；伴侣 App 最低按 16MB 执行。
            player["cache_limit_mb"] = normalize_cache_limit(player["cache_limit_mb"])
        if "mode" in player:
            player.pop("default", None)
    return patch


def _payload(settings: SettingsService) -> dict[str, Any]:
    return {
        "settings": settings.public(),
        "data_dir": str(settings.data_dir),
        "version": __version__,
    }


def _client_flags(request: Request) -> tuple[PlayContext, dict[str, bool]]:
    user_agent = request.headers.get("user-agent", "")
    is_companion = (
        "StrmActionCompanion" in user_agent
        or request.headers.get("x-strmaction-companion") is not None
    )
    is_android = "Android" in user_agent
    context = PlayContext(
        user_agent=user_agent,
        is_android=is_android,
        is_companion=is_companion,
        client_ip=request.client.host if request.client else "",
    )
    return context, {
        "is_companion": is_companion,
        "is_android": is_android,
        "is_browser": not is_companion,
    }


def _player_preference_payload(
    settings: SettingsService,
    engine,
    user: CurrentUser,
    request: Request,
) -> dict[str, Any]:
    allow_desktop_mpv = user.role == "admin"
    pref = get_preference(engine, user.id)
    context, client = _client_flags(request)
    # 延迟导入，避免 api 包初始化时的循环依赖。
    from .play import resolve_mode

    resolved_mode = resolve_mode(
        None,
        context,
        settings,
        engine,
        player=effective_player(settings, pref),
        allow_server_mpv=allow_desktop_mpv,
    )
    return {
        "overrides": preference_payload(pref, allow_desktop_mpv),
        "defaults": defaults_summary(settings, allow_desktop_mpv),
        "effective": effective_summary(settings, pref, allow_desktop_mpv),
        "allowed_modes": allowed_player_modes(allow_desktop_mpv),
        "available_modes": available_player_modes(
            allow_desktop_mpv, client["is_companion"], client["is_android"]
        ),
        "client": client,
        "resolved_mode": resolved_mode,
    }


@router.get("/settings")
def get_settings_api(
    _admin: CurrentUser = Depends(require_admin),
    settings: SettingsService = Depends(get_settings),
):
    return _payload(settings)


@router.get("/me/player")
def get_my_player(
    request: Request,
    user: CurrentUser = Depends(get_current_user),
    engine=Depends(get_engine),
    settings: SettingsService = Depends(get_settings),
):
    """当前用户的播放偏好；未设置时回落到全局默认。"""
    return _player_preference_payload(settings, engine, user, request)


@router.patch("/me/player")
def patch_my_player(
    body: PlayerPreferencePatch,
    request: Request,
    user: CurrentUser = Depends(get_current_user),
    engine=Depends(get_engine),
    settings: SettingsService = Depends(get_settings),
):
    """只允许修改 mode / fallback_on_error；显式 null 表示恢复跟随全局。"""
    if body.mode == "desktop_mpv" and user.role != "admin":
        raise APIError(403, "FORBIDDEN", "服务器桌面 mpv 仅管理员可用")
    save_preference(engine, user.id, body.model_dump(exclude_unset=True))
    return _player_preference_payload(settings, engine, user, request)


@router.get("/about")
def about(
    user: CurrentUser = Depends(get_current_user),
    settings: SettingsService = Depends(get_settings),
):
    """应用信息：所有登录用户可见；数据目录仅管理员可见。"""
    return {
        "app": "StrmAction",
        "version": __version__,
        "api_docs": "/docs",
        "data_dir": str(settings.data_dir) if user.role == "admin" else None,
    }


@router.patch("/settings")
def patch_settings(
    patch: dict[str, Any] = Body(...),
    _admin: CurrentUser = Depends(require_admin),
    settings: SettingsService = Depends(get_settings),
    scheduler: SchedulerService = Depends(get_scheduler),
):
    if not isinstance(patch, dict):
        raise APIError(400, "INVALID_SETTINGS", "设置必须是对象")
    _validate(patch)
    cleaned = {k: v for k, v in patch.items() if k in {"server", "auth", "scraper", "scanner", "player", "ui"}}
    settings.update(_sanitize(cleaned))
    scheduler.reload()
    return _payload(settings)


@router.post("/settings/provider-test")
async def provider_test(
    body: ProviderTestBody,
    _admin: CurrentUser = Depends(require_admin),
    settings: SettingsService = Depends(get_settings),
    engine=Depends(get_engine),
):
    if body.provider not in PROVIDERS:
        raise APIError(400, "INVALID_PROVIDER", "provider 只能是 tmdb / tvdb")
    registry = ProviderRegistry(settings)
    provider = registry.get(body.provider)
    try:
        if provider is None:
            raise APIError(400, "INVALID_PROVIDER", "未知的 provider")
        health = await provider.health()
        return {
            "provider": body.provider,
            "ok": health.ok,
            "status": health.status,
            "message": health.message,
            "latency_ms": health.latency_ms,
        }
    finally:
        await registry.close()
