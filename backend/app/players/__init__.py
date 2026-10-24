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
from .clipboard import ClipboardAdapter

__all__ = [
    "PlayContext",
    "PlayerAdapter",
    "ClipboardAdapter",
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

VALID_MODES = {"builtin", "copy"}
# Historical names remain readable, but never produce external actions.
MODE_ALIASES = dict.fromkeys(
    ("internal", "default", "auto", "direct", "intent", "web_intent",
     "browser_intent", "external_mpv", "desktop_mpv", "mpv_ipc", "backend"),
    "builtin",
)


def normalize_mode(
    requested: str | None, player: dict[str, Any] | None = None
) -> str:
    """把请求/偏好归一到合法 mode；缺省时回落到 player 配置里的 mode。"""
    raw = str(requested or (player or {}).get("mode") or "builtin").lower()
    mode = MODE_ALIASES.get(raw, raw)
    return mode if mode in VALID_MODES else "builtin"


def select_adapter(
    requested: str | None,
    context: PlayContext,
    settings: SettingsService,
    engine,
) -> PlayerAdapter:
    """按 mode 选服务端适配器。

    内部播放由客户端执行；复制链接时服务端仅返回剪贴板动作。
    """
    # Playback itself is always performed by the App. No server-side launcher.
    return ClipboardAdapter()
