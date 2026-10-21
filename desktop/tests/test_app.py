from __future__ import annotations

from strmaction_desktop.app import (
    DesktopApp,
    error_uri,
    loading_uri,
    settings_uri,
)
from strmaction_desktop.config import DesktopConfig


class FakeWindow:
    def __init__(self):
        self.scripts: list[str] = []
        self.urls: list[str] = []

    def evaluate_js(self, script: str):
        self.scripts.append(script)
        return None

    def load_url(self, url: str):
        self.urls.append(url)


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
    assert app._on_before_load(loading_uri()) is True
    assert app._on_before_load(error_uri()) is True
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


def test_enabling_self_signed_requires_restart(monkeypatch):
    class FakeLogger:
        def info(self, *args, **kwargs):
            pass

    app = DesktopApp(DesktopConfig(server_url="https://media.example.com"), logger=FakeLogger())
    monkeypatch.setattr(DesktopConfig, "save", lambda self, path=None: None)
    restart = app.save_settings(
        {
            "server_url": "https://media.example.com",
            "mpv_path": "/usr/bin/mpv",
            "cache_limit_mb": 128,
            "allow_self_signed_https": True,
        }
    )
    assert restart is True
    assert app.config.allow_self_signed_https is True


def test_startup_check_shows_error_page(monkeypatch):
    app = _app()
    window = FakeWindow()
    app.window = window
    monkeypatch.setattr(app, "check_connection", lambda: (False, "无法连接服务器"))
    app._startup_check()
    assert window.urls[-1] == error_uri()
    assert app.last_error == "无法连接服务器"


def test_startup_check_loads_server_on_success(monkeypatch):
    app = _app()
    window = FakeWindow()
    app.window = window
    monkeypatch.setattr(app, "check_connection", lambda: (True, ""))
    app._startup_check()
    assert window.urls[-1] == "https://media.example.com"
    assert app.last_error == ""


def test_save_settings_checks_connection(monkeypatch):
    class FakeLogger:
        def info(self, *args, **kwargs):
            pass

    app = DesktopApp(DesktopConfig(server_url="https://media.example.com"), logger=FakeLogger())
    window = FakeWindow()
    app.window = window
    called: list[bool] = []
    monkeypatch.setattr(DesktopConfig, "save", lambda self, path=None: None)
    monkeypatch.setattr(app, "retry_connection", lambda: called.append(True))
    app.save_settings(
        {
            "server_url": "https://media.example.com",
            "mpv_path": "/usr/bin/mpv",
            "cache_limit_mb": 128,
        }
    )
    assert called == [True]


def test_cert_error_detection():
    import ssl

    error = ssl.SSLCertVerificationError("certificate verify failed")
    assert DesktopApp._is_cert_error(error) is True
