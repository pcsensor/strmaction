"""StrmAction desktop entry point.

The window is a Qt WebEngine view around the existing web UI. Python is
deliberately a thin playback agent: it receives an already-authorized /api/play
payload from the web page, plays it with Qt Multimedia, and reports progress
with the item play_token.
"""

from __future__ import annotations

import argparse
import ssl
import sys
import threading
from pathlib import Path
from urllib.parse import urlparse

import httpx

from .config import (
    APP_NAME,
    ConfigError,
    DesktopConfig,
    app_data_dir,
    log_dir,
    normalize_server_url,
)
from .logging_setup import setup_logging
from .proxy import configure_proxy_tls
from .version import __version__


def assets_dir() -> Path:
    return Path(__file__).resolve().parent / "assets"


def icon_path() -> Path:
    if sys.platform.startswith("win"):
        return assets_dir() / "icon.ico"
    if sys.platform == "darwin":
        return assets_dir() / "icon.icns"
    return assets_dir() / "icon.png"


class DesktopApp:
    def __init__(self, config: DesktopConfig, logger):
        self.config = config
        self.logger = logger
        self.window = None
        self.last_error = ""

    # -- paths ---------------------------------------------------------
    @property
    def assets_dir(self) -> Path:
        return assets_dir()

    # -- playback ------------------------------------------------------
    def stop_playback(self) -> None:
        window = self.window
        if window is not None and hasattr(window, "close_player_and_return_to_web"):
            try:
                window.close_player_and_return_to_web()
            except Exception:
                pass

    def _on_progress_auth_error(self) -> None:
        self.logger.warning("播放进度凭证已失效，请从网页重新打开播放")

    # -- server connection ---------------------------------------------
    @staticmethod
    def _is_cert_error(error: BaseException) -> bool:
        seen: set[int] = set()
        current: BaseException | None = error
        while current is not None and id(current) not in seen:
            if isinstance(current, ssl.SSLError):
                return True
            seen.add(id(current))
            current = current.__cause__ or current.__context__
        return False

    def check_connection(self) -> tuple[bool, str]:
        """Check /api/health without requiring a window."""
        if not self.config.server_url:
            return False, "尚未配置服务器地址"
        url = f"{self.config.server_url.rstrip('/')}/api/health"
        try:
            verify = (
                False
                if self.config.allow_self_signed_https
                else ssl.create_default_context()
            )
            with httpx.Client(
                timeout=httpx.Timeout(5.0, connect=3.0),
                follow_redirects=True,
                # Default: OS trust store. If the global self-signed switch is
                # on, skip certificate validation for every HTTPS endpoint.
                verify=verify,
            ) as client:
                response = client.get(
                    url,
                    headers={"X-StrmAction-Companion": "1"},
                )
            if response.status_code not in range(200, 300):
                return False, f"服务器返回 HTTP {response.status_code}"
            try:
                payload = response.json()
            except ValueError:
                return False, "服务器响应不是合法 JSON"
            if not isinstance(payload, dict) or not payload.get("ok", False):
                return False, "服务未就绪"
            return True, ""
        except httpx.TimeoutException:
            return False, "连接服务器超时，请检查服务器是否启动。"
        except httpx.ConnectError as exc:
            if self._is_cert_error(exc):
                return (
                    False,
                    "HTTPS 证书校验失败。请在桌面端设置中开启"
                    "“允许自签名 HTTPS 证书”。",
                )
            return False, "无法连接服务器，请检查地址、端口和服务器状态。"
        except httpx.HTTPError as exc:
            return False, f"连接服务器失败：{type(exc).__name__}"
        except Exception as exc:
            return False, f"连接服务器失败：{type(exc).__name__}"

    def retry_connection(self) -> None:
        if self.window is None:
            return
        self.last_error = ""
        self.window.retry_connection()

    # -- settings ------------------------------------------------------
    def open_settings(self) -> None:
        if self.window is not None and hasattr(self.window, "open_settings_page"):
            self.window.open_settings_page()

    def save_settings(self, data: dict) -> bool:
        """Persist settings and apply them live.

        Returns True when the server address changed (the caller reloads the
        web view); every other change is applied without a reload.
        """
        previous_server = self.config.server_url
        server = normalize_server_url(str(data.get("server_url") or ""))
        try:
            cache_limit = int(data.get("cache_limit_mb", self.config.cache_limit_mb))
        except (TypeError, ValueError):
            cache_limit = self.config.cache_limit_mb
        allow_self_signed = bool(
            data.get(
                "allow_self_signed_https",
                self.config.allow_self_signed_https,
            )
        )
        self.config = DesktopConfig(
            server_url=server,
            cache_limit_mb=cache_limit,
            allow_self_signed_https=allow_self_signed,
            window_width=self.config.window_width,
            window_height=self.config.window_height,
            log_level=self.config.log_level,
        ).normalized()
        self.config.save()
        # Streaming proxy + certificate handler pick the new policy up live.
        configure_proxy_tls(not self.config.allow_self_signed_https)
        self.logger.info("桌面端设置已保存，服务器=%s", server)
        return self.config.server_url != previous_server

    # -- lifecycle -----------------------------------------------------
    def shutdown(self) -> None:
        self.stop_playback()
        if self.window is not None:
            try:
                self.window.close()
            except Exception:
                pass

    def run(self, *, start_with_settings: bool, debug: bool = False) -> None:
        from PySide6.QtCore import QCoreApplication, Qt
        from PySide6.QtGui import QIcon
        from PySide6.QtWidgets import QApplication

        from .qt_window import MainWindow

        # Stable storage locations for QtWebEngine (cookies, localStorage).
        QCoreApplication.setOrganizationName(APP_NAME)
        QCoreApplication.setApplicationName(APP_NAME)
        # QtWebEngine requires this before the application object exists once
        # other GPU-backed widgets (the video surface) live in the same window.
        QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts, True)

        qt_app = QApplication.instance() or QApplication(sys.argv)
        if icon_path().is_file():
            qt_app.setWindowIcon(QIcon(str(icon_path())))
        self.window = MainWindow(self, start_with_settings=start_with_settings)
        self.window.show()
        qt_app.exec()


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="strmaction-desktop")
    parser.add_argument("--server", help="StrmAction 服务器地址，例如 https://media.example.com")
    parser.add_argument("--settings", action="store_true", help="启动后直接打开桌面端设置")
    parser.add_argument("--debug", action="store_true", help="开启调试日志")
    parser.add_argument("--version", action="store_true", help="输出版本号")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    if args.version:
        print(f"StrmAction Desktop {__version__}")
        return 0

    logger = setup_logging(log_dir(), debug=args.debug)
    try:
        config = DesktopConfig.load()
    except ConfigError as exc:
        logger.warning("配置读取失败：%s", exc)
        config = DesktopConfig()

    if args.server:
        try:
            config.server_url = normalize_server_url(args.server)
        except ConfigError as exc:
            logger.error("--server 参数无效：%s", exc)
            return 2
    try:
        config = config.normalized()
        if args.server:
            config.save()
    except (ConfigError, OSError) as exc:
        logger.error("配置保存失败：%s", exc)
        return 2

    logger.info("StrmAction Desktop %s，数据目录=%s", __version__, app_data_dir())
    try:
        import PySide6  # noqa: F401
    except ImportError:
        logger.error("缺少 PySide6，请执行：pip install -r requirements.txt")
        return 2

    app = DesktopApp(config, logger)
    try:
        app.run(
            start_with_settings=args.settings or not config.is_configured(),
            debug=args.debug,
        )
    except Exception as exc:  # pragma: no cover - GUI startup
        logger.exception("桌面端启动失败：%s", exc)
        return 1
    finally:
        app.stop_playback()
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
