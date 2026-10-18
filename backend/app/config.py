"""配置管理。

优先级：数据库设置（设置页写入） > config.yaml > 内置默认值。
所有密钥仅在服务端使用，对外返回时统一打码。
"""

from __future__ import annotations

import copy
import json
import os
import threading
from pathlib import Path
from typing import Any

import yaml

# ---------------------------------------------------------------------------
# 默认配置
# ---------------------------------------------------------------------------

DEFAULT_CONFIG: dict[str, Any] = {
    "server": {
        "host": "0.0.0.0",
        "port": 8080,
        "base_url": "",
        "data_dir": "./data",
    },
    "auth": {
        "username": "admin",
        "password_hash": "",
    },
    "scraper": {
        "language": "zh-CN",
        "proxy": "",
        "auto_refresh_days": 30,
        "match_threshold": 0.75,
        "provider_priority": {
            "movie": ["tmdb", "tvdb"],
            "tv": ["tmdb", "tvdb"],
            "home": [],
            "course": [],
        },
        "tmdb": {
            "api_key": "",
            "base_url": "https://api.themoviedb.org/3",
            "proxy": "",
            "rate_limit": 8,
            "concurrency": 4,
            "language": "zh-CN",
        },
        "tvdb": {
            "api_key": "",
            "pin": "",
            "base_url": "https://api4.thetvdb.com/v4",
            "proxy": "",
            "rate_limit": 4,
            "concurrency": 2,
            "language": "zho",
            "season_type": "default",
        },
    },
    "scanner": {
        "ignore": ["@eaDir", ".DS_Store", "#recycle", "*.tmp"],
        "follow_symlinks": False,
        "max_depth": 6,
    },
    "player": {
        "mode": "builtin",
        "progress_interval_ms": 5000,
        "play_token_ttl_hours": 12,
        "fallback_on_error": True,
        "play_headers": {},
        "mpv_package": "is.xyz.mpv",
        "mpv_path": "/usr/bin/mpv",
        "mpv_extra_args": [
            "--http-header-fields=User-Agent: pan.baidu.com,Referer: https://pan.baidu.com/",
        ],
        "enable_progress": True,
    },
    "ui": {
        "default_language": "zh-CN",
        "hero_rotate_ms": 8000,
    },
}

SECRET_KEYS = {"api_key", "pin", "password_hash", "token", "secret"}


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------


def deep_merge(base: dict[str, Any], override: dict[str, Any] | None) -> dict[str, Any]:
    """递归合并，override 中的值覆盖 base；不修改入参。"""
    out = copy.deepcopy(base)
    if not override:
        return out
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = deep_merge(out[key], value)
        else:
            out[key] = copy.deepcopy(value)
    return out


def mask_secret(value: Any) -> Any:
    if not isinstance(value, str) or not value:
        return value
    if len(value) <= 4:
        return "****"
    return "****" + value[-4:]


def is_masked(value: Any) -> bool:
    return isinstance(value, str) and value.startswith("****")


def mask_config(config: Any) -> Any:
    """递归打码敏感字段（用于 GET /settings）。"""
    if isinstance(config, dict):
        out: dict[str, Any] = {}
        for key, value in config.items():
            if key in SECRET_KEYS and isinstance(value, str):
                out[key] = mask_secret(value)
            else:
                out[key] = mask_config(value)
        return out
    if isinstance(config, list):
        return [mask_config(v) for v in config]
    return config


def strip_masked_keys(config: Any) -> Any:
    """移除 PATCH 请求里回传的打码值，避免把 **** 写进配置。"""
    if isinstance(config, dict):
        out: dict[str, Any] = {}
        for key, value in config.items():
            if key in SECRET_KEYS and is_masked(value):
                continue
            out[key] = strip_masked_keys(value)
        return out
    if isinstance(config, list):
        return [strip_masked_keys(v) for v in config]
    return config


