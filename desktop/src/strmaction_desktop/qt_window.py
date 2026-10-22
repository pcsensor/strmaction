"""PySide6 main window: persistent web view + native embedded player."""

from __future__ import annotations

import json
import threading
import time
from urllib.parse import urlparse

from PySide6.QtCore import QFile, QIODevice, QObject, QUrl, Signal, Slot
from PySide6.QtGui import QDesktopServices
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtWebEngineCore import (
    QWebEngineCertificateError,
    QWebEnginePage,
    QWebEngineProfile,
    QWebEngineScript,
    QWebEngineSettings,
)
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QDialog, QMainWindow, QMessageBox, QStackedWidget

from .config import webview_cache_dir, webview_storage_dir
from .progress import ProgressReporter
from .proxy import get_proxy
from .player import PlayerView
from .security import PlaybackPayload, config_error_message, parse_payload
from .settings_dialog import SettingsDialog
from .version import __version__

PROFILE_NAME = "StrmAction"


def is_allowed_url(server_url: str, url: str) -> bool:
    """True when ``url`` may be loaded inside the app window."""
    if not url or url == "about:blank":
        return True
    server = urlparse(server_url)
    target = urlparse(url)
    if target.scheme in ("file", "data", "qrc"):
        return True
    return bool(
        server.scheme
        and server.netloc
        and target.scheme == server.scheme
        and target.netloc == server.netloc
    )


