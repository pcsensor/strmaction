"""Payload validation and log redaction.

Everything that enters the desktop client from the web UI is untrusted: the
payload contains a direct media URL and request headers (credentials).  It is
validated here before it is handed to the player.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Mapping
from urllib.parse import urljoin, urlparse

from .config import ConfigError, normalize_server_url

MAX_HEADERS = 32
MAX_HEADER_KEY = 128
MAX_HEADER_VALUE = 4096
MAX_SUBTITLES = 32
MAX_URL_LENGTH = 16_384
_TOKEN_RE = re.compile(r"^[A-Za-z0-9._~+/=-]{8,512}$")


class PayloadError(ValueError):
    """Invalid playback payload from the web UI."""


@dataclass(frozen=True)
class Subtitle:
    label: str
    url: str


@dataclass(frozen=True)
class PlaybackPayload:
    item_id: int
    play_url: str
    headers: dict[str, str]
    play_token: str
    resume_ms: int
    progress_interval_ms: int
    subtitles: tuple[Subtitle, ...]
    title: str = ""
    series_title: str = ""
    playlist: tuple[dict, ...] = ()
    next_item_id: int | None = None
    next_title: str = ""
    current_index: int = -1
    duration_ms: int | None = None


def _require_int(value: Any, name: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise PayloadError(f"{name} 必须是整数")
    if value < minimum:
        raise PayloadError(f"{name} 不能小于 {minimum}")
    return value


def _require_http_url(value: Any, name: str) -> str:
    if not isinstance(value, str):
        raise PayloadError(f"{name} 必须是 URL 字符串")
    url = value.strip()
    if not url or len(url) > MAX_URL_LENGTH:
        raise PayloadError(f"{name} 长度不合法")
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise PayloadError(f"{name} 必须是 http/https 地址")
    return url


def _clean_headers(raw: Any) -> dict[str, str]:
    if raw is None:
        return {}
    if not isinstance(raw, Mapping):
        raise PayloadError("headers 必须是对象")
    if len(raw) > MAX_HEADERS:
        raise PayloadError("headers 数量过多")
    clean: dict[str, str] = {}
    for key, value in raw.items():
        if not isinstance(key, str) or not isinstance(value, str):
            raise PayloadError("headers 的键和值都必须是字符串")
        name = key.strip()
        text = value.strip()
        if not name or len(name) > MAX_HEADER_KEY or len(text) > MAX_HEADER_VALUE:
            raise PayloadError("headers 长度不合法")
        if "\r" in name or "\n" in name or "\r" in text or "\n" in text:
            raise PayloadError("headers 不能包含换行")
        clean[name] = text
    return clean


def _clean_subtitles(raw: Any, server_url: str) -> tuple[Subtitle, ...]:
    if raw is None:
        return ()
    if not isinstance(raw, list):
        raise PayloadError("subtitles 必须是数组")
    if len(raw) > MAX_SUBTITLES:
        raise PayloadError("subtitles 数量过多")
    out: list[Subtitle] = []
    for entry in raw:
        if not isinstance(entry, Mapping):
            continue
        url = entry.get("url")
        if not isinstance(url, str) or not url.strip():
            continue
        absolute = urljoin(server_url + "/", url.strip())
        parsed = urlparse(absolute)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            continue
        label = str(entry.get("label") or entry.get("lang") or "").strip()
        out.append(Subtitle(label=label or "字幕", url=absolute))
    return tuple(out)


def parse_payload(raw: Any, server_url: str) -> PlaybackPayload:
    """Validate a /api/play response received via the JS bridge."""
    if not isinstance(raw, Mapping):
        raise PayloadError("播放数据格式不正确")
    server = normalize_server_url(server_url)

    item_id = _require_int(raw.get("item_id"), "item_id", minimum=1)
    play_url = _require_http_url(raw.get("play_url"), "play_url")
    headers = _clean_headers(raw.get("headers"))
    token = raw.get("play_token")
    if not isinstance(token, str) or not _TOKEN_RE.fullmatch(token.strip()):
        raise PayloadError("play_token 无效")
    resume_ms = _require_int(raw.get("resume_ms") or 0, "resume_ms")
    interval = raw.get("progress_interval_ms") or 5000
    interval = _require_int(interval, "progress_interval_ms", minimum=0)
    interval = max(2000, min(interval, 60_000))
    subtitles = _clean_subtitles(raw.get("subtitles"), server)
    title = str(raw.get("title") or "").strip()[:512]
    series_title = str(raw.get("series_title") or "").strip()[:512]
    duration_ms = raw.get("duration_ms")
    if duration_ms is not None and isinstance(duration_ms, int) and duration_ms > 0:
        duration_ms_val: int | None = duration_ms
    else:
        duration_ms_val = None

    raw_playlist = raw.get("playlist")
    playlist_clean: list[dict] = []
    if isinstance(raw_playlist, list):
        for entry in raw_playlist[:200]:
            if isinstance(entry, Mapping):
                ep_id = entry.get("item_id") if entry.get("item_id") is not None else entry.get("id")
                try:
                    ep_id = int(ep_id) if ep_id is not None else None
                except (TypeError, ValueError):
                    ep_id = None
                playlist_clean.append({
                    "item_id": ep_id,
                    "id": ep_id,
                    "title": str(entry.get("title") or ""),
                    "episode_no": entry.get("episode_no"),
                    "code": str(entry.get("code") or ""),
                    "watched": bool(entry.get("watched")),
                    "current": bool(entry.get("current")),
                })

    next_item_id = raw.get("next_item_id")
    if not isinstance(next_item_id, int) or next_item_id <= 0:
        next_item_id = None
    next_title = str(raw.get("next_title") or "").strip()[:256]
    current_index = raw.get("current_index")
    current_index_val = current_index if isinstance(current_index, int) else -1

    return PlaybackPayload(
        item_id=item_id,
        play_url=play_url,
        headers=headers,
        play_token=token.strip(),
        resume_ms=resume_ms,
        progress_interval_ms=interval,
        subtitles=subtitles,
        title=title,
        series_title=series_title,
        playlist=tuple(playlist_clean),
        next_item_id=next_item_id,
        next_title=next_title,
        current_index=current_index_val,
        duration_ms=duration_ms_val,
    )


def redact_url(url: str | None) -> str:
    """Log-safe URL: keep scheme/host, drop path/query/token."""
    if not url:
        return ""
    try:
        parsed = urlparse(url)
    except ValueError:
        return "<invalid-url>"
    if not parsed.scheme or not parsed.netloc:
        return "<invalid-url>"
    return f"{parsed.scheme}://{parsed.netloc}/***"


def redact_headers(headers: Mapping[str, str] | None) -> dict[str, str]:
    return {key: "***" for key in (headers or {})}


def config_error_message(exc: Exception) -> str:
    if isinstance(exc, (ConfigError, PayloadError)):
        return str(exc)
    return "操作失败，请查看日志"
