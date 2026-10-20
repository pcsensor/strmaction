"""用户级偏好（v1.2）。

只有少量字段允许普通用户自定：播放方式与失败回退提示。
`None` 表示「跟随全局默认」，读取时与 SettingsService.player() 合并。
"""

from __future__ import annotations

from typing import Any

from sqlmodel import Session

from .config_store import SettingsService
from .models import UserPreference, utcnow
from .players import normalize_mode

ALL_PLAYER_MODES = (
    "auto",
    "builtin",
    "external_mpv",
    "browser_intent",
    "desktop_mpv",
    "copy",
)
# 服务器桌面 mpv 会在服务端启动进程，仅管理员（通常是 HTPC 主人）可用。
USER_PLAYER_MODES = tuple(mode for mode in ALL_PLAYER_MODES if mode != "desktop_mpv")
_COLUMN_BY_FIELD = {
    "mode": "player_mode",
    "fallback_on_error": "fallback_on_error",
}


def allowed_player_modes(is_admin: bool) -> list[str]:
    return list(ALL_PLAYER_MODES if is_admin else USER_PLAYER_MODES)


def available_player_modes(
    is_admin: bool, is_companion: bool, is_android: bool
) -> list[str]:
    """当前客户端真正能执行的模式；用于设置页提示“当前设备不支持”。"""
    if is_companion:
        return ["auto", "builtin", "external_mpv", "copy"]
    if is_android:
        return ["auto", "browser_intent", "copy"]
    modes = ["auto", "copy"]
    if is_admin:
        modes.append("desktop_mpv")
    return modes


def get_preference(engine, user_id: int) -> UserPreference | None:
    with Session(engine) as session:
        return session.get(UserPreference, user_id)


def preference_payload(
    pref: UserPreference | None, allow_desktop_mpv: bool = True
) -> dict[str, Any]:
    """只返回用户可自定的字段，None 表示跟随全局。"""
    mode = pref.player_mode if pref else None
    if not allow_desktop_mpv and mode == "desktop_mpv":
        # 旧数据/管理员默认里可能残留服务器 mpv，对普通用户按未设置处理。
        mode = None
    return {
        "mode": mode,
        "fallback_on_error": pref.fallback_on_error if pref else None,
    }


def save_preference(engine, user_id: int, changes: dict[str, Any]) -> UserPreference:
    """按字段增量更新；changes 里的 None 表示清除该字段的覆盖。"""
    with Session(engine) as session:
        row = session.get(UserPreference, user_id)
        if row is None:
            row = UserPreference(user_id=user_id, updated_at=utcnow())
        for field, column in _COLUMN_BY_FIELD.items():
            if field in changes:
                setattr(row, column, changes[field])
        row.updated_at = utcnow()
        session.add(row)
        session.commit()
        session.refresh(row)
        return row


def effective_player(
    settings: SettingsService, pref: UserPreference | None
) -> dict[str, Any]:
    """全局播放器配置 + 用户覆盖，供播放链路使用。"""
    player = dict(settings.player())
    if pref is not None:
        if pref.player_mode:
            player["mode"] = pref.player_mode
        if pref.fallback_on_error is not None:
            player["fallback_on_error"] = bool(pref.fallback_on_error)
    return player


def _display_mode(mode: str, allow_desktop_mpv: bool) -> str:
    """普通用户不显示服务器 mpv；用 auto 表示会按设备降级。"""
    if not allow_desktop_mpv and mode == "desktop_mpv":
        return "auto"
    return mode


def effective_summary(
    settings: SettingsService,
    pref: UserPreference | None,
    allow_desktop_mpv: bool = True,
) -> dict[str, Any]:
    """给前端的「生效值」：只暴露用户关心的两个字段。"""
    player = effective_player(settings, pref)
    return {
        "mode": _display_mode(normalize_mode(None, player), allow_desktop_mpv),
        "fallback_on_error": bool(player.get("fallback_on_error", True)),
    }


def defaults_summary(
    settings: SettingsService, allow_desktop_mpv: bool = True
) -> dict[str, Any]:
    player = settings.player()
    return {
        "mode": _display_mode(normalize_mode(None, player), allow_desktop_mpv),
        "fallback_on_error": bool(player.get("fallback_on_error", True)),
    }