class GuardedPage(QWebEnginePage):
    """Keeps in-page navigation on the configured server origin.

    ``setUrl`` driven navigation (startup, retry, settings) is always allowed;
    only link clicks / script navigations are checked, and external links are
    handed to the system browser instead of hijacking the app window.
    """

    def __init__(self, profile: QWebEngineProfile, parent: QObject, is_allowed):
        super().__init__(profile, parent)
        self._is_allowed = is_allowed

    def acceptNavigationRequest(  # noqa: N802 - Qt override
        self, url: QUrl, nav_type: QWebEnginePage.NavigationType, is_main_frame: bool
    ) -> bool:
        if not is_main_frame:
            return True
        if nav_type != QWebEnginePage.NavigationType.NavigationTypeLinkClicked:
            return True
        target = url.toString()
        if self._is_allowed(target):
            return True
        if target.startswith(("http://", "https://")):
            QDesktopServices.openUrl(url)
        return False

    def createWindow(  # noqa: N802 - Qt override
        self, _window_type: QWebEnginePage.WebWindowType
    ) -> QWebEnginePage | None:
        # Popups would escape the origin guard; open them in the system browser
        # through acceptNavigationRequest instead.
        return None


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
            self._win.app.logger.warning(
                "播放请求失败：%s: %s", type(exc).__name__, exc
            )
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
            self._win.apply_settings(data)
            return json.dumps({"ok": True, "restart_required": False})
        except Exception as exc:
            return json.dumps({"ok": False, "error": config_error_message(exc)})

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
    # Emitted from a worker thread after the health check finishes; the queued
    # connection keeps all web-view calls on the GUI thread.
    connection_checked = Signal(bool, str)

    def __init__(self, app_instance, start_with_settings: bool = False):
        super().__init__()
        self.app = app_instance
        self.setWindowTitle("StrmAction")
        self.resize(self.app.config.window_width, self.app.config.window_height)
        self.setMinimumSize(900, 640)

        self._active_stream_id: str | None = None
        self._proxy = None
        self._web_loaded = False
        self._cert_handler_on = False
        self.connection_checked.connect(self._apply_connection_result)

        # Main stacked layout: 0 = Web, 1 = Embedded Player
        self.stack = QStackedWidget(self)
        self.setCentralWidget(self.stack)

        self._init_web_page()
        self._init_player_page()
        self._install_shortcuts()

        if start_with_settings or not self.app.config.is_configured():
            self.open_settings_page()
        else:
            self.load_server_url()

    # -- web view ------------------------------------------------------
    def _create_profile(self) -> QWebEngineProfile:
        """Named, on-disk profile so cookies and localStorage survive restarts.

        The default QWebEngineProfile is off-the-record (``isOffTheRecord()`` is
        True and persistent storage is ignored), which forced a fresh login on
        every launch.
        """
        storage_dir = webview_storage_dir()
        cache_dir = webview_cache_dir()
        storage_dir.mkdir(parents=True, exist_ok=True)
        cache_dir.mkdir(parents=True, exist_ok=True)

        profile = QWebEngineProfile(PROFILE_NAME, self)
        profile.setPersistentStoragePath(str(storage_dir))
        profile.setCachePath(str(cache_dir))
        profile.setPersistentCookiesPolicy(
            QWebEngineProfile.PersistentCookiesPolicy.ForcePersistentCookies
        )
        profile.setHttpCacheType(QWebEngineProfile.HttpCacheType.DiskHttpCache)
        profile.setHttpCacheMaximumSize(512 * 1024 * 1024)

        settings = profile.settings()
        settings.setAttribute(
            QWebEngineSettings.WebAttribute.LocalStorageEnabled, True
        )
        settings.setAttribute(
            QWebEngineSettings.WebAttribute.FullScreenSupportEnabled, True
        )
        settings.setAttribute(
            QWebEngineSettings.WebAttribute.JavascriptCanOpenWindows, False
        )
        return profile

    def _init_web_page(self) -> None:
        self.web = QWebEngineView(self)
        self.profile = self._create_profile()
        self.page = GuardedPage(self.profile, self.web, self._is_allowed_url)
        self.web.setPage(self.page)

        self.apply_cert_policy()

        # WebChannel setup
        self.channel = QWebChannel(self.page)
        self.bridge_obj = WebChannelBridge(self)
        self.channel.registerObject("backend", self.bridge_obj)
        self.page.setWebChannel(self.channel)

        # Inject qwebchannel.js and bridge shim into every page at DocumentReady
        self._inject_bridge_script(self.profile)

        # A dead server must not leave the user on Chromium's error page with no
        # way back: fall back to the local error page (it has retry + settings).
        self.page.loadFinished.connect(self._on_load_finished)

        self.stack.addWidget(self.web)

    def _on_load_finished(self, ok: bool) -> None:
        if ok:
            return
        current = self.page.url().toString()
        if current.startswith(("http://", "https://")):
            self.show_error_page("无法加载服务器页面，请检查地址与网络")

    def _install_shortcuts(self) -> None:
        from PySide6.QtGui import QKeySequence, QShortcut

        QShortcut(QKeySequence("Ctrl+,"), self, activated=self.open_settings_page)
        QShortcut(QKeySequence("Ctrl+Shift+S"), self, activated=self.open_settings_page)
        QShortcut(QKeySequence.StandardKey.Refresh, self, activated=self.web.reload)

    def _is_allowed_url(self, url: str) -> bool:
        return is_allowed_url(self.app.config.server_url, url)

    # -- TLS ------------------------------------------------------------
    def apply_cert_policy(self) -> None:
        """(Re)bind the certificate handler to the current setting."""
        if self._cert_handler_on:
            try:
                self.page.certificateError.disconnect(self._on_certificate_error)
            except (RuntimeError, TypeError):
                pass
            self._cert_handler_on = False
        if self.app.config.allow_self_signed_https:
            self.page.certificateError.connect(self._on_certificate_error)
            self._cert_handler_on = True

    def _on_certificate_error(self, error: QWebEngineCertificateError) -> None:
        if error.isOverridable():
            self.app.logger.warning("接受自签名证书：%s", error.description())
            error.acceptCertificate()
        else:
            self.app.logger.error("证书不可接受：%s", error.description())
            error.rejectCertificate()

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

    # -- navigation -----------------------------------------------------
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
            self._web_loaded = True
        else:
            self.open_settings_page()

    def _asset(self, name: str) -> str:
        return str(self.app.assets_dir / name)

    def show_error_page(self, message: str = "") -> None:
        self.app.last_error = message
        self._web_loaded = False
        self.load_url(self._asset("error.html"))

    # -- settings -------------------------------------------------------
    def open_settings_page(self) -> None:
        """Open the native settings dialog without touching the web page."""
        configured = bool(self.app.config.server_url)
        dialog = SettingsDialog(self.app.config, self, allow_cancel=configured)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            if not configured:
                self.show_error_page("尚未配置服务器地址")
            return
        try:
            server_changed = self.apply_settings(dialog.values())
        except Exception as exc:  # noqa: BLE001 - surface config errors to the user
            QMessageBox.warning(self, "保存失败", config_error_message(exc))
            return
        if not self.isVisible():
            self.show()
        # Only reload when the target origin actually changed, or when the web
        # app was never loaded. Keeping the page alive preserves the session.
        if server_changed or not self._web_loaded or not self.app.config.server_url:
            self.load_server_url()

    def apply_settings(self, data: dict) -> bool:
        """Persist settings and apply them live; returns True if the server changed."""
        changed = self.app.save_settings(data)
        self.apply_cert_policy()
        self.app.logger.info("桌面端设置已应用，服务器=%s", self.app.config.server_url)
        return changed

    def retry_connection(self) -> None:
        """Health-check off the GUI thread, then load the server or error page."""
        threading.Thread(
            target=self._check_connection_worker, name="strmaction-health", daemon=True
        ).start()

    def _check_connection_worker(self) -> None:
        ok, message = self.app.check_connection()
        self.connection_checked.emit(ok, message)

    @Slot(bool, str)
    def _apply_connection_result(self, ok: bool, message: str) -> None:
        if ok:
            self.app.last_error = ""
            self.load_server_url()
        else:
            self.show_error_page(message)

    # -- playback -------------------------------------------------------
    def play_embedded(self, payload: PlaybackPayload) -> None:
        self._teardown_player()

        # Switch to player page
        self.stack.setCurrentWidget(self.player_view)
        self.player_view.raise_()

        # Register stream with local loopback proxy (TLS policy included)
        self._proxy = get_proxy(tls_verify=not self.app.config.allow_self_signed_https)
        stream_id = f"stream_{payload.item_id}_{int(time.time() * 1000)}"
        self._active_stream_id = stream_id
        local_url = self._proxy.register_stream(stream_id, payload.play_url, payload.headers)

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
            self.app.logger.info("内嵌原生播放开始 item=%s", payload.item_id)

    def _teardown_player(self) -> None:
        self.player_view.stop_playback()
        if self._active_stream_id and self._proxy is not None:
            self._proxy.unregister_stream(self._active_stream_id)
        self._active_stream_id = None

    def close_player_and_return_to_web(self) -> None:
        was_playing = self.stack.currentWidget() is self.player_view
        self._teardown_player()

        if self.isFullScreen():
            self.showNormal()
        self.stack.setCurrentWidget(self.web)
        self.web.setFocus()
        if was_playing:
            # Refresh "continue watching" data now that progress changed.
            self.page.runJavaScript(
                "window.dispatchEvent(new CustomEvent('strmaction:progress-updated'));"
            )

    def request_play_item(self, item_id: int) -> None:
        """Ask the web app to start another item (next/prev/playlist)."""
        js_code = f"""
        if (typeof window.dispatchEvent !== 'undefined') {{
            window.dispatchEvent(new CustomEvent('strmaction:request-play', {{ detail: {{ itemId: {int(item_id)} }} }}));
        }}
        """
        if self.stack.currentWidget() is self.player_view:
            # The web app must run the play request, so hand control back first.
            self._teardown_player()
            self.stack.setCurrentWidget(self.web)
        self.page.runJavaScript(js_code)

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
