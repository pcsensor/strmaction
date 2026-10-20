"""Progress reporting for local mpv playback.

The desktop client uses the same progress endpoint as the web/companion apps,
with the item-scoped play_token as a Bearer credential.  Uploads are
single-flight and coalesced: only the latest known position is sent.
"""

from __future__ import annotations

import threading
import time
import uuid
from typing import Any, Callable

import httpx

from .version import __version__

FINISHED_RATIO = 0.9


class ProgressReporter:
    def __init__(
        self,
        server_url: str,
        item_id: int,
        play_token: str,
        interval_ms: int = 5000,
        *,
        client: httpx.Client | None = None,
        on_auth_error: Callable[[], None] | None = None,
        logger=None,
        session_id: str | None = None,
    ):
        self._url = f"{server_url.rstrip('/')}/api/items/{item_id}/progress"
        self._item_id = item_id
        self._token = play_token
        self._interval = max(2.0, min(interval_ms / 1000.0, 60.0))
        self._client = client or httpx.Client(
            timeout=httpx.Timeout(5.0, connect=3.0)
        )
        self._owns_client = client is None
        self._headers = {
            "User-Agent": f"StrmActionDesktop/{__version__}",
            "Authorization": f"Bearer {play_token}",
        }
        self._on_auth_error = on_auth_error
        self._logger = logger
        self._session = session_id or uuid.uuid4().hex[:12]

        self._state_lock = threading.Lock()
        self._send_lock = threading.Lock()
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

        self._position_ms = 0
        self._duration_ms: int | None = None
        self._finished = False
        self._dirty = False
        self._sequence = 0
        self._auth_failed = False

    # -- public API ----------------------------------------------------
    @property
    def auth_failed(self) -> bool:
        return self._auth_failed

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._thread = threading.Thread(
            target=self._loop, name="progress-reporter", daemon=True
        )
        self._thread.start()

    def update(self, position_ms: int, duration_ms: int | None = None) -> None:
        if self._stop.is_set():
            return
        with self._state_lock:
            self._position_ms = max(0, int(position_ms))
            if duration_ms is not None:
                self._duration_ms = max(0, int(duration_ms))
            self._dirty = True
        # Deliberately do not wake the loop here. mpv emits time-pos many times
        # per second; waking on every tick would turn the configured interval
        # into an unthrottled upload loop. Pause/seek/exit call request_flush().

    def finish(self) -> None:
        with self._state_lock:
            self._finished = True
            self._dirty = True
        self._wake.set()

    def request_flush(self) -> None:
        self._wake.set()

    def flush_once(self, force: bool = False) -> bool:
        """Send the latest progress once. Safe to call from tests/stop()."""
        if self._auth_failed:
            return False
        with self._send_lock:
            with self._state_lock:
                if not self._dirty and not force:
                    return False
                payload = self._payload_locked()
                self._dirty = False
            try:
                response = self._client.post(
                    self._url, json=payload, headers=self._headers
                )
            except httpx.HTTPError as exc:
                if self._logger:
                    self._logger.warning("进度上报网络错误：%s", type(exc).__name__)
                with self._state_lock:
                    self._dirty = True
                return False

            if response.status_code in {401, 403}:
                self._auth_failed = True
                self._stop.set()
                self._wake.set()
                if self._logger:
                    self._logger.warning(
                        "进度上报鉴权失败（%s），停止上报", response.status_code
                    )
                if self._on_auth_error:
                    try:
                        self._on_auth_error()
                    except Exception:
                        pass
                return False
            if response.status_code >= 400:
                if self._logger:
                    self._logger.warning(
                        "进度上报失败：HTTP %s", response.status_code
                    )
                with self._state_lock:
                    self._dirty = True
                return False
            return True

    def stop(self, flush: bool = True) -> None:
        self._stop.set()
        self._wake.set()
        if flush and not self._auth_failed:
            try:
                self.flush_once(force=True)
            except Exception:
                pass
        if self._thread is not None:
            self._thread.join(timeout=4)
            self._thread = None
        if self._owns_client:
            try:
                self._client.close()
            except Exception:
                pass

    # -- internals -----------------------------------------------------
    def _payload_locked(self) -> dict[str, Any]:
        duration = self._duration_ms
        position = self._position_ms
        finished = bool(self._finished)
        if duration and duration > 0:
            position = min(position, duration)
            if position / duration >= FINISHED_RATIO:
                finished = True
        if finished:
            position = 0
        self._sequence += 1
        return {
            "position_ms": position,
            "duration_ms": duration,
            "finished": finished,
            "client_key": f"desktop-{self._session}-{self._sequence}",
        }

    def _loop(self) -> None:
        while not self._stop.is_set():
            self._wake.wait(self._interval)
            self._wake.clear()
            if self._stop.is_set():
                break
            if not self.flush_once():
                # Keep a small delay before the next attempt; the loop interval
                # already provides backpressure, and the latest state is kept.
                time.sleep(0.5)
