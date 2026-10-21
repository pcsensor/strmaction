"""StrmAction desktop entry point.

The window is a WebView around the existing web UI. Python is deliberately a
thin playback agent: it receives an already-authorized /api/play payload from
the web page, starts local mpv, and reports progress with the item play_token.
"""

from __future__ import annotations

import argparse
import inspect
import json
import ssl
import sys
import threading
from pathlib import Path
from threading import RLock
from urllib.parse import urlparse

import httpx

try:
    import webview  # type: ignore
except ImportError:  # pragma: no cover - only hit without runtime deps
    webview = None

from .bridge import DesktopBridge
from .config import (
    ConfigError,
    DesktopConfig,
    app_data_dir,
    log_dir,
    normalize_server_url,
    webview_storage_dir,
)
from .logging_setup import setup_logging
from .mpv import MpvError, bundle_root, find_mpv
from .playback import PlaybackSession
from .security import PlaybackPayload
from .version import __version__


def assets_dir() -> Path:
    return Path(__file__).resolve().parent / "assets"


def settings_uri() -> str:
    return (assets_dir() / "settings.html").resolve().as_uri()


def loading_uri() -> str:
    return (assets_dir() / "loading.html").resolve().as_uri()


def error_uri() -> str:
    return (assets_dir() / "error.html").resolve().as_uri()


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
        self.bridge = DesktopBridge(self)
        self.window = None
        self._session: PlaybackSession | None = None
        self._play_lock = RLock()
        self._last_error = ""
        self._startup_check_started = False
        self._webview_allow_self_signed = False

    # -- playback ------------------------------------------------------
    def detected_mpv(self) -> str | None:
        return find_mpv(self.config.mpv_path, bundle_root())

    def play(self, payload: PlaybackPayload) -> None:
        mpv = self.detected_mpv()
        if not mpv:
            raise MpvError(
                "未找到 mpv。请安装 mpv，或在桌面端设置中选择 mpv 可执行文件。"
            )
        self.stop_playback()
        session = PlaybackSession(
            payload,
            mpv,
            server_url=self.config.server_url,
            cache_limit_mb=self.config.cache_limit_mb,
            allow_self_signed_https=self.config.allow_self_signed_https,
            logger=self.logger,
            on_auth_error=self._on_progress_auth_error,
        )
        with self._play_lock:
            self._session = session
        try:
            session.start()
        except Exception:
            with self._play_lock:
                self._session = None
            raise
        self.logger.info("开始播放 item=%s", payload.item_id)

    def stop_playback(self) -> None:
        with self._play_lock:
            session = self._session
            self._session = None
        if session is not None:
            session.stop()

    def _on_progress_auth_error(self) -> None:
        self.logger.warning("播放进度凭证已失效，请从网页重新打开播放")

    # -- server connection ---------------------------------------------
    @property
    def last_error(self) -> str:
        return self._last_error

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
                    "HTTPS 证书校验失败。请在服务器设置中开启"
                    "“允许所有自签名 HTTPS 证书”，然后重启桌面端。",
                )
            return False, "无法连接服务器，请检查地址、端口和服务器状态。"
        except httpx.HTTPError as exc:
            return False, f"连接服务器失败：{type(exc).__name__}"
        except Exception as exc:
            return False, f"连接服务器失败：{type(exc).__name__}"

    def _startup_check(self) -> None:
        ok, message = self.check_connection()
        if self.window is None:
            return
        if ok:
            self._last_error = ""
            if self.logger:
                self.logger.info("服务器连接正常：%s", self.config.server_url)
            try:
                self.window.load_url(self.config.server_url)
            except Exception as exc:  # pragma: no cover - GUI runtime
                if self.logger:
                    self.logger.warning("加载服务器页面失败：%s", type(exc).__name__)
        else:
            self._last_error = message
            if self.logger:
                self.logger.warning("服务器连接失败：%s", message)
            try:
                self.window.load_url(error_uri())
            except Exception as exc:  # pragma: no cover - GUI runtime
                if self.logger:
                    self.logger.warning("加载错误页失败：%s", type(exc).__name__)

    def retry_connection(self) -> None:
        if self.window is None:
            return
        self._last_error = ""
        try:
            self.window.load_url(loading_uri())
        except Exception as exc:  # pragma: no cover - GUI runtime
            if self.logger:
                self.logger.warning("加载连接中页面失败：%s", type(exc).__name__)
        threading.Thread(
            target=self._startup_check,
            name="strmaction-health",
            daemon=True,
        ).start()

    # -- settings ------------------------------------------------------
    def open_settings(self) -> None:
        if self.window is not None:
            self.window.load_url(settings_uri())

    def save_settings(self, data: dict) -> bool:
        server = normalize_server_url(str(data.get("server_url") or ""))
        mpv_path = str(data.get("mpv_path") or "").strip()
        try:
            cache_limit = int(
                data.get("cache_limit_mb", self.config.cache_limit_mb)
            )
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
            mpv_path=mpv_path,
            cache_limit_mb=cache_limit,
            allow_self_signed_https=allow_self_signed,
            window_width=self.config.window_width,
            window_height=self.config.window_height,
            log_level=self.config.log_level,
        ).normalized()
        self.config.save()
        self.logger.info("桌面端设置已保存，服务器=%s", server)
        restart_required = allow_self_signed != self._webview_allow_self_signed
        if self.window is not None and not restart_required:
            self.retry_connection()
        return restart_required

    def choose_mpv(self) -> str | None:
        if self.window is None:
            return None
        dialog_type = getattr(getattr(webview, "FileDialog", None), "OPEN", None)
        if dialog_type is None:
            dialog_type = webview.OPEN_DIALOG
        result = self.window.create_file_dialog(dialog_type, allow_multiple=False)
        if not result:
            return None
        path = result[0] if isinstance(result, (list, tuple)) else result
        candidate = Path(str(path)).expanduser()
        if candidate.is_file():
            return str(candidate)
        return None

    # -- lifecycle -----------------------------------------------------
    def shutdown(self) -> None:
        self.stop_playback()
        if self.window is not None:
            try:
                self.window.destroy()
            except Exception:
                pass

    def _on_closing(self) -> None:
        self.stop_playback()

    def _on_before_load(self, url: str = "", *args) -> bool:
        """Keep the JS bridge on the configured server (or local settings page)."""
        if not url or url == "about:blank":
            return True
        if (
            url.startswith(settings_uri())
            or url.startswith(loading_uri())
            or url.startswith(error_uri())
        ):
            return True

        target = urlparse(url)
        server = urlparse(self.config.server_url)
        return bool(
            server.scheme
            and server.netloc
            and target.scheme == server.scheme
            and target.netloc == server.netloc
        )

    def _on_loading_loaded(self, *args) -> None:
        """Start the health check only after the loading window exists."""
        if self._startup_check_started:
            return
        self._startup_check_started = True
        threading.Thread(
            target=self._startup_check,
            name="strmaction-health",
            daemon=True,
        ).start()

    def _install_desktop_bridge(self, *args) -> None:
        """Expose the same window.StrmActionNative shape the web UI expects."""
        if self.window is None:
            return
        script = """
        (() => {
          const call = (name, ...args) => {
            const api = window.pywebview && window.pywebview.api;
            if (!api || typeof api[name] !== 'function') {
              return Promise.reject(new Error('桌面端桥接未就绪'));
            }
            return api[name](...args);
          };
          window.StrmActionNative = {
            isDesktop: () => true,
            version: () => %s,
            playItem: (payload) => call('playItem', payload),
            stopPlayback: () => call('stopPlayback'),
            openSettings: () => call('openSettings'),
            quit: () => call('quit'),
          };
          window.dispatchEvent(new Event('strmaction:desktop-ready'));
        })();
        """ % json.dumps(__version__)
        try:
            self.window.evaluate_js(script)
        except Exception as exc:
            self.logger.warning("注入桌面端桥接失败：%s", type(exc).__name__)

    def run(self, *, start_with_settings: bool, debug: bool = False) -> None:
        if webview is None:
            raise RuntimeError(
                "缺少 pywebview。请先执行：pip install -r requirements.txt"
            )
        # This must be set before the WebView2 backend is initialized. It makes
        # WebView2 skip certificate errors for StrmAction and every Alist/CDN
        # HTTPS request loaded inside the webview.
        settings = getattr(webview, "settings", None)
        if settings is not None and "IGNORE_SSL_ERRORS" in settings:
            settings["IGNORE_SSL_ERRORS"] = bool(
                self.config.allow_self_signed_https
            )
        self._webview_allow_self_signed = bool(
            self.config.allow_self_signed_https
        )
        needs_check = not start_with_settings and bool(self.config.server_url)
        start_url = loading_uri() if needs_check else settings_uri()
        self.window = webview.create_window(
            "StrmAction",
            start_url,
            js_api=self.bridge,
            width=self.config.window_width,
            height=self.config.window_height,
            min_size=(900, 640),
            text_select=True,
            background_color="#07080a",
        )
        self.window.events.closing += self._on_closing
        self.window.events.before_load += self._on_before_load
        self.window.events.loaded += self._install_desktop_bridge
        if needs_check:
            # pywebview starts func before creating the native window; wait
            # for the loading page's loaded event instead.
            self.window.events.loaded += self._on_loading_loaded

        kwargs: dict = {"debug": debug}
        params = inspect.signature(webview.start).parameters
        if "private_mode" in params:
            kwargs["private_mode"] = False
        if "storage_path" in params:
            webview_storage_dir().mkdir(parents=True, exist_ok=True)
            kwargs["storage_path"] = str(webview_storage_dir())
        if "icon" in params and icon_path().is_file():
            kwargs["icon"] = str(icon_path())
        webview.start(**kwargs)


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="strmaction-desktop")
    parser.add_argument("--server", help="StrmAction 服务器地址，例如 https://media.example.com")
    parser.add_argument("--mpv", help="mpv 可执行文件路径")
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
    if args.mpv:
        config.mpv_path = args.mpv
    try:
        config = config.normalized()
        if args.server or args.mpv:
            config.save()
    except (ConfigError, OSError) as exc:
        logger.error("配置保存失败：%s", exc)
        return 2

    logger.info("StrmAction Desktop %s，数据目录=%s", __version__, app_data_dir())
    if webview is None:
        logger.error("缺少 pywebview，请执行：pip install -r requirements.txt")
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
