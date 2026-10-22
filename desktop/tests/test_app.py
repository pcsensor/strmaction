from __future__ import annotations


from strmaction_desktop.app import DesktopApp, assets_dir, icon_path
from strmaction_desktop.config import DesktopConfig
from strmaction_desktop.qt_window import is_allowed_url


class FakeLogger:
    def info(self, *args, **kwargs):
        pass

    def warning(self, *args, **kwargs):
        pass

    def error(self, *args, **kwargs):
        pass


def _app(server="https://media.example.com"):
    return DesktopApp(DesktopConfig(server_url=server), logger=FakeLogger())


def test_assets_dir_contains_error_page():
    assets = assets_dir()
    assert (assets / "error.html").is_file()
    assert icon_path().suffix in {".ico", ".icns", ".png"}


def test_save_settings_updates_cache_limit(monkeypatch):
    app = _app()
    monkeypatch.setattr(DesktopConfig, "save", lambda self, path=None: None)
    changed = app.save_settings(
        {
            "server_url": "https://media.example.com",
            "cache_limit_mb": 64,
        }
    )
    assert app.config.cache_limit_mb == 64
    assert changed is False


def test_save_settings_reports_server_change(monkeypatch):
    app = _app()
    monkeypatch.setattr(DesktopConfig, "save", lambda self, path=None: None)
    changed = app.save_settings(
        {"server_url": "https://other.example.com", "cache_limit_mb": 128}
    )
    assert changed is True
    assert app.config.server_url == "https://other.example.com"


def test_self_signed_switch_applies_without_restart(monkeypatch):
    app = _app()
    monkeypatch.setattr(DesktopConfig, "save", lambda self, path=None: None)
    app.save_settings(
        {
            "server_url": "https://media.example.com",
            "cache_limit_mb": 128,
            "allow_self_signed_https": True,
        }
    )
    assert app.config.allow_self_signed_https is True


def test_navigation_is_limited_to_server_origin():
    server = "https://media.example.com"

    assert is_allowed_url(server, "https://media.example.com/item/42") is True
    assert is_allowed_url(server, "https://media.example.com.evil.test/") is False
    assert is_allowed_url(server, "https://evil.example.com/") is False
    assert is_allowed_url(server, "about:blank") is True
    assert is_allowed_url(server, (assets_dir() / "error.html").as_uri()) is True


def test_cert_error_detection():
    import ssl

    error = ssl.SSLCertVerificationError("certificate verify failed")
    assert DesktopApp._is_cert_error(error) is True
