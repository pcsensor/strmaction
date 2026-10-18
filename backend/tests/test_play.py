from __future__ import annotations

from urllib.parse import quote

from app.config import ConfigManager
from app.config_store import SettingsService
from app.db import Database
from app.players import PlayContext, select_adapter
from app.players.base import mask_url
from app.players.web_intent import build_mpv_intent


def test_intent_encoding_handles_query_and_fragment():
    url = "https://cdn.example.com/path/a b.m3u8?x=1&y=%23&t=中文#frag"
    intent = build_mpv_intent(url, "三体 S01E01 & 第 1 集", 61_000)
    assert intent.startswith("intent://cdn.example.com/path/a%20b.m3u8?x=1&y=%23&t=")
    assert "package=is.xyz.mpv" in intent
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
