"""Explicit clipboard action. No external application or intent URL is emitted."""
from .base import PlayContext


class ClipboardAdapter:
    name = "clipboard"

    def available(self, context: PlayContext) -> bool:
        return True

    async def build(self, *, item, media, title, resume_ms, context) -> dict:
        return {"mode": "copy", "target": "copy", "action": None,
                "fallback_url": media.url, "tip": "复制所选版本的播放链接"}
