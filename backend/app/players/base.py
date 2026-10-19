"""播放适配器接口。"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Protocol

from ..models import Item, MediaFile

HEADER_NAME_RE = re.compile(r"^[A-Za-z0-9!#$%&'*+\-.^_`|~]+$")
DEFAULT_HEADERS_HINT = "User-Agent: pan.baidu.com, Referer: https://pan.baidu.com/"


@dataclass
class PlayContext:
    user_agent: str = ""
    is_android: bool = False
    is_companion: bool = False
    base_url: str = ""
    client_ip: str = ""
    headers: dict[str, str] | None = None


def clean_headers(data: object) -> dict[str, str]:
    """校验并清洗请求头：忽略非法名、CRLF 注入与超长值。"""
    if not isinstance(data, dict):
        return {}
    out: dict[str, str] = {}
    for key, value in data.items():
        if not isinstance(key, str) or not isinstance(value, str):
            continue
        key = key.strip()
        value = value.strip()
        if not key or not HEADER_NAME_RE.match(key):
            continue
        if "\r" in value or "\n" in value or len(value) > 2048:
            continue
        out[key] = value
    return out


def parse_headers(raw: str | None) -> dict[str, str]:
    """把 library.play_headers 的 JSON 解析成干净的请求头字典。"""
    if not raw:
        return {}
    try:
        return clean_headers(json.loads(raw))
    except (json.JSONDecodeError, TypeError):
        return {}


def headers_hint(headers: dict[str, str]) -> str:
    if not headers:
        return DEFAULT_HEADERS_HINT
    return ", ".join(f"{key}: {value}" for key, value in headers.items())


def mask_url(url: str) -> str:
    """日志中打码播放地址（保留 host + 前 12 字符）。"""
    if not url:
        return ""
    try:
        from urllib.parse import urlsplit

        parts = urlsplit(url)
        head = f"{parts.scheme}://{parts.netloc}"
        rest = (parts.path or "").lstrip("/")
        return f"{head}/{rest[:12]}…"
    except Exception:
        return url[:16] + "…"


class PlayerAdapter(Protocol):
    name: str

    def available(self, context: PlayContext) -> bool: ...

    async def build(
        self,
        *,
        item: Item,
        media: MediaFile,
        title: str,
        resume_ms: int,
        context: PlayContext,
    ) -> dict: ...
