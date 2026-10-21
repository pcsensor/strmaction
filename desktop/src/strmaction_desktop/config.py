"""Configuration for the StrmAction desktop shell.

Only non-secret preferences live here: server address, mpv path, playback
cache budget and window geometry. Account credentials and web session cookies
stay in the WebView.
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from urllib.parse import urlparse

APP_NAME = "StrmAction"
DEFAULT_WIDTH = 1280
DEFAULT_HEIGHT = 820
MIN_WIDTH = 900
MIN_HEIGHT = 640
DEFAULT_CACHE_LIMIT_MB = 128
MIN_CACHE_LIMIT_MB = 0
MIN_ACTIVE_CACHE_LIMIT_MB = 16
MAX_CACHE_LIMIT_MB = 2048


class ConfigError(ValueError):
    """Invalid desktop configuration."""


def app_data_dir() -> Path:
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    return base / APP_NAME


def config_path() -> Path:
    return app_data_dir() / "config.json"


def log_dir() -> Path:
    return app_data_dir() / "logs"


def webview_storage_dir() -> Path:
    return app_data_dir() / "webview"


def normalize_server_url(raw: str) -> str:
    """Validate and normalize the server base URL."""
    value = (raw or "").strip().rstrip("/")
    if not value:
        raise ConfigError("服务器地址不能为空")
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ConfigError("服务器地址必须以 http:// 或 https:// 开头")
    if parsed.username or parsed.password:
        raise ConfigError("服务器地址不能包含用户名或密码")
    return value


def _clamp(value: int, low: int, high: int, default: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    return max(low, min(number, high))


def normalize_cache_limit(value: int) -> int:
    """0 keeps the cache off; other values use a 16–2048MB budget."""
    try:
        number = int(value)
    except (TypeError, ValueError):
        return DEFAULT_CACHE_LIMIT_MB
    if number <= MIN_CACHE_LIMIT_MB:
        return MIN_CACHE_LIMIT_MB
    return min(max(number, MIN_ACTIVE_CACHE_LIMIT_MB), MAX_CACHE_LIMIT_MB)


@dataclass
class DesktopConfig:
    server_url: str = ""
    mpv_path: str = ""
    cache_limit_mb: int = DEFAULT_CACHE_LIMIT_MB
    allow_self_signed_https: bool = False
    window_width: int = DEFAULT_WIDTH
    window_height: int = DEFAULT_HEIGHT
    log_level: str = "INFO"

    def is_configured(self) -> bool:
        return bool(self.server_url)

    def normalized(self) -> "DesktopConfig":
        server = normalize_server_url(self.server_url) if self.server_url else ""
        return DesktopConfig(
            server_url=server,
            mpv_path=(self.mpv_path or "").strip(),
            cache_limit_mb=normalize_cache_limit(self.cache_limit_mb),
            allow_self_signed_https=bool(self.allow_self_signed_https),
            window_width=_clamp(self.window_width, MIN_WIDTH, 3840, DEFAULT_WIDTH),
            window_height=_clamp(self.window_height, MIN_HEIGHT, 2160, DEFAULT_HEIGHT),
            log_level=(self.log_level or "INFO").upper(),
        )

    @classmethod
    def load(cls, path: Path | None = None) -> "DesktopConfig":
        target = path or config_path()
        if not target.is_file():
            return cls()
        try:
            raw = json.loads(target.read_text("utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ConfigError(f"配置文件无法读取：{exc}") from exc
        if not isinstance(raw, dict):
            raise ConfigError("配置文件格式不正确")
        return cls(
            server_url=str(raw.get("server_url") or ""),
            mpv_path=str(raw.get("mpv_path") or ""),
            cache_limit_mb=raw.get("cache_limit_mb", DEFAULT_CACHE_LIMIT_MB),
            allow_self_signed_https=bool(raw.get("allow_self_signed_https", False)),
            window_width=raw.get("window_width", DEFAULT_WIDTH),
            window_height=raw.get("window_height", DEFAULT_HEIGHT),
            log_level=str(raw.get("log_level") or "INFO"),
        ).normalized()

    def save(self, path: Path | None = None) -> Path:
        target = path or config_path()
        target.parent.mkdir(parents=True, exist_ok=True)
        payload = asdict(self.normalized())
        tmp = target.with_suffix(target.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), "utf-8")
        os.replace(tmp, target)
        return target
