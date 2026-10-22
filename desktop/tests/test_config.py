from __future__ import annotations

import json

import pytest

from strmaction_desktop.config import (
    ConfigError,
    DesktopConfig,
    normalize_server_url,
)


def test_normalize_server_url():
    assert normalize_server_url("https://media.example.com/") == "https://media.example.com"
    assert normalize_server_url(" http://127.0.0.1:8080 ") == "http://127.0.0.1:8080"
    with pytest.raises(ConfigError):
        normalize_server_url("ftp://media.example.com")
    with pytest.raises(ConfigError):
        normalize_server_url("media.example.com")
    with pytest.raises(ConfigError):
        normalize_server_url("")
    with pytest.raises(ConfigError):
        normalize_server_url("https://user:pass@media.example.com")


def test_config_roundtrip(tmp_path):
    path = tmp_path / "config.json"
    config = DesktopConfig(
        server_url="https://media.example.com/",
        cache_limit_mb=64,
        allow_self_signed_https=True,
        window_width=1400,
        window_height=900,
        log_level="debug",
    )
    config.save(path)
    loaded = DesktopConfig.load(path)
    assert loaded.server_url == "https://media.example.com"
    assert loaded.cache_limit_mb == 64
    assert loaded.allow_self_signed_https is True
    assert loaded.window_width == 1400
    assert loaded.window_height == 900
    assert loaded.log_level == "DEBUG"
    assert loaded.is_configured()


def test_config_clamps_window_size(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(
        json.dumps({"server_url": "https://x.test", "window_width": 10, "window_height": 9999}),
        "utf-8",
    )
    loaded = DesktopConfig.load(path)
    assert loaded.window_width == 900
    assert loaded.window_height == 2160


def test_config_clamps_cache_limit(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(
        json.dumps({"server_url": "https://x.test", "cache_limit_mb": 99999}),
        "utf-8",
    )
    assert DesktopConfig.load(path).cache_limit_mb == 2048

    path.write_text(
        json.dumps({"server_url": "https://x.test", "cache_limit_mb": -5}),
        "utf-8",
    )
    assert DesktopConfig.load(path).cache_limit_mb == 0

    path.write_text(
        json.dumps({"server_url": "https://x.test", "cache_limit_mb": 1}),
        "utf-8",
    )
    assert DesktopConfig.load(path).cache_limit_mb == 16


def test_config_invalid_json(tmp_path):
    path = tmp_path / "config.json"
    path.write_text("{oops", "utf-8")
    with pytest.raises(ConfigError):
        DesktopConfig.load(path)


def test_config_missing_returns_defaults(tmp_path):
    loaded = DesktopConfig.load(tmp_path / "missing.json")
    assert loaded.server_url == ""
    assert not loaded.is_configured()
