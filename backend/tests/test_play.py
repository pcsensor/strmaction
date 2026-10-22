from __future__ import annotations

from urllib.parse import quote

from app.config import ConfigManager, sanitize_settings
from app.config_store import SettingsService
from app.db import Database
from app.api.play import resolve_mode
from app.players import PlayContext, normalize_mode, select_adapter
from app.players.base import mask_url
from app.players.cache import normalize_cache_limit
from app.players.web_intent import build_external_intent


def test_cache_limit_normalization():
    assert normalize_cache_limit(128) == 128
    assert normalize_cache_limit(-1) == 0
    assert normalize_cache_limit(1) == 16
    assert normalize_cache_limit(99999) == 2048
    assert normalize_cache_limit("bad") == 128


def test_intent_encoding_handles_query_and_fragment():
    url = "https://cdn.example.com/path/a b.m3u8?x=1&y=%23&t=中文#frag"
    intent = build_external_intent(url, "三体 S01E01 & 第 1 集", 61_000)
    assert intent.startswith("intent://cdn.example.com/path/a%20b.m3u8?x=1&y=%23&t=")
    # v1.3：不再写死 mpv 包名，交给系统选择播放器
    assert "package=" not in intent
    assert "type=video/any" in intent
    assert "i.position=61000" in intent
    assert "S.title=" + quote("三体 S01E01 & 第 1 集", safe="") in intent
    assert "%23frag" in intent
    assert intent.endswith(";end")


def test_mask_url_does_not_leak_path():
    url = "https://pan.baidu.com/s/very-secret-token-1234567890"
    masked = mask_url(url)
    assert "very-secret-token" not in masked
    assert masked.startswith("https://pan.baidu.com/")


def test_adapter_selection(tmp_path):
    config_file = tmp_path / "config.yaml"
    config_file.write_text("server:\n  data_dir: ./data\n", encoding="utf-8")
    config = ConfigManager(config_file)
    db = Database(config)
    settings = SettingsService(config, db.engine)

    context = PlayContext(user_agent="Mozilla/5.0 (Linux; Android 14)", is_android=True)
    adapter = select_adapter("auto", context, settings, db.engine)
    assert adapter.name == "web_intent"

    adapter = select_adapter("copy", context, settings, db.engine)
    assert adapter.name == "clipboard"


def test_obsolete_player_settings_are_pruned():
    """旧的 mpv 字段与模式必须从对外配置里消失。"""
    cleaned = sanitize_settings(
        {
            "player": {
                "mode": "desktop_mpv",
                "mpv_path": "/usr/bin/mpv",
                "mpv_extra_args": ["--foo"],
                "mpv_package": "is.xyz.mpv",
                "enable_progress": True,
                "cache_limit_mb": 64,
            }
        }
    )
    assert cleaned["player"] == {"mode": "auto", "cache_limit_mb": 64}


def test_deprecated_modes_normalize_to_auto():
    assert normalize_mode("desktop_mpv") == "auto"
    assert normalize_mode("external_mpv") == "auto"
    assert normalize_mode("mpv_ipc") == "auto"
    assert normalize_mode("builtin") == "builtin"


def test_resolve_mode_follows_device_capabilities(tmp_path):
    config_file = tmp_path / "config.yaml"
    config_file.write_text("server:\n  data_dir: ./data\n", encoding="utf-8")
    config = ConfigManager(config_file)
    db = Database(config)
    settings = SettingsService(config, db.engine)

    desktop = PlayContext(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64)")
    android = PlayContext(user_agent="Mozilla/5.0 (Linux; Android 14)", is_android=True)
    companion = PlayContext(user_agent="StrmActionCompanion", is_companion=True)

    assert resolve_mode("auto", desktop, settings, db.engine) == "copy"
    assert resolve_mode("auto", android, settings, db.engine) == "browser_intent"
    assert resolve_mode("auto", companion, settings, db.engine) == "builtin"
    assert resolve_mode("browser_intent", desktop, settings, db.engine) == "copy"
    assert resolve_mode("builtin", desktop, settings, db.engine) == "copy"
    assert resolve_mode("direct", desktop, settings, db.engine) == "direct"
    # 已下线的模式请求按自动处理，不再尝试启动任何服务端播放器
    assert resolve_mode("desktop_mpv", desktop, settings, db.engine) == "copy"
    assert resolve_mode("desktop_mpv", companion, settings, db.engine) == "builtin"