def env_override(config: dict[str, Any]) -> dict[str, Any]:
    """少量环境变量覆盖，方便 Docker 部署。"""
    env_map = {
        "STRMACTION_DATA_DIR": ("server", "data_dir"),
        "STRMACTION_BASE_URL": ("server", "base_url"),
        "STRMACTION_PORT": ("server", "port"),
        "STRMACTION_USERNAME": ("auth", "username"),
        "STRMACTION_TMDB_KEY": ("scraper", "tmdb", "api_key"),
        "STRMACTION_TVDB_KEY": ("scraper", "tvdb", "api_key"),
        "STRMACTION_TVDB_PIN": ("scraper", "tvdb", "pin"),
        "STRMACTION_PROXY": ("scraper", "proxy"),
    }
    for env_key, path in env_map.items():
        raw = os.environ.get(env_key)
        if raw is None or raw == "":
            continue
        target = config
        for part in path[:-1]:
            target = target.setdefault(part, {})
        target[path[-1]] = int(raw) if path[-1] == "port" else raw
    return config


def load_yaml(path: str | Path | None) -> dict[str, Any]:
    if not path:
        return {}
    file = Path(path)
    if not file.exists():
        return {}
    try:
        data = yaml.safe_load(file.read_text("utf-8")) or {}
    except Exception as exc:  # pragma: no cover - 配置损坏时不应白屏
        print(f"[config] 无法解析配置文件 {file}: {exc}")
        return {}
    return data if isinstance(data, dict) else {}


class ConfigManager:
    """负责加载 yaml、解析数据目录、合并数据库覆盖设置。"""

    def __init__(self, config_path: str | Path | None = None):
        self.config_path = Path(
            config_path
            or os.environ.get("STRMACTION_CONFIG")
            or Path.cwd() / "config.yaml"
        )
        self._lock = threading.RLock()
        self._yaml = env_override(load_yaml(self.config_path))
        self._db_override: dict[str, Any] = {}
        self._db_override_raw: dict[str, Any] = {}
        self._revision = 0
        self._effective_cache: dict[str, Any] | None = None
        self._cache_revision = -1

    # -- 路径 -------------------------------------------------------------
    @property
    def base_config(self) -> dict[str, Any]:
        return deep_merge(DEFAULT_CONFIG, self._yaml)

    @property
    def data_dir(self) -> Path:
        raw = self.base_config["server"].get("data_dir") or "./data"
        path = Path(raw)
        if not path.is_absolute():
            path = (self.config_path.parent / path).resolve()
        return path

    @property
    def image_dir(self) -> Path:
        return self.data_dir / "images"

    @property
    def db_path(self) -> Path:
        return self.data_dir / "strmaction.db"

    def ensure_dirs(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.image_dir.mkdir(parents=True, exist_ok=True)

    # -- 数据库覆盖 -------------------------------------------------------
    def set_db_override(self, override: dict[str, Any] | None) -> None:
        with self._lock:
            self._db_override_raw = copy.deepcopy(override or {})
            self._db_override = strip_masked_keys(copy.deepcopy(override or {}))
            self._revision += 1

    def update_db_override(self, patch: dict[str, Any]) -> dict[str, Any]:
        """深合并 PATCH 内容并返回新的原始覆盖（调用方负责持久化）。"""
        clean = strip_masked_keys(copy.deepcopy(patch or {}))
        with self._lock:
            merged = deep_merge(self._db_override_raw, clean)
            self.set_db_override(merged)
            return copy.deepcopy(self._db_override_raw)

    def effective(self) -> dict[str, Any]:
        with self._lock:
            if (
                self._effective_cache is None
                or self._cache_revision != self._revision
            ):
                self._effective_cache = deep_merge(self.base_config, self._db_override)
                self._cache_revision = self._revision
            return copy.deepcopy(self._effective_cache)

    @property
    def revision(self) -> int:
        with self._lock:
            return self._revision


def dumps_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
