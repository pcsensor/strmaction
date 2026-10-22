"""libmpv based playback engine and its OpenGL render surface.

Why this exists
---------------
Qt Multimedia is not a playback engine: it has no HLS manifest handling, no
meaningful buffer, no external subtitle support and its ``QVideoWidget`` is a
*native window*, which is why controls painted on top of it were covered.

libmpv fixes the capabilities (MKV, HEVC, DTS, ASS, external subtitles,
demuxer cache) and, rendered through ``MpvRenderContext`` into a
``QOpenGLWidget`` framebuffer, it also fixes the layering: Qt composites the
FBO itself, so child widgets above it behave normally.

The engine is optional.  When no libmpv can be loaded the caller falls back to
Qt Multimedia and this module is never used.
"""

from __future__ import annotations

import logging
import math
import os
from typing import Any, Callable, Sequence

from PySide6.QtCore import (
    QObject,
    Qt,
    QTimer,
    Signal,
    Slot,
)
from PySide6.QtGui import QOpenGLContext, QSurfaceFormat
from PySide6.QtOpenGLWidgets import QOpenGLWidget

from .mpv_loader import prime_environment

logger = logging.getLogger(__name__)

# mpv fires time-pos far more often than a UI needs.  Polling on a timer keeps
# the repaint rate bounded: every update redraws the seek bar and the clock,
# and at 20 Hz that alone was enough to make playback stutter.
POSITION_POLL_MS = 200

# The demuxer cache changes far more often than a progress bar needs to move.
# Poll at 2 Hz on the GUI thread: this also gives us the real buffered ranges
# and the network input rate without observing a high-frequency property from
# mpv's thread.
CACHE_STATE_POLL_MS = 500

# mpv end-file reasons: the MpvEventEndFile constants in mpv.py.
_EOF = 0
_RESTARTED = 1
_ABORTED = 2
_QUIT = 3
_ERROR = 4
_REDIRECT = 5

# mpv error codes (mpv_error), used to turn end-file into a readable message.
_ERR_LOADING_FAILED = -13
_ERR_AO_INIT_FAILED = -14
_ERR_VO_INIT_FAILED = -15
_ERR_NOTHING_TO_PLAY = -16
_ERR_UNKNOWN_FORMAT = -17
_ERR_UNSUPPORTED = -18

# Escape hatch for drivers where the non-blocking render path misbehaves.
# The default is non-blocking; set this to 1/true/yes/on to restore the old
# behaviour (mpv sleeps inside render() until the frame's target time).
_BLOCK_RENDER_ENV = "STRMACTION_MPV_BLOCK_RENDER"


