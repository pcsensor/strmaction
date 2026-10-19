"""播放适配器工厂。"""

from __future__ import annotations

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
from .mpv_ipc import MpvIpcAdapter, write_progress
from .web_intent import ClipboardAdapter, WebIntentAdapter, build_mpv_intent

__all__ = [
    "PlayContext",
    "PlayerAdapter",
    "MpvIpcAdapter",
    "WebIntentAdapter",
    "ClipboardAdapter",
    "build_mpv_intent",
    "clean_headers",
    "headers_hint",
    "parse_headers",
    "DEFAULT_HEADERS_HINT",
    "write_progress",
    "mask_url",
    "normalize_mode",
    "select_adapter",
]

MODE_ALIASES = {
    "intent": "browser_intent",
    "web_intent": "browser_intent",
    "mpv_ipc": "desktop_mpv",
    "backend": "desktop_mpv",
    "default": "builtin",
}
VALID_MODES = {"builtin", "external_mpv", "browser_intent", "desktop_mpv", "copy", "auto"}


def normalize_mode(requested: str | None, settings: SettingsService) -> str:
    raw = (requested or settings.player().get("mode") or "builtin").lower()
    mode = MODE_ALIASES.get(raw, raw)
    return mode if mode in VALID_MODES else "builtin"


def select_adapter(
    requested: str | None,
    context: PlayContext,
    settings: SettingsService,
    engine,
) -> PlayerAdapter:
    """按 v0.8 的 mode 选服务端适配器。

    builtin / external_mpv 由客户端自己播放，服务端不需要动作；
    这里返回 intent 适配器只为兼容旧调用方。
    """
    mode = normalize_mode(requested, settings)
    intent = WebIntentAdapter()
    clipboard = ClipboardAdapter()
    mpv = MpvIpcAdapter(settings, engine)
    if mode == "auto":
        if context.is_companion:
            return intent
        if context.is_android:
            return intent
        return mpv if mpv.available(context) else clipboard
    if mode == "browser_intent":
        return intent
    if mode == "desktop_mpv":
        return mpv if mpv.available(context) else clipboard
    if mode == "copy":
        return clipboard
    return intent
