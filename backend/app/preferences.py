"""账号播放偏好。None 跟随全局；公开方式仅 builtin / copy。

历史模式读取时归一化为 builtin，设备覆盖由客户端按服务器和账号保存。
"""

from __future__ import annotations

from typing import Any

from sqlmodel import Session

from .config_store import SettingsService
from .models import UserPreference, utcnow
from .players import normalize_mode

ALL_PLAYER_MODES = ("builtin", "copy")
_COLUMN_BY_FIELD = {
    "mode": "player_mode",
}


def allowed_player_modes() -> list[str]:
    return list(ALL_PLAYER_MODES)


def available_player_modes(is_companion: bool, is_android: bool) -> list[str]:
    """当前客户端真正能执行的模式；用于设置页提示“当前设备不支持”。"""
    return ["builtin", "copy"] if is_companion else ["copy"]


def get_preference(engine, user_id: int) -> UserPreference | None:
    with Session(engine) as session:
        return session.get(UserPreference, user_id)


def preference_payload(pref: UserPreference | None) -> dict[str, Any]:
    """只返回用户可自定的字段，None 表示跟随全局。"""
    return {
        "mode": normalize_mode(pref.player_mode) if pref and pref.player_mode else None,
    }


def save_preference(engine, user_id: int, changes: dict[str, Any]) -> UserPreference:
    """按字段增量更新；changes 里的 None 表示清除该字段的覆盖。"""
    with Session(engine) as session:
        row = session.get(UserPreference, user_id)
        if row is None:
            row = UserPreference(user_id=user_id, updated_at=utcnow())
        for field, column in _COLUMN_BY_FIELD.items():
            if field in changes:
                value = changes[field]
                setattr(row, column, normalize_mode(value) if field == "mode" and value else value)
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
            player["mode"] = normalize_mode(pref.player_mode)
    return player


def effective_summary(
    settings: SettingsService, pref: UserPreference | None
) -> dict[str, Any]:
    """给前端的「生效值」：只暴露播放方式。"""
    player = effective_player(settings, pref)
    return {
        "mode": normalize_mode(None, player),
    }


def defaults_summary(settings: SettingsService) -> dict[str, Any]:
    player = settings.player()
    return {
        "mode": normalize_mode(None, player),
    }
