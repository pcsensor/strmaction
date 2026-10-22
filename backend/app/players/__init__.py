"""播放适配器工厂。"""

from __future__ import annotations

from typing import Any

from ..config_store import SettingsService
from .base import (
    DEFAULT_HEADERS_HINT,
    PlayContext,
    PlayerAdapter,
    clean_headers,
    headers_hint,
    mask_url,
    parse_headers,
)
from .cache import (
    DEFAULT_CACHE_LIMIT_MB,
    MAX_CACHE_LIMIT_MB,
    normalize_cache_limit,
)
from .web_intent import ClipboardAdapter, WebIntentAdapter, build_external_intent

__all__ = [
    "PlayContext",
    "PlayerAdapter",
    "WebIntentAdapter",
    "ClipboardAdapter",
    "build_external_intent",
    "clean_headers",
    "headers_hint",
    "parse_headers",
    "DEFAULT_HEADERS_HINT",
    "DEFAULT_CACHE_LIMIT_MB",
    "MAX_CACHE_LIMIT_MB",
    "normalize_cache_limit",
    "mask_url",
    "normalize_mode",
    "select_adapter",
]

MODE_ALIASES = {
    "intent": "browser_intent",
    "web_intent": "browser_intent",
    "default": "builtin",
}
# v1.3：服务端 mpv（desktop_mpv）与外部 mpv（external_mpv）已下线。
VALID_MODES = {
    "builtin",
    "browser_intent",
    "copy",
    "auto",
    "direct",
}
OBSOLETE_MODES = {"external_mpv", "desktop_mpv", "mpv_ipc", "backend"}


def normalize_mode(
    requested: str | None, player: dict[str, Any] | None = None
) -> str:
    """把请求/偏好归一到合法 mode；缺省时回落到 player 配置里的 mode。"""
    raw = str(requested or (player or {}).get("mode") or "builtin").lower()
    if raw in OBSOLETE_MODES:
        # 旧配置/旧客户端传来的已下线模式按自动处理。
        return "auto"
    mode = MODE_ALIASES.get(raw, raw)
    return mode if mode in VALID_MODES else "builtin"


def select_adapter(
    requested: str | None,
    context: PlayContext,
    settings: SettingsService,
    engine,
) -> PlayerAdapter:
    """按 mode 选服务端适配器。

    builtin / direct 由客户端自己播放，服务端不需要动作；
    这里返回 intent 适配器只为兼容旧调用方。
    """
    mode = normalize_mode(requested, settings.player())
    intent = WebIntentAdapter()
    clipboard = ClipboardAdapter()
    if mode == "auto":
        if context.is_companion:
            return intent
        if context.is_android:
            return intent
        return clipboard
    if mode == "browser_intent":
        return intent
    if mode == "copy":
        return clipboard
    return intent
