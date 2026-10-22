"""PySide6 main window with QWebEngineView (Web) and PlayerView (Embedded Player)."""

from __future__ import annotations

import json
import ssl
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
from .mpv import MpvError
from .playback import PlaybackSession
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
            msg = str(exc) if isinstance(exc, MpvError) else config_error_message(exc)
            return json.dumps({"ok": False, "error": msg})

    @Slot(result=str)
    def stopPlayback(self) -> str:
        self._win.app.stop_playback()
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
            "mpv_path": cfg.mpv_path,
            "cache_limit_mb": cfg.cache_limit_mb,
            "allow_self_signed_https": cfg.allow_self_signed_https,
            "detected_mpv": self._win.app.detected_mpv() or "",
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
        path = self._win.app.choose_mpv()
        return json.dumps({"ok": True, "path": path or ""})

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
                window.pywebview = {{
                    api: {{
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
                    }}
                }};
                window.StrmActionNative = {{
                    isDesktop: () => true,
                    version: () => "{__version__}",
                    playItem: (payload) => window.pywebview.api.playItem(payload),
                    stopPlayback: () => window.pywebview.api.stopPlayback(),
                    openSettings: () => window.pywebview.api.openSettings(),
                    quit: () => window.pywebview.api.quit(),
                }};
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

    def load_server_url(self) -> None:
        url = self.app.config.server_url
        if url:
            self.web.setUrl(QUrl(url))
        else:
            self.open_settings_page()

    def open_settings_page(self) -> None:
        assets_dir = Path(__file__).resolve().parent / "assets"
        settings_path = assets_dir / "settings.html"
        self.web.setUrl(QUrl.fromLocalFile(str(settings_path)))

    def retry_connection(self) -> None:
        ok, msg = self.app.check_connection()
        if ok:
            self.load_server_url()
        else:
            assets_dir = Path(__file__).resolve().parent / "assets"
            error_path = assets_dir / "error.html"
            self.web.setUrl(QUrl.fromLocalFile(str(error_path)))

    def play_embedded(self, payload: PlaybackPayload) -> None:
        mpv = self.app.detected_mpv()
        if not mpv:
            raise MpvError("未找到 mpv。请安装 mpv，或在桌面端设置中选择 mpv 可执行文件。")

        self.app.stop_playback()

        # Switch to player page
        self.stack.setCurrentWidget(self.player_view)
        wid = self.player_view.get_video_wid()

        # Create session with callbacks
        session = PlaybackSession(
            payload,
            mpv,
            server_url=self.app.config.server_url,
            cache_limit_mb=self.app.config.cache_limit_mb,
            allow_self_signed_https=self.app.config.allow_self_signed_https,
            logger=self.app.logger,
            on_auth_error=self.app._on_progress_auth_error,
            on_position=self.player_view.on_mpv_position,
            on_duration=self.player_view.on_mpv_duration,
            on_paused=self.player_view.on_mpv_paused,
            on_speed=self.player_view.on_mpv_speed,
            on_cache_state=self.player_view.on_mpv_cache_state,
            on_tracks=self.player_view.on_mpv_tracks,
            on_idle=self.player_view.on_mpv_idle,
            on_exited=self._on_mpv_exited,
        )

        with self.app._play_lock:
            self.app._session = session

        self.player_view.bind_controller(session.controller, payload)
        session.start(wid=wid)
        if self.app.logger:
            self.app.logger.info("内嵌播放开始 item=%s, wid=%s", payload.item_id, wid)

    def close_player_and_return_to_web(self) -> None:
        self.app.stop_playback()
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

    def _on_mpv_exited(self) -> None:
        # Return to web page when mpv exits
        if self.stack.currentWidget() == self.player_view:
            self.close_player_and_return_to_web()

    def closeEvent(self, event) -> None:
        self.app.stop_playback()
        super().closeEvent(event)
