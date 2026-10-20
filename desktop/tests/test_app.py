from __future__ import annotations

from strmaction_desktop.app import DesktopApp, settings_uri
from strmaction_desktop.config import DesktopConfig


class FakeWindow:
    def __init__(self):
        self.scripts: list[str] = []

    def evaluate_js(self, script: str):
        self.scripts.append(script)
        return None


def _app(server="https://media.example.com"):
    return DesktopApp(DesktopConfig(server_url=server), logger=None)


def test_desktop_bridge_shim_is_installed():
    app = _app()
    window = FakeWindow()
    app.window = window
    app._install_desktop_bridge()
    assert len(window.scripts) == 1
    script = window.scripts[0]
    assert "window.StrmActionNative" in script
    assert "isDesktop" in script
    assert "playItem" in script
    assert "openSettings" in script
    assert "strmaction:desktop-ready" in script
    assert "0.1.0" in script


def test_navigation_is_limited_to_server_and_settings_page():
    app = _app()
    assert app._on_before_load(settings_uri()) is True
    assert app._on_before_load("https://media.example.com/item/42") is True
    assert app._on_before_load("https://media.example.com.evil.test/") is False
    assert app._on_before_load("https://evil.example.com/") is False
    assert app._on_before_load("about:blank") is True


def test_save_settings_updates_cache_limit(monkeypatch):
    class FakeLogger:
        def info(self, *args, **kwargs):
            pass

    app = DesktopApp(DesktopConfig(server_url="https://media.example.com"), logger=FakeLogger())
    monkeypatch.setattr(DesktopConfig, "save", lambda self, path=None: None)
    app.save_settings(
        {
            "server_url": "https://media.example.com",
            "mpv_path": "/usr/bin/mpv",
            "cache_limit_mb": 64,
        }
    )
    assert app.config.cache_limit_mb == 64
