from __future__ import annotations

import json
from dataclasses import dataclass

from strmaction_desktop.bridge import DesktopBridge
from strmaction_desktop.config import DesktopConfig
from strmaction_desktop.mpv import MpvError


@dataclass
class FakeApp:
    config: DesktopConfig
    logger: object = None
    played: list | None = None
    stopped: int = 0
    settings_saved: dict | None = None
    play_error: Exception | None = None

    def __post_init__(self):
        self.played = []

    def play(self, payload):
        if self.play_error is not None:
            raise self.play_error
        self.played.append(payload)

    def stop_playback(self):
        self.stopped += 1

    def open_settings(self):
        pass

    def detected_mpv(self):
        return "/usr/local/bin/mpv"

    def save_settings(self, data):
        self.settings_saved = data

    def choose_mpv(self):
        return "/opt/homebrew/bin/mpv"

    def shutdown(self):
        pass


def _payload():
    return {
        "item_id": 42,
        "play_url": "https://pan.example.com/video.m3u8",
        "headers": {"User-Agent": "pan.baidu.com"},
        "play_token": "pt_abcdefghijklmnopqrstuvwxyz123456",
        "resume_ms": 0,
        "progress_interval_ms": 5000,
        "subtitles": [],
    }


def test_bridge_play_payload():
    app = FakeApp(DesktopConfig(server_url="https://media.example.com"))
    bridge = DesktopBridge(app)
    assert bridge.isDesktop() is True
    result = bridge.playItem(json.dumps(_payload()))
    assert result["ok"] is True
    assert len(app.played) == 1
    assert app.played[0].item_id == 42


def test_bridge_rejects_invalid_payload():
    app = FakeApp(DesktopConfig(server_url="https://media.example.com"))
    bridge = DesktopBridge(app)
    result = bridge.playItem(json.dumps({"item_id": 0}))
    assert result["ok"] is False
    assert result["error"]


def test_bridge_reports_mpv_error():
    app = FakeApp(
        DesktopConfig(server_url="https://media.example.com"),
        play_error=MpvError("未找到 mpv"),
    )
    bridge = DesktopBridge(app)
    result = bridge.playItem(json.dumps(_payload()))
    assert result["ok"] is False
    assert result["error"] == "未找到 mpv"


def test_bridge_settings_and_actions():
    app = FakeApp(
        DesktopConfig(server_url="https://media.example.com", mpv_path="/mpv")
    )
    bridge = DesktopBridge(app)
    settings = bridge.get_settings()
    assert settings["server_url"] == "https://media.example.com"
    assert settings["mpv_path"] == "/mpv"
    assert settings["cache_limit_mb"] == 128
    assert settings["detected_mpv"] == "/usr/local/bin/mpv"
    assert bridge.save_settings({"server_url": "https://x.test"})["ok"] is True
    assert app.settings_saved["server_url"] == "https://x.test"
    assert bridge.stopPlayback()["ok"] is True
    assert app.stopped == 1
    assert bridge.choose_mpv()["path"] == "/opt/homebrew/bin/mpv"
