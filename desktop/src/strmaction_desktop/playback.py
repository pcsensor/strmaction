"""One active playback session: local mpv + progress reporter."""

from __future__ import annotations

import threading

from .config import DEFAULT_CACHE_LIMIT_MB
from .mpv import MpvController
from .progress import ProgressReporter
from .security import PlaybackPayload


class PlaybackSession:
    def __init__(
        self,
        payload: PlaybackPayload,
        mpv_path: str,
        *,
        server_url: str,
        cache_limit_mb: int = DEFAULT_CACHE_LIMIT_MB,
        allow_self_signed_https: bool = False,
        logger=None,
        on_auth_error=None,
        on_position=None,
        on_duration=None,
        on_paused=None,
        on_finished=None,
        on_exited=None,
        on_speed=None,
        on_volume=None,
        on_cache_state=None,
        on_tracks=None,
        on_idle=None,
    ):
        self.payload = payload
        self._logger = logger
        self._lock = threading.Lock()
        self._duration_ms: int | None = None
        self._last_position_ms = 0
        self._last_flush_position_ms = 0
        self._stopped = False
        self._extra_on_position = on_position
        self._extra_on_duration = on_duration
        self._extra_on_paused = on_paused
        self._extra_on_finished = on_finished
        self._extra_on_exited = on_exited
        self.reporter = ProgressReporter(
            server_url=server_url,
            item_id=payload.item_id,
            play_token=payload.play_token,
            interval_ms=payload.progress_interval_ms,
            verify_ssl=not allow_self_signed_https,
            logger=logger,
            on_auth_error=on_auth_error,
        )
        self.controller = MpvController(
            mpv_path,
            cache_limit_mb=cache_limit_mb,
            tls_verify=not allow_self_signed_https,
            on_position=self._on_position,
            on_duration=self._on_duration,
            on_paused=self._on_paused,
            on_finished=self._on_finished,
            on_exited=self._on_exited,
            on_speed=on_speed,
            on_volume=on_volume,
            on_cache_state=on_cache_state,
            on_tracks=on_tracks,
            on_idle=on_idle,
            logger=logger,
        )

    def start(self, wid: int | None = None) -> None:
        self.reporter.start()
        try:
            self.controller.play(self.payload, wid=wid)
        except Exception:
            self.reporter.stop(flush=False)
            raise

    def stop(self) -> None:
        with self._lock:
            if self._stopped:
                return
            self._stopped = True
        self.reporter.stop(flush=True)
        self.controller.stop()

    # -- mpv callbacks (reader thread) ---------------------------------
    def _on_position(self, seconds: float) -> None:
        position_ms = max(0, int(seconds * 1000))
        with self._lock:
            self._last_position_ms = position_ms
            duration = self._duration_ms
        self.reporter.update(position_ms, duration)
        # A large jump is a seek: persist it without waiting for the interval.
        if abs(position_ms - self._last_flush_position_ms) >= 5000:
            self._last_flush_position_ms = position_ms
            self.reporter.request_flush()
        if self._extra_on_position:
            self._extra_on_position(seconds)

    def _on_duration(self, seconds: float | None) -> None:
        if seconds is None:
            return
        with self._lock:
            self._duration_ms = max(0, int(seconds * 1000))
            position = self._last_position_ms
            duration = self._duration_ms
        self.reporter.update(position, duration)
        if self._extra_on_duration:
            self._extra_on_duration(seconds)

    def _on_paused(self, paused: bool) -> None:
        if paused:
            self.reporter.request_flush()
        if self._extra_on_paused:
            self._extra_on_paused(paused)

    def _on_finished(self) -> None:
        self.reporter.finish()
        self.reporter.request_flush()
        if self._extra_on_finished:
            self._extra_on_finished()

    def _on_exited(self) -> None:
        with self._lock:
            stopped = self._stopped
        if stopped:
            return
        if self._logger:
            self._logger.info("mpv 已退出")
        self.reporter.stop(flush=True)
        if self._extra_on_exited:
            self._extra_on_exited()
