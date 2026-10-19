"""设置与 Provider 连通性测试 API（v0.9: 仅管理员）。"""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Body, Depends
from sqlmodel import Session

from .. import __version__
from ..config_store import SettingsService
from ..deps import get_engine, get_scheduler, get_settings, require_admin
from ..errors import APIError
from ..jobs import SchedulerService
from ..players import clean_headers
from ..schemas import ProviderTestBody, CurrentUser
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
        if "mode" in player:
            player.pop("default", None)
    return patch


def _payload(settings: SettingsService) -> dict[str, Any]:
    return {
        "settings": settings.public(),
        "data_dir": str(settings.data_dir),
        "version": __version__,
    }


@router.get("/settings")
def get_settings_api(
    _admin: CurrentUser = Depends(require_admin),
    settings: SettingsService = Depends(get_settings),
):
    return _payload(settings)


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
