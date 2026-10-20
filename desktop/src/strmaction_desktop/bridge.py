"""The JS bridge exposed to the WebView as ``window.pywebview.api``."""

from __future__ import annotations

import json

from .mpv import MpvError
from .security import config_error_message, parse_payload
from .version import __version__


class DesktopBridge:
    def __init__(self, app):
        self._app = app
        self._logger = app.logger

    # -- identity ------------------------------------------------------
    def isDesktop(self) -> bool:
        return True

    def version(self) -> str:
        return __version__

    # -- playback ------------------------------------------------------
    def playItem(self, payload: str | dict) -> dict:
        try:
            raw = json.loads(payload) if isinstance(payload, str) else payload
            parsed = parse_payload(raw, self._app.config.server_url)
            self._app.play(parsed)
            return {"ok": True}
        except Exception as exc:
            if self._logger:
                self._logger.warning(
                    "播放请求失败：%s: %s", type(exc).__name__, exc
                )
            message = (
                str(exc) if isinstance(exc, MpvError) else config_error_message(exc)
            )
            return {"ok": False, "error": message}

    def stopPlayback(self) -> dict:
        self._app.stop_playback()
        return {"ok": True}

    # -- settings ------------------------------------------------------
    def openSettings(self) -> dict:
        self._app.open_settings()
        return {"ok": True}

    def get_settings(self) -> dict:
        return {
            "ok": True,
            "server_url": self._app.config.server_url,
            "mpv_path": self._app.config.mpv_path,
            "cache_limit_mb": self._app.config.cache_limit_mb,
            "detected_mpv": self._app.detected_mpv() or "",
            "version": __version__,
        }

    def save_settings(self, data: dict) -> dict:
        try:
            self._app.save_settings(data or {})
            return {"ok": True}
        except Exception as exc:
            if self._logger:
                self._logger.warning("保存设置失败：%s", type(exc).__name__)
            return {"ok": False, "error": config_error_message(exc)}

    def choose_mpv(self) -> dict:
        path = self._app.choose_mpv()
        return {"ok": True, "path": path or ""}

    # -- lifecycle -----------------------------------------------------
    def quit(self) -> dict:
        self._app.shutdown()
        return {"ok": True}
