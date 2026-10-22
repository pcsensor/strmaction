"""PySide6 main window with QWebEngineView (Web) and PlayerView (Embedded Player)."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from PySide6.QtCore import QFile, QIODevice, QObject, QUrl, Qt, Slot
from PySide6.QtGui import QIcon
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtWebEngineCore import (
    QWebEnginePage,
    QWebEngineProfile,
    QWebEngineScript,
    QWebEngineSettings,
)
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QMainWindow, QStackedWidget, QWidget

from .config import DesktopConfig, webview_storage_dir
from .progress import ProgressReporter
from .proxy import get_proxy
from .player import PlayerView
from .security import PlaybackPayload, config_error_message, parse_payload
from .version import __version__


class WebChannelBridge(QObject):
    """QWebChannel bridge exposed to the Web page."""

    def __init__(self, main_window: MainWindow):
        super().__init__()
        self._win = main_window

    @Slot(result=bool)
    def isDesktop(self) -> bool:
        return True

    @Slot(result=str)
    def version(self) -> str:
        return __version__

    @Slot(str, result=str)
    def playItem(self, payload_json: str) -> str:
        try:
            raw = json.loads(payload_json) if isinstance(payload_json, str) else payload_json
            parsed = parse_payload(raw, self._win.app.config.server_url)
            self._win.play_embedded(parsed)
            return json.dumps({"ok": True})
        except Exception as exc:
            return json.dumps({"ok": False, "error": config_error_message(exc)})

    @Slot(result=str)
    def stopPlayback(self) -> str:
        self._win.close_player_and_return_to_web()
        return json.dumps({"ok": True})

    @Slot(result=str)
    def openSettings(self) -> str:
        self._win.open_settings_page()
        return json.dumps({"ok": True})

    @Slot(result=str)
    def get_settings(self) -> str:
        cfg = self._win.app.config
        return json.dumps({
            "ok": True,
            "server_url": cfg.server_url,
            "cache_limit_mb": cfg.cache_limit_mb,
            "allow_self_signed_https": cfg.allow_self_signed_https,
            "version": __version__,
        })

    @Slot(str, result=str)
    def save_settings(self, data_json: str) -> str:
        try:
            data = json.loads(data_json) if isinstance(data_json, str) else {}
            restart = self._win.app.save_settings(data)
            return json.dumps({"ok": True, "restart_required": restart})
        except Exception as exc:
            return json.dumps({"ok": False, "error": config_error_message(exc)})

    @Slot(result=str)
    def choose_mpv(self) -> str:
        return json.dumps({"ok": True, "path": ""})

    @Slot(result=str)
    def retryConnection(self) -> str:
        self._win.retry_connection()
        return json.dumps({"ok": True})

    @Slot(result=str)
    def getConnectionError(self) -> str:
        return json.dumps({"ok": True, "error": self._win.app.last_error})

    @Slot(result=str)
    def quit(self) -> str:
        self._win.close()
        return json.dumps({"ok": True})


class MainWindow(QMainWindow):
    def __init__(self, app_instance, start_with_settings: bool = False):
        super().__init__()
        self.app = app_instance
        self.setWindowTitle("StrmAction")
        self.resize(self.app.config.window_width, self.app.config.window_height)
        self.setMinimumSize(900, 640)

        self._active_stream_id: str | None = None

        # Main stacked layout: 0 = Web, 1 = Embedded Player
        self.stack = QStackedWidget(self)
        self.setCentralWidget(self.stack)

        self._init_web_page()
        self._init_player_page()

        if start_with_settings or not self.app.config.is_configured():
            self.open_settings_page()
        else:
            self.load_server_url()

    def _init_web_page(self) -> None:
        self.web = QWebEngineView(self)
        page = self.web.page()

        # Storage persistence for cookies and sessions
        profile = page.profile()
        storage_dir = str(webview_storage_dir())
        profile.setPersistentStoragePath(storage_dir)

        # Allow self-signed certificates if configured
        if self.app.config.allow_self_signed_https:
            page.certificateError.connect(lambda err: err.acceptCertificate())

        # WebChannel setup
        self.channel = QWebChannel(page)
        self.bridge_obj = WebChannelBridge(self)
        self.channel.registerObject("backend", self.bridge_obj)
        page.setWebChannel(self.channel)

        # Inject qwebchannel.js and bridge shim into every page at DocumentReady
        self._inject_bridge_script(profile)

        self.stack.addWidget(self.web)

    def _inject_bridge_script(self, profile: QWebEngineProfile) -> None:
        # Read qwebchannel.js from Qt resources
        qfile = QFile(":/qtwebchannel/qwebchannel.js")
        qwebchannel_content = ""
        if qfile.open(QIODevice.OpenModeFlag.ReadOnly):
            qwebchannel_content = bytes(qfile.readAll()).decode("utf-8")
            qfile.close()

        script_code = f"""
        {qwebchannel_content}
        (function() {{
            if (typeof QWebChannel === 'undefined') return;
            new QWebChannel(qt.webChannelTransport, function(channel) {{
                window._strmaction_bridge = channel.objects.backend;
                const call = (method, ...args) => {{
                    return new Promise((resolve, reject) => {{
                        if (!window._strmaction_bridge || !window._strmaction_bridge[method]) {{
                            return reject(new Error('桌面端桥接未就绪'));
                        }}
                        window._strmaction_bridge[method](...args, (res) => {{
                            try {{
                                resolve(typeof res === 'string' ? JSON.parse(res) : res);
                            }} catch(e) {{
                                resolve(res);
                            }}
                        }});
                    }});
                }};
                const apiObj = {{
                    isDesktop: () => true,
                    version: () => "{__version__}",
                    playItem: (payload) => call('playItem', typeof payload === 'string' ? payload : JSON.stringify(payload)),
                    stopPlayback: () => call('stopPlayback'),
                    openSettings: () => call('openSettings'),
                    get_settings: () => call('get_settings'),
                    save_settings: (data) => call('save_settings', JSON.stringify(data)),
                    choose_mpv: () => call('choose_mpv'),
                    retryConnection: () => call('retryConnection'),
                    getConnectionError: () => call('getConnectionError'),
                    quit: () => call('quit'),
                }};
                window.pywebview = {{ api: apiObj }};
                window._strmaction_api = apiObj;
                window.StrmActionNative = {{
                    isDesktop: () => true,
                    version: () => "{__version__}",
                    playItem: (payload) => apiObj.playItem(payload),
                    stopPlayback: () => apiObj.stopPlayback(),
                    openSettings: () => apiObj.openSettings(),
                    quit: () => apiObj.quit(),
                }};
                window.dispatchEvent(new Event('pywebviewready'));
                window.dispatchEvent(new Event('strmaction:desktop-ready'));
            }});
        }})();
        """
        user_script = QWebEngineScript()
        user_script.setName("StrmActionBridge")
        user_script.setSourceCode(script_code)
        user_script.setInjectionPoint(QWebEngineScript.InjectionPoint.DocumentReady)
        user_script.setWorldId(QWebEngineScript.ScriptWorldId.MainWorld)
        user_script.setRunsOnSubFrames(False)
        profile.scripts().insert(user_script)

    def _init_player_page(self) -> None:
        self.player_view = PlayerView(self)
        self.player_view.exit_requested.connect(self.close_player_and_return_to_web)
        self.player_view.next_episode_requested.connect(self.request_play_item)
        self.stack.addWidget(self.player_view)

    def load_url(self, url: str) -> None:
        """Universal URL loader for server, local files or web pages."""
        if not url:
            return
        if url.startswith("http://") or url.startswith("https://") or url.startswith("file://"):
            self.web.setUrl(QUrl(url))
        else:
            self.web.setUrl(QUrl.fromLocalFile(url))

    def load_server_url(self) -> None:
        url = self.app.config.server_url
        if url:
            self.load_url(url)
        else:
            self.open_settings_page()

    def open_settings_page(self) -> None:
        assets_dir = Path(__file__).resolve().parent / "assets"
        settings_path = assets_dir / "settings.html"
        self.load_url(str(settings_path))

    def retry_connection(self) -> None:
        ok, msg = self.app.check_connection()
        if ok:
            self.load_server_url()
        else:
            assets_dir = Path(__file__).resolve().parent / "assets"
            error_path = assets_dir / "error.html"
            self.load_url(str(error_path))

    def play_embedded(self, payload: PlaybackPayload) -> None:
        self.close_player_and_return_to_web()

        # Switch to player page
        self.stack.setCurrentWidget(self.player_view)

        # Register stream with local loopback proxy
        proxy = get_proxy()
        stream_id = f"stream_{payload.item_id}_{int(time.time() * 1000)}"
        self._active_stream_id = stream_id
        local_url = proxy.register_stream(stream_id, payload.play_url, payload.headers)

        # Create progress reporter
        reporter = ProgressReporter(
            server_url=self.app.config.server_url,
            item_id=payload.item_id,
            play_token=payload.play_token,
            interval_ms=payload.progress_interval_ms,
            verify_ssl=not self.app.config.allow_self_signed_https,
            logger=self.app.logger,
            on_auth_error=self.app._on_progress_auth_error,
        )
        reporter.start()

        # Load playback in PlayerView
        self.player_view.load_playback(payload, local_url, reporter=reporter)
        if self.app.logger:
            self.app.logger.info("内嵌原生播放开始 item=%s, url=%s", payload.item_id, local_url)

    def close_player_and_return_to_web(self) -> None:
        self.player_view.stop_playback()
        if self._active_stream_id:
            get_proxy().unregister_stream(self._active_stream_id)
            self._active_stream_id = None

        if self.isFullScreen():
            self.showNormal()
        self.stack.setCurrentWidget(self.web)
        self.web.setFocus()

    def request_play_item(self, item_id: int) -> None:
        # Trigger play for next episode via web JS bridge
        js_code = f"""
        if (typeof window.dispatchEvent !== 'undefined') {{
            window.dispatchEvent(new CustomEvent('strmaction:request-play', {{ detail: {{ itemId: {item_id} }} }}));
        }}
        """
        self.web.page().runJavaScript(js_code)

    def closeEvent(self, event) -> None:
        self.close_player_and_return_to_web()
        cfg = self.app.config
        cfg.window_width = self.width()
        cfg.window_height = self.height()
        try:
            cfg.save()
        except Exception:
            pass
        super().closeEvent(event)