def _env_flag(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


# mpv options that are set once and are not user-visible.
_BASE_OPTIONS: dict[str, str] = {
    "vo": "libmpv",
    "hwdec": "auto-safe",
    "keep-open": "always",
    "idle": "yes",
    "terminal": "no",
    "osc": "no",
    "input-default-bindings": "no",
    "input-vo-keyboard": "no",
    "ytdl": "no",
    "force-window": "no",
    "audio-display": "no",
    "msg-level": "all=info",
}


def _field(data: Any, key: str, default: Any = None) -> Any:
    """Read a key from a dict-like or attribute-style mpv event payload."""
    if isinstance(data, dict):
        return data.get(key, default)
    value = getattr(data, key, default)
    return default if value is None else value


def _finite_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _parse_buffered_ranges(state: Any) -> list[tuple[float, float]]:
    """Extract the playable cached ranges from ``demuxer-cache-state``.

    ``seekable-ranges`` is the authoritative list of timestamps that are
    downloaded and seekable.  Older mpv builds can omit it, so fall back to
    ``reader-pts``/``cache-end`` (or derive the start from ``cache-duration``).
    Ranges are returned as sorted, merged absolute-second pairs.
    """
    if not isinstance(state, dict):
        return []

    raw_ranges = state.get("seekable-ranges")
    ranges: list[tuple[float, float]] = []
    if isinstance(raw_ranges, (list, tuple)):
        for entry in raw_ranges:
            start = _finite_float(_field(entry, "start"))
            end = _finite_float(_field(entry, "end"))
            if start is None or end is None or end <= start:
                continue
            ranges.append((max(0.0, start), end))

    if not ranges:
        cache_end = _finite_float(state.get("cache-end"))
        start = _finite_float(state.get("reader-pts"))
        if start is None and cache_end is not None:
            duration = _finite_float(state.get("cache-duration"))
            if duration is not None and duration > 0:
                start = cache_end - duration
        if start is not None and cache_end is not None and cache_end > start:
            ranges.append((max(0.0, start), cache_end))

    return _merge_ranges(ranges)


def _merge_ranges(ranges: Sequence[tuple[float, float]]) -> list[tuple[float, float]]:
    if not ranges:
        return []
    ordered = sorted(ranges, key=lambda value: value[0])
    merged: list[tuple[float, float]] = [ordered[0]]
    for start, end in ordered[1:]:
        last_start, last_end = merged[-1]
        if start <= last_end + 0.1:
            if end > last_end:
                merged[-1] = (last_start, end)
        else:
            merged.append((start, end))
    return merged


def _parse_network_speed(state: Any) -> float | None:
    """``raw-input-rate`` is mpv's network read rate in bytes/second."""
    if not isinstance(state, dict):
        return None
    value = _finite_float(state.get("raw-input-rate"))
    if value is None or value < 0:
        return None
    return value


def video_surface_format() -> QSurfaceFormat:
    """Context requested by the mpv render surface only.

    macOS needs a core profile for anything above GL 2.1 and mpv needs at least
    GL 2.1, so ask for 3.2 core and let Qt negotiate downwards.

    Deliberately **not** applied through ``QSurfaceFormat.setDefaultFormat``:
    that call is global, and forcing OpenGL on every widget breaks QtWebEngine
    (its internal ``QQuickWidget`` then fails with "'OpenGL' is not compatible
    with this QQuickWidget" and renders black).  The video widget sets this on
    itself, leaving the rest of the app on Qt's default graphics API.
    """
    fmt = QSurfaceFormat()
    fmt.setVersion(3, 2)
    fmt.setProfile(QSurfaceFormat.OpenGLContextProfile.CoreProfile)
    fmt.setDepthBufferSize(24)
    fmt.setStencilBufferSize(8)
    fmt.setSwapInterval(1)
    return fmt


def create_engine(parent: QObject | None = None, **options: Any) -> "MpvEngine":
    """Build an MpvEngine; raises whatever mpv raises when it is unusable."""
    return MpvEngine(parent, **options)


class MpvEngine(QObject):
    """libmpv wrapper exposing the same signals as QtPlayerController."""

    position_changed = Signal(float)         # current position in seconds
    duration_changed = Signal(float)         # duration in seconds
    paused_changed = Signal(bool)            # True if paused
    speed_changed = Signal(float)            # playback rate
    buffered_ranges_changed = Signal(list)   # [(start_sec, end_sec)] absolute
    network_speed_changed = Signal(float)    # bytes/s; negative means unknown
    loading_changed = Signal(bool)           # True when buffering/loading
    error_occurred = Signal(str)
    playback_finished = Signal()             # end of media reached
    tracks_changed = Signal(list)            # [{"type": "audio"|"sub", ...}]
    # Rendering: emitted from mpv's thread, consumed on the GUI thread.
    frame_ready = Signal()

    def __init__(
        self,
        parent: QObject | None = None,
        *,
        block_for_target_time: bool | None = None,
        **options: Any,
    ):
        super().__init__(parent)
        # Non-blocking is the default: mpv's blocking render waits on the GUI
        # thread until the frame's target time, which is the main source of
        # playback stutter.  The constructor argument and environment variable
        # are escape hatches for drivers where the non-blocking path is broken.
        if block_for_target_time is None:
            block_for_target_time = _env_flag(_BLOCK_RENDER_ENV)
        self._block_for_target_time = bool(block_for_target_time)
        # Prime the DLL search path first: constructing an engine directly
        # (without going through mpv_loader.is_available()) must still work.
        prime_environment()
        import mpv  # imported lazily: absence is a normal, handled condition

        self._mpv_mod = mpv
        merged = dict(_BASE_OPTIONS)
        merged.update({k: v for k, v in options.items() if v is not None})

        self._mpv = mpv.MPV(log_handler=self._handle_log, **merged)

        self._video_widget: MpvVideoWidget | None = None
        self._render_ctx: Any = None
        self._rendering = False
        self._proc_address_cb: Any = None
        self._current_headers: dict[str, str] = {}

        self._duration_sec: float = 0.0
        self._position_sec: float = 0.0
        self._is_paused: bool = False
        self._speed: float = 1.0
        self._paused_for_cache: bool = False
        self._file_starting: bool = False
        self._loading: bool = False
        self._finished_emitted = False
        self._pending_subtitles: tuple = ()
        self._tracks: list[dict] = []
        self._buffered_ranges: list[tuple[float, float]] = []
        self._network_speed: float | None = None

        self._mpv.observe_property("duration", self._on_duration)
        self._mpv.observe_property("pause", self._on_pause)
        self._mpv.observe_property("speed", self._on_speed)
        self._mpv.observe_property("track-list", self._on_track_list)
        self._mpv.observe_property("paused-for-cache", self._on_paused_for_cache)
        self._mpv.event_callback("end-file")(self._on_end_file)
        self._mpv.event_callback("start-file")(self._on_start_file)
        self._mpv.event_callback("playback-restart")(self._on_playback_restart)

        self._timer = QTimer(self)
        self._timer.setInterval(POSITION_POLL_MS)
        self._timer.timeout.connect(self._poll_position)
        self._timer.start()

        self._cache_timer = QTimer(self)
        self._cache_timer.setInterval(CACHE_STATE_POLL_MS)
        self._cache_timer.timeout.connect(self._poll_cache_state)
        self._cache_timer.start()

    # -- mpv access -----------------------------------------------------
    @property
    def handle(self) -> Any:
        return self._mpv

    @property
    def duration(self) -> float:
        return self._duration_sec

    @property
    def position(self) -> float:
        return self._position_sec

    # -- output ---------------------------------------------------------
    def set_video_output(self, video_widget) -> None:
        self._video_widget = video_widget
        if hasattr(video_widget, "bind_engine"):
            video_widget.bind_engine(self)

    def attach_render(self, get_proc_address: Callable) -> bool:
        """Create the render context; must run with a current GL context.

        python-mpv stores the callback inside a ctypes struct, so it has to be
        a real CFUNCTYPE instance rather than a plain function; passing the raw
        function raises "expected CFunctionType instance".
        """
        if self._render_ctx is not None:
            return self._rendering
        try:
            # Held on the instance: mpv keeps the raw pointer, so the callback
            # must outlive attach_render.
            self._proc_address_cb = self._mpv_mod.MpvGlGetProcAddressFn(
                get_proc_address
            )
        except Exception as exc:  # noqa: BLE001 - API renamed upstream
            logger.warning("mpv 渲染回调类型不可用：%s: %s", type(exc).__name__, exc)
            self._rendering = False
            return False
        try:
            self._render_ctx = self._mpv_mod.MpvRenderContext(
                self._mpv,
                "opengl",
                opengl_init_params={"get_proc_address": self._proc_address_cb},
            )
        except Exception as exc:  # noqa: BLE001 - render is best-effort
            logger.warning("mpv 渲染上下文创建失败：%s: %s", type(exc).__name__, exc)
            self._render_ctx = None
            self._rendering = False
            return False
        self._render_ctx.update_cb = self._on_frame_update
        self._rendering = True
        logger.info("mpv 渲染上下文已就绪")
        return True

    def _on_frame_update(self) -> None:
        # Called on mpv's own thread; the queued signal moves it to the GUI.
        self.frame_ready.emit()

    def consume_frame_update(self) -> bool:
        """Consume mpv's pending-frame flag; call from the GUI/render thread.

        ``MpvRenderContext.update()`` is what tells mpv the update callback has
        been handled.  Returning ``False`` means there is nothing new to draw,
        so callers can skip a repaint instead of re-rendering the video for an
        overlay-only update.
        """
        if self._render_ctx is None:
            return False
        try:
            return bool(self._render_ctx.update())
        except Exception as exc:  # noqa: BLE001 - fail open in the render path
            logger.debug("mpv 新帧查询失败：%s: %s", type(exc).__name__, exc)
            return True

    def render(self, width: int, height: int, fbo: int) -> bool:
        if self._render_ctx is None:
            return False
        params: dict[str, Any] = {
            "flip_y": True,
            "opengl_fbo": {"w": width, "h": height, "fbo": fbo},
        }
        if not getattr(self, "_block_for_target_time", False):
            # Return immediately instead of sleeping until the next display
            # time.  Qt already drives presentation; blocking here parked the
            # GUI thread and made every repaint wait for mpv.
            params["block_for_target_time"] = 0
        try:
            self._render_ctx.render(**params)
            return True
        except Exception as exc:  # noqa: BLE001 - a bad frame must not crash
            logger.debug("mpv 渲染失败：%s: %s", type(exc).__name__, exc)
            return False

    def report_swap(self) -> None:
        """Tell mpv that a rendered frame actually reached the screen.

        Called from ``QOpenGLWidget.frameSwapped`` after Qt has composited the
        widget, not from ``paintGL`` (which would be one composition too early).
        """
        if self._render_ctx is None:
            return
        try:
            self._render_ctx.report_swap()
        except Exception as exc:  # noqa: BLE001 - timing hint only
            logger.debug("mpv report_swap 失败：%s: %s", type(exc).__name__, exc)

    # -- loading --------------------------------------------------------
    @Slot(str, int)
    def load_media(
        self,
        url: str,
        start_ms: int = 0,
        subtitles: Sequence[Any] = (),
    ) -> None:
        """Start playback of ``url``, resuming at ``start_ms``.

        mpv supports the start position natively, so there is no pending-seek
        dance and no dropped resume.
        """
        logger.info("mpv 载入媒体 %s", url)
        self._finished_emitted = False
        self._duration_sec = 0.0
        self._position_sec = 0.0
        self._file_starting = True
        self._pending_subtitles = tuple(subtitles)
        self._reset_cache_stats()

        # mpv sends the headers with every HTTP request for this entry:
        # the media itself, HLS segments and range seeks after a 302.
        if self._current_headers:
            self._mpv["http-header-fields"] = _format_headers(self._current_headers)

        start_sec = max(0.0, int(start_ms) / 1000.0)
        if start_sec > 0.5:
            self._mpv.command(
                "loadfile", url, "replace", -1, f"start={start_sec:.3f}"
            )
        else:
            self._mpv.command("loadfile", url, "replace")

    def set_headers(self, headers: dict[str, str]) -> None:
        """Attach per-request HTTP headers (User-Agent, Referer, tokens)."""
        self._current_headers = dict(headers or {})
        if self._current_headers:
            try:
                self._mpv["http-header-fields"] = _format_headers(
                    self._current_headers
                )
            except Exception:  # noqa: BLE001 - option may be unavailable
                logger.debug("mpv 不支持 http-header-fields")

    def set_tls_verify(self, verify: bool) -> None:
        try:
            self._mpv["tls-verify"] = "yes" if verify else "no"
        except Exception:  # noqa: BLE001
            logger.debug("mpv 不支持 tls-verify")

    def set_cache_limit_mb(self, limit_mb: int) -> None:
        """Size the demuxer cache; 0 disables it."""
        if limit_mb <= 0:
            self._set_option("cache", "no")
            self._set_option("demuxer-max-bytes", "0")
            return
        self._set_option("cache", "yes")
        self._set_option("demuxer-max-bytes", f"{int(limit_mb)}MiB")
        self._set_option("demuxer-max-back-bytes", f"{max(1, limit_mb // 4)}MiB")

    def _set_option(self, name: str, value: str) -> None:
        try:
            self._mpv[name] = value
        except Exception:  # noqa: BLE001 - mpv rejects unknown/absent options
            logger.debug("mpv 选项 %s 不可用", name)

    # NOTE: in python-mpv ``player['x']`` addresses the *option* (it resolves
    # ``options/x``), while ``player.x`` addresses the *property*.  Playback
    # state (pause/speed/volume/aid/sid/time-pos) are properties; engine
    # options (cache, tls-verify, http-header-fields) are options.
    @Slot()
    def play(self) -> None:
        self._mpv.pause = False

    @Slot()
    def pause(self) -> None:
        self._mpv.pause = True

    @Slot(bool)
    def set_pause(self, paused: bool) -> None:
        if paused:
            self._mpv.pause = True
            return
        if self._finished_emitted and self._duration_sec > 0:
            # Replay from the start after the media finished.
            self._finished_emitted = False
            self._mpv.command("seek", 0, "absolute")
        self._mpv.pause = False

    @Slot(float, bool)
    def seek(self, target_sec: float, relative: bool = False) -> None:
        if relative:
            self._mpv.command("seek", float(target_sec), "relative")
            return
        target = max(0.0, float(target_sec))
        if self._duration_sec > 0:
            target = min(target, self._duration_sec)
        self._mpv.command("seek", target, "absolute")

    @Slot(float)
    def set_speed(self, speed: float) -> None:
        self._mpv.speed = max(0.25, min(float(speed), 4.0))

    @Slot(int)
    def set_volume(self, volume_percent: int) -> None:
        self._mpv.volume = max(0, min(int(volume_percent), 100))

    @Slot(int)
    def set_volume_relative(self, delta_percent: int) -> None:
        self.set_volume(int(self.volume()) + int(delta_percent))

    def volume(self) -> int:
        try:
            return int(round(float(self._mpv.volume)))
        except Exception:  # noqa: BLE001
            return 100

    @Slot()
    def stop(self) -> None:
        self._finished_emitted = False
        self._file_starting = False
        self._pending_subtitles = ()
        self._tracks = []
        try:
            self._mpv.command("stop")
        except Exception:  # noqa: BLE001 - stopping is best-effort
            logger.debug("mpv stop 失败")
        self._duration_sec = 0.0
        self._position_sec = 0.0
        self._reset_cache_stats()
        self._set_loading(False)

    def shutdown(self) -> None:
        self._timer.stop()
        self._cache_timer.stop()
        try:
            self._mpv.command("stop")
        except Exception:  # noqa: BLE001
            pass
        # Detach the video output first: freeing the render context while it is
        # still the active vo makes mpv log a spurious VO_INIT_FAILED.
        try:
            self._mpv.vo = "null"
        except Exception:  # noqa: BLE001
            pass
        if self._render_ctx is not None:
            try:
                self._render_ctx.free()
            except Exception:  # noqa: BLE001
                pass
            self._render_ctx = None
        self._rendering = False
        try:
            self._mpv.terminate()
        except Exception:  # noqa: BLE001
            logger.debug("mpv terminate 失败")

    # -- tracks ---------------------------------------------------------
    def tracks(self) -> list[dict]:
        return list(self._tracks)

    @Slot(int)
    def set_audio_track(self, index: int) -> None:
        self._mpv.aid = int(index)

    @Slot(int)
    def set_subtitle_track(self, index: int) -> None:
        # -1 (or "no") disables subtitles, which the drawer relies on.
        self._mpv.sid = "no" if int(index) < 0 else int(index)

    @Slot()
    def cycle_audio(self) -> None:
        ids = [t["id"] for t in self._tracks if t.get("type") == "audio"]
        if len(ids) <= 1:
            return
        current = self._current_aid()
        try:
            pos = ids.index(current)
        except ValueError:
            self._mpv.aid = ids[0]
            return
        self._mpv.aid = ids[(pos + 1) % len(ids)]

    @Slot()
    def cycle_subtitle(self) -> None:
        ids = [t["id"] for t in self._tracks if t.get("type") == "sub"]
        if not ids:
            return
        current = self._current_sid()
        if current is None or current not in ids:
            self._mpv.sid = ids[0]
            return
        pos = ids.index(current)
        # Cycling past the last track turns subtitles off.
        self._mpv.sid = "no" if pos + 1 >= len(ids) else ids[pos + 1]

    def _current_aid(self) -> int | None:
        try:
            value = self._mpv.aid
        except Exception:  # noqa: BLE001
            return None
        return value if isinstance(value, int) else None

    def _current_sid(self) -> int | None:
        try:
            value = self._mpv.sid
        except Exception:  # noqa: BLE001
            return None
        return value if isinstance(value, int) else None

    # -- mpv observers --------------------------------------------------
    def _on_duration(self, _name: str, value: Any) -> None:
        if value is None or not isinstance(value, (int, float)):
            return
        seconds = max(0.0, float(value))
        if abs(seconds - self._duration_sec) < 0.01:
            return
        self._duration_sec = seconds
        self.duration_changed.emit(seconds)

    def _on_pause(self, _name: str, value: Any) -> None:
        paused = bool(value)
        if paused == self._is_paused:
            return
        self._is_paused = paused
        self.paused_changed.emit(paused)

    def _on_speed(self, _name: str, value: Any) -> None:
        if value is None or not isinstance(value, (int, float)):
            return
        self._speed = float(value)
        self.speed_changed.emit(self._speed)

    def _on_paused_for_cache(self, _name: str, value: Any) -> None:
        self._paused_for_cache = bool(value)
        self._set_loading(self._paused_for_cache or self._file_starting)

    def _on_track_list(self, _name: str, value: Any) -> None:
        if not isinstance(value, list):
            if value is None:
                self._tracks = []
                self.tracks_changed.emit([])
            return
        tracks: list[dict] = []
        aid = self._current_aid()
        sid = self._current_sid()
        for entry in value:
            kind = entry.get("type")
            if kind not in ("audio", "sub"):
                continue
            track_id = entry.get("id")
            try:
                track_id = int(track_id)
            except (TypeError, ValueError):
                continue
            title = (
                entry.get("title")
                or entry.get("lang")
                or entry.get("codec")
                or ""
            )
            selected = (
                track_id == aid if kind == "audio" else track_id == sid
            )
            tracks.append(
                {
                    "type": kind,
                    "id": track_id,
                    "title": str(title),
                    "selected": bool(selected),
                    "external": bool(entry.get("external")),
                }
            )
        self._tracks = tracks
        self.tracks_changed.emit(tracks)

    # -- mpv events -----------------------------------------------------
    def _on_start_file(self, event: Any) -> None:  # noqa: ARG002
        self._file_starting = True
        self._set_loading(True)
        self._flush_pending_subtitles()

    def _on_playback_restart(self, event: Any) -> None:  # noqa: ARG002
        self._file_starting = False
        self._set_loading(self._paused_for_cache)

    def _on_end_file(self, event: Any) -> None:
        data = getattr(event, "data", None)
        reason = _field(data, "reason")
        self._file_starting = False
        if reason == _EOF:
            self._set_loading(False)
            if not self._finished_emitted:
                self._finished_emitted = True
                self.playback_finished.emit()
            return
        if reason == _ERROR:
            self._set_loading(False)
            code = _field(data, "error")
            logger.warning("mpv 播放失败，错误码 %s", code)
            self.error_occurred.emit(_friendly_error(code))
            return
        # aborted / quit / redirect: the UI tore the playback down on purpose.
        self._set_loading(False)

    def _flush_pending_subtitles(self) -> None:
        """Attach external subtitles as soon as the file starts loading."""
        if not self._pending_subtitles:
            return
        pending, self._pending_subtitles = self._pending_subtitles, ()
        for index, sub in enumerate(pending):
            url = getattr(sub, "url", None) or (sub.get("url") if isinstance(sub, dict) else None)
            if not url:
                continue
            label = getattr(sub, "label", "") or "字幕"
            try:
                # "select" makes the first external track active; the rest are
                # added but left disabled so the drawer can switch to them.
                self._mpv.command(
                    "sub-add", url, "select" if index == 0 else "auto", label
                )
            except Exception:  # noqa: BLE001 - a bad subtitle URL is not fatal
                logger.warning("外挂字幕加载失败：%s", label)

    # -- polling --------------------------------------------------------
    def _poll_position(self) -> None:
        try:
            value = self._mpv.time_pos
        except Exception:  # noqa: BLE001 - property absent while idle
            return
        if value is None or not isinstance(value, (int, float)):
            return
        self._position_sec = max(0.0, float(value))
        self.position_changed.emit(self._position_sec)

    def _poll_cache_state(self) -> None:
        try:
            state = self._mpv.demuxer_cache_state
        except Exception:  # noqa: BLE001 - property unavailable while idle
            return
        if not isinstance(state, dict):
            return
        self._apply_cache_state(state)

    def _apply_cache_state(self, state: dict) -> None:
        ranges = _parse_buffered_ranges(state)
        if ranges != self._buffered_ranges:
            self._buffered_ranges = ranges
            self.buffered_ranges_changed.emit(ranges)

        speed = _parse_network_speed(state)
        if speed is None:
            # Some builds omit raw-input-rate from the node while cache-speed
            # is still available.
            try:
                speed = _finite_float(self._mpv.cache_speed)
            except Exception:  # noqa: BLE001 - optional property
                speed = None
        if speed is None or speed < 0:
            return
        if speed != self._network_speed:
            self._network_speed = speed
            self.network_speed_changed.emit(speed)

    def _reset_cache_stats(self) -> None:
        self._buffered_ranges = []
        self._network_speed = None
        try:
            self.buffered_ranges_changed.emit([])
            self.network_speed_changed.emit(-1.0)
        except RuntimeError:
            # Tests build the engine with __new__ to avoid loading libmpv.
            pass

    def _set_loading(self, loading: bool) -> None:
        if loading == self._loading:
            return
        self._loading = loading
        self.loading_changed.emit(loading)

    def _handle_log(self, level: str, component: str, message: str) -> None:
        text = (message or "").strip()
        if not text:
            return
        if level in ("error", "fatal"):
            logger.error("mpv[%s] %s", component, text)
        elif level == "warn":
            logger.warning("mpv[%s] %s", component, text)
        elif level in ("v", "debug", "trace"):
            logger.debug("mpv[%s] %s", component, text)
        else:
            logger.info("mpv[%s] %s", component, text)


def _format_headers(headers: dict[str, str]) -> str:
    """mpv wants `Name: Value` entries joined by commas."""
    parts: list[str] = []
    for key, value in headers.items():
        key = str(key).strip()
        value = str(value).strip()
        if not key or not value or "," in key or ":" in key:
            # A comma or colon would break the option's own grammar.
            continue
        parts.append(f"{key}: {value}")
    return ",".join(parts)


def _friendly_error(code: Any) -> str:
    """Turn an mpv error code into something a user can act on."""
    try:
        number = int(code)
    except (TypeError, ValueError):
        return _GENERIC_PLAYBACK_ERROR
    if number == _ERR_LOADING_FAILED:
        return ("无法打开片源（链接可能已过期、被防盗链拒绝，"
                "或证书校验未通过）")
    if number in (_ERR_UNKNOWN_FORMAT, _ERR_UNSUPPORTED):
        return "无法播放该媒体（格式不受支持或片源已损坏）"
    if number == _ERR_NOTHING_TO_PLAY:
        return "片源中没有可播放的音视频轨道"
    if number == _ERR_VO_INIT_FAILED:
        return "视频输出初始化失败，请更新显卡驱动"
    if number == _ERR_AO_INIT_FAILED:
        return "音频设备初始化失败，请检查系统音频输出"
    return _GENERIC_PLAYBACK_ERROR


_GENERIC_PLAYBACK_ERROR = "播放失败，请查看日志或稍后重试"


class MpvVideoWidget(QOpenGLWidget):
    """Renders mpv into an FBO so Qt can composite widgets above the video.

    This is the crux of the layering fix: unlike ``QVideoWidget``, the frame
    never leaves Qt's paint path, so overlays stacked on top are drawn
    normally and never get covered by a native window.
    """

    def __init__(self, engine: MpvEngine, parent: Any = None):
        super().__init__(parent)
        self._engine = engine
        self._attached = False
        self._needs_render = True
        self._frame_rendered = False
        self.frame_ready_connected = False
        # Keep the last video frame in the FBO when Qt repaints only the
        # overlay.  With the default NoPartialUpdate Qt clears the FBO before
        # paintGL, so returning early would show black.
        self.setUpdateBehavior(QOpenGLWidget.UpdateBehavior.PartialUpdate)
        # Scoped to this widget: a global default format breaks QtWebEngine.
        self.setFormat(video_surface_format())
        self.setStyleSheet("background-color: #000000;")
        # The video surface never handles input; PlayerView owns the mouse.
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        # frameSwapped fires after Qt has composited the widget, which is the
        # correct point for mpv to learn that the frame reached the screen.
        self.frameSwapped.connect(self._on_frame_swapped)

    def bind_engine(self, engine: MpvEngine) -> None:
        self._engine = engine
        try:
            engine.frame_ready.connect(self._request_update)
            self.frame_ready_connected = True
        except Exception:  # noqa: BLE001
            pass

    def _request_update(self) -> None:
        engine = self._engine
        if engine is None or not engine.consume_frame_update():
            return
        self._needs_render = True
        self.update()

    def _on_frame_swapped(self) -> None:
        if not self._frame_rendered:
            return
        self._frame_rendered = False
        if self._engine is not None:
            self._engine.report_swap()

    # -- QOpenGLWidget overrides ---------------------------------------
    def initializeGL(self) -> None:  # noqa: N802 - Qt override
        self._needs_render = True
        if self._engine is None or self._attached:
            return
        self._attached = self._engine.attach_render(self._get_proc_address)

    def paintGL(self) -> None:  # noqa: N802 - Qt override
        engine = self._engine
        if engine is None or not self._needs_render:
            return
        self._needs_render = False
        ratio = self.devicePixelRatioF() if hasattr(self, "devicePixelRatioF") else 1.0
        width = max(1, int(self.width() * ratio))
        height = max(1, int(self.height() * ratio))
        self._frame_rendered = bool(
            engine.render(width, height, int(self.defaultFramebufferObject()))
        )

    def resizeGL(self, w: int, h: int) -> None:  # noqa: N802 - Qt override
        # The FBO is recreated by Qt on resize; force one full re-render even
        # if mpv has not produced a new frame yet.
        super().resizeGL(w, h)
        self._needs_render = True

    def showEvent(self, event) -> None:  # noqa: N802 - Qt override
        super().showEvent(event)
        self._needs_render = True
        self.update()

    # -- helper ---------------------------------------------------------
    @staticmethod
    def _get_proc_address(_ctx: Any, name: Any) -> int:
        """Resolve a GL entry point for mpv (C callback, must not raise)."""
        try:
            context = QOpenGLContext.currentContext()
            if context is None:
                return 0
            text = name.decode("utf-8") if isinstance(name, (bytes, bytearray)) else str(name)
            address = context.getProcAddress(text)
            if not address:
                return 0
            return int(address)
        except Exception:  # noqa: BLE001 - returning 0 is the contract
            return 0
