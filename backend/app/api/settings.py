"""设置 API（v1.2）。

- 全局设置 / Provider 测试：仅管理员；
- 个人播放偏好：所有登录用户；
- 关于信息：所有登录用户（数据目录仅管理员可见）。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends, Request

from .. import __version__
from ..config import is_masked
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
# v1.3：服务端 mpv / 外部 mpv 已下线，设置里只保留这些模式。
PLAYER_MODES = {"builtin", "copy"}


def _validate(patch: dict[str, Any]) -> None:
    for key in ("server", "auth", "scraper", "scanner", "player", "ui"):
        if key in patch and not isinstance(patch[key], dict):
            raise APIError(400, "INVALID_SETTINGS", f"{key} 必须是对象")
    server = patch.get("server") or {}
    if isinstance(server, dict):
        for key in ("data_dir", "port"):
            if key in server:
                raise APIError(
                    400,
                    "INVALID_SETTINGS",
                    "服务器数据目录和端口不能通过设置接口修改，请使用环境变量或配置文件",
                )
    scanner = patch.get("scanner") or {}
    if isinstance(scanner, dict):
        if "max_depth" in scanner:
            try:
                depth = int(scanner["max_depth"])
            except (TypeError, ValueError):
                raise APIError(400, "INVALID_SETTINGS", "scanner.max_depth 必须是整数")
            if depth < 1 or depth > 64:
                raise APIError(400, "INVALID_SETTINGS", "scanner.max_depth 必须在 1 到 64 之间")
        if "ignore" in scanner and not (
            isinstance(scanner["ignore"], list)
            and all(isinstance(item, str) for item in scanner["ignore"])
        ):
            raise APIError(400, "INVALID_SETTINGS", "scanner.ignore 必须是字符串数组")
        if "follow_symlinks" in scanner and not isinstance(scanner["follow_symlinks"], bool):
            raise APIError(400, "INVALID_SETTINGS", "scanner.follow_symlinks 必须是布尔值")
    scraper = patch.get("scraper") or {}
    for provider in ("tmdb", "tvdb"):
        if provider in scraper and not isinstance(scraper[provider], dict):
            raise APIError(400, "INVALID_SETTINGS", f"scraper.{provider} 必须是对象")
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
    """清洗播放器/扫描器字段，避免把非法值写进配置。"""
    server = patch.get("server")
    if isinstance(server, dict):
        # 防御旧备份或旧客户端回写不可变字段。
        server.pop("data_dir", None)
        server.pop("port", None)
    auth = patch.get("auth")
    if isinstance(auth, dict):
        password_hash = auth.get("password_hash")
        if password_hash is not None and (not password_hash or is_masked(password_hash)):
            auth.pop("password_hash", None)
    scanner = patch.get("scanner")
    if isinstance(scanner, dict):
        if "max_depth" in scanner:
            try:
                scanner["max_depth"] = min(max(int(scanner["max_depth"]), 1), 64)
            except (TypeError, ValueError):
                scanner.pop("max_depth", None)
        if "ignore" in scanner:
            scanner["ignore"] = [
                str(item).strip()
                for item in scanner.get("ignore") or []
                if isinstance(item, str) and str(item).strip()
            ]
        if "follow_symlinks" in scanner:
            scanner["follow_symlinks"] = bool(scanner["follow_symlinks"])
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
        for key, maximum in (("buffer_limit_mb", 8192), ("disk_cache_limit_mb", 32768)):
            if key in player and player[key] is not None:
                try:
                    player[key] = min(max(0, int(player[key])), maximum)
                except (TypeError, ValueError):
                    raise APIError(400, "INVALID_SETTINGS", f"{key} 必须是容量或 null")
        if "mode" in player:
            player.pop("default", None)
        # 已下线的播放器字段：直接丢弃，避免旧客户端写回。
        for key in ("mpv_path", "mpv_extra_args", "mpv_package", "enable_progress", "fallback_on_error"):
            player.pop(key, None)
    return patch


# 供系统导入等入口复用同一套校验/清洗逻辑。
validate_settings_patch = _validate
sanitize_settings_patch = _sanitize


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
    )
    return {
        "overrides": preference_payload(pref),
        "defaults": defaults_summary(settings),
        "effective": effective_summary(settings, pref),
        "allowed_modes": allowed_player_modes(),
        "available_modes": available_player_modes(
            client["is_companion"], client["is_android"]
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
