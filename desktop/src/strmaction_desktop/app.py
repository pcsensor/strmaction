"""StrmAction desktop entry point.

The window is a WebView around the existing web UI. Python is deliberately a
thin playback agent: it receives an already-authorized /api/play payload from
the web page, starts local mpv, and reports progress with the item play_token.
"""

from __future__ import annotations

import argparse
import inspect
import json
import sys
from pathlib import Path
from threading import RLock

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

    # -- settings ------------------------------------------------------
    def open_settings(self) -> None:
        if self.window is not None:
            self.window.load_url(settings_uri())

    def save_settings(self, data: dict) -> None:
        server = normalize_server_url(str(data.get("server_url") or ""))
        mpv_path = str(data.get("mpv_path") or "").strip()
        try:
            cache_limit = int(
                data.get("cache_limit_mb", self.config.cache_limit_mb)
            )
        except (TypeError, ValueError):
            cache_limit = self.config.cache_limit_mb
        self.config = DesktopConfig(
            server_url=server,
            mpv_path=mpv_path,
            cache_limit_mb=cache_limit,
            window_width=self.config.window_width,
            window_height=self.config.window_height,
            log_level=self.config.log_level,
        ).normalized()
        self.config.save()
        self.logger.info("桌面端设置已保存，服务器=%s", server)
        if self.window is not None:
            self.window.load_url(self.config.server_url)

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
        if url.startswith(settings_uri()):
            return True
        from urllib.parse import urlparse

        target = urlparse(url)
        server = urlparse(self.config.server_url)
        return bool(
            server.scheme
            and server.netloc
            and target.scheme == server.scheme
            and target.netloc == server.netloc
        )

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
        start_url = (
            settings_uri()
            if start_with_settings or not self.config.server_url
            else self.config.server_url
        )
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
