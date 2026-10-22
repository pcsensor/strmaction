"""Android intent:// 拉起系统播放器 / 复制链接兜底（§12.2、§12.4）。"""

from __future__ import annotations

from urllib.parse import quote, urlsplit

from ..models import Item, MediaFile
from .base import PlayContext


def build_external_intent(url: str, title: str, position_ms: int = 0) -> str:
    """按 Chrome intent 语法构造 ACTION_VIEW intent（由系统选择播放器）。"""
    parts = urlsplit(url)
    scheme = parts.scheme or "https"
    payload = parts.netloc + (quote(parts.path, safe="/%:@") if parts.path else "/")
    if parts.query:
        # 查询串必须完整编码，# 要编码为 %23，否则会被当作 fragment 截断
        payload += "?" + quote(parts.query, safe="=&%:@/")
    if parts.fragment:
        payload += "%23" + quote(parts.fragment, safe="")
    title_encoded = quote(title or "", safe="")
    return (
        f"intent://{payload}#Intent;scheme={scheme};"
        f"type=video/any;S.title={title_encoded};i.position={max(0, int(position_ms))};end"
    )


class WebIntentAdapter:
    name = "web_intent"

    def available(self, context: PlayContext) -> bool:
        return True

    async def build(
        self,
        *,
        item: Item,
        media: MediaFile,
        title: str,
        resume_ms: int,
        context: PlayContext,
    ) -> dict:
        action = build_external_intent(media.url, title, resume_ms)
        return {
            "mode": "intent",
            "target": "intent",
            "action": action,
            "fallback_url": media.url,
            "tip": "即将用系统播放器打开",
            "warning": "当前浏览器可能不支持 intent://，请使用 Chrome 或伴侣 App",
        }


class ClipboardAdapter:
    name = "clipboard"

    def available(self, context: PlayContext) -> bool:
        return True

    async def build(
        self,
        *,
        item: Item,
        media: MediaFile,
        title: str,
        resume_ms: int,
        context: PlayContext,
    ) -> dict:
        return {
            "mode": "copy",
            "target": "copy",
            "action": None,
            "fallback_url": media.url,
            "tip": "已复制播放地址，可在支持该协议的播放器中打开",
        }
