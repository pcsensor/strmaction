"""Integrated embedded PlayerView: video surface, overlay, drawer, keyboard."""

from __future__ import annotations

import logging
from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QKeyEvent, QMouseEvent
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtWidgets import QWidget

from ..config import DEFAULT_CACHE_LIMIT_MB
from ..security import PlaybackPayload
from .controller import QtPlayerController
from .drawer import PlayerDrawer
from .endcard import MessageCard
from .keyboard import KeyboardHandler
from .overlay import ControlsOverlay

logger = logging.getLogger(__name__)

NEXT_EPISODE_COUNTDOWN = 5


class PlayerView(QWidget):
    exit_requested = Signal()
    next_episode_requested = Signal(int)  # item_id

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setStyleSheet("background-color: #000000;")
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMouseTracking(True)

        self._controller: QtPlayerController | Any = None
        self._payload: PlaybackPayload | None = None
        self._reporter = None
        self._stream_url = ""
        self._normal_speed: float = 1.0
        self._is_paused: bool = False
        self._duration: float = 0.0
        self._card_mode: str | None = None  # "end" | "error" | None
        self._using_mpv = False
        self._cache_limit_mb = DEFAULT_CACHE_LIMIT_MB
        self._tls_verify = True

        self._init_ui()
        self._init_keyboard()

    # -- backend selection ----------------------------------------------
    def _create_playback_engine(self) -> None:
        """Pick the libmpv backend, or fall back to Qt Multimedia.

        mpv renders into a QOpenGLWidget FBO that Qt composites itself, so the
        controls stacked above it are painted normally.  The Qt fallback uses
        QVideoWidget, which is a native window and needs the local proxy to
        inject request headers.
        """
        engine = None
        try:
            from ..player.mpv_loader import is_available

            if is_available():
                from .mpv_engine import MpvVideoWidget, create_engine

                engine = create_engine(self)
        except Exception as exc:  # noqa: BLE001 - absence is not an error
            logger.warning("mpv 后端不可用，回退 Qt Multimedia：%s: %s",
                           type(exc).__name__, exc)
            engine = None

        if engine is not None:
            self.video_widget = MpvVideoWidget(engine, self)
            self.controller = engine
            self.controller.set_video_output(self.video_widget)
            self._using_mpv = True
            logger.info("播放后端：libmpv")
        else:
            self.video_widget = QVideoWidget(self)
            self.video_widget.setStyleSheet("background-color: #000000;")
            self.controller = QtPlayerController(self)
            self.controller.set_video_output(self.video_widget)
            self._using_mpv = False
            logger.info("播放后端：Qt Multimedia（未找到 libmpv）")
        self._controller = self.controller

    def configure(
        self,
        *,
        cache_limit_mb: int | None = None,
        tls_verify: bool | None = None,
    ) -> None:
        """Apply desktop settings that affect the playback engine."""
        if cache_limit_mb is not None:
            self._cache_limit_mb = int(cache_limit_mb)
        if tls_verify is not None:
            self._tls_verify = bool(tls_verify)
        if self._controller is None:
            return
        try:
            self._controller.set_cache_limit_mb(self._cache_limit_mb)
            self._controller.set_tls_verify(self._tls_verify)
        except Exception:  # noqa: BLE001 - the Qt backend ignores both
            pass

    def _init_ui(self) -> None:
        # 1. Video surface + playback engine (mpv when available)
        self._create_playback_engine()

        # Wire controller signals
        self.controller.position_changed.connect(self._on_player_position)
        self.controller.duration_changed.connect(self._on_player_duration)
        self.controller.paused_changed.connect(self._on_player_paused)
        self.controller.speed_changed.connect(self._on_player_speed)
        self.controller.buffered_ranges_changed.connect(
            self._on_player_buffered_ranges
        )
        self.controller.network_speed_changed.connect(
            self._on_player_network_speed
        )
        self.controller.loading_changed.connect(self._on_player_loading)
        self.controller.error_occurred.connect(self._on_player_error)
        self.controller.playback_finished.connect(self._on_playback_finished)
        self.controller.tracks_changed.connect(self._on_tracks_changed)

        # 2. Controls Overlay
        self.overlay = ControlsOverlay(self)
        self.overlay.back_clicked.connect(self._on_back_clicked)
        self.overlay.play_pause_clicked.connect(self._toggle_play_pause)
        self.overlay.prev_clicked.connect(self._play_prev_episode)
        self.overlay.next_clicked.connect(self._play_next_episode)
        self.overlay.seek_requested.connect(self._on_seek_requested)
        self.overlay.speed_drawer_clicked.connect(lambda: self._open_drawer("speed"))
        self.overlay.episodes_drawer_clicked.connect(lambda: self._open_drawer("episodes"))
        self.overlay.tracks_drawer_clicked.connect(lambda: self._open_drawer("tracks"))
        self.overlay.fullscreen_clicked.connect(self._toggle_fullscreen)

        # 3. 40% Drawer
        self.drawer = PlayerDrawer(self)
        self.drawer.closed.connect(self._on_drawer_closed)
        self.drawer.episode_selected.connect(self._on_episode_selected)
        self.drawer.speed_selected.connect(self._on_speed_selected)
        self.drawer.subtitle_selected.connect(self._on_subtitle_selected)
        self.drawer.audio_selected.connect(self._on_audio_selected)

        # 4. End-of-playback / error card
        self.message_card = MessageCard(self)
        self.message_card.primary_clicked.connect(self._on_card_primary)
        self.message_card.secondary_clicked.connect(self._on_card_secondary)

    def _init_keyboard(self) -> None:
        self.keyboard = KeyboardHandler(self)
        self.keyboard.play_pause_toggled.connect(self._toggle_play_pause)
        self.keyboard.seek_relative.connect(self._on_seek_relative)
        self.keyboard.speed_boost_started.connect(self._on_speed_boost_started)
        self.keyboard.speed_boost_ended.connect(self._on_speed_boost_ended)
        self.keyboard.volume_relative.connect(self._on_volume_relative)
        self.keyboard.fullscreen_toggled.connect(self._toggle_fullscreen)
        self.keyboard.escape_pressed.connect(self._on_escape_pressed)
        self.keyboard.prev_episode_requested.connect(self._play_prev_episode)
        self.keyboard.next_episode_requested.connect(self._play_next_episode)
        self.keyboard.cycle_subtitle_requested.connect(self._cycle_subtitle)
        self.keyboard.cycle_audio_requested.connect(self._cycle_audio)
        self.keyboard.toggle_drawer_requested.connect(self._toggle_drawer)

    def load_playback(
        self,
        payload: PlaybackPayload,
        stream_url: str,
        reporter=None,
    ) -> None:
        """Start playing a stream URL with metadata and optional progress reporter."""
        self._payload = payload
        self._reporter = reporter
        self._stream_url = stream_url
        self._normal_speed = 1.0
        self._is_paused = False
        self._duration = (payload.duration_ms or 0) / 1000.0 if payload.duration_ms else 0.0
        self._card_mode = None
        self.message_card.hide_message()

        # Setup Overlay UI
        self.overlay.set_title(payload.title, payload.series_title)
        self.overlay.set_duration(self._duration)
        self.overlay.set_position((payload.resume_ms or 0) / 1000.0)
        self.overlay.reset_buffer_stats()
        self.overlay.set_speed_text(1.0)
        self.overlay.set_paused(False)

        # Prev / Next navigation
        has_prev, has_next = self._check_nav_available(payload)
        self.overlay.set_nav_buttons(has_prev, has_next)

        # Setup Drawer UI (embedded tracks arrive asynchronously from the player)
        self.drawer.set_data(
            playlist=payload.playlist,
            current_item_id=payload.item_id,
            current_speed=1.0,
            subtitles=[],
            audio_tracks=[],
            current_sid="no",
            current_aid=None,
            subtitle_hint=self._subtitle_hint(payload, has_tracks=False),
        )

        self.setFocus()
        self.overlay.show_controls()
        self.overlay.restart_auto_hide_timer()

        # mpv attaches the headers to every HTTP request itself, so the direct
        # CDN URL is used.  The Qt fallback cannot do that and just opens it.
        self._controller.set_headers(payload.headers)
        # mpv takes the resume offset natively via loadfile; no pending seek.
        self.controller.load_media(
            stream_url,
            start_ms=int(payload.resume_ms or 0),
            subtitles=payload.subtitles if self._using_mpv else (),
        )

    def stop_playback(self) -> None:
        self.message_card.hide_message()
        self.controller.stop()
        self.overlay.reset_buffer_stats()
        if self._reporter:
            try:
                self._reporter.stop(flush=True)
            except Exception:
                pass
            self._reporter = None

    def shutdown(self) -> None:
        """Tear the libmpv instance down when the window closes."""
        controller = self._controller
        if controller is not None and hasattr(controller, "shutdown"):
            try:
                controller.shutdown()
            except Exception:  # noqa: BLE001 - shutdown is best-effort
                logger.debug("播放引擎关闭异常", exc_info=True)

    def _subtitle_hint(self, payload: PlaybackPayload, has_tracks: bool) -> str:
        """Hint shown in the tracks drawer when no subtitle track exists yet.

        libmpv can load external .srt/.ass, so the old "not supported" wording
        only applies to the Qt fallback.
        """
        if has_tracks:
            return ""
        if not self._using_mpv:
            if payload.subtitles:
                return "外挂字幕暂不支持内嵌播放器，请使用伴侣 App 或网页端观看。"
            return "片中无字幕轨道"
        return "外挂字幕加载中…" if payload.subtitles else "片中无字幕轨道"

    def _check_nav_available(self, payload: PlaybackPayload) -> tuple[bool, bool]:
        if not payload.playlist or payload.current_index < 0:
            return False, payload.next_item_id is not None
        has_prev = payload.current_index > 0
        has_next = payload.current_index + 1 < len(payload.playlist) or payload.next_item_id is not None
        return has_prev, has_next

    # -- Player Internal Event Listeners --
    def _on_player_position(self, seconds: float) -> None:
        self.overlay.set_position(seconds)
        if self._reporter:
            pos_ms = int(seconds * 1000)
            dur_ms = int(self._duration * 1000) if self._duration else None
            self._reporter.update(pos_ms, dur_ms)

    def _on_player_duration(self, seconds: float) -> None:
        self._duration = seconds
        self.overlay.set_duration(seconds)

    def _on_player_paused(self, paused: bool) -> None:
        self._is_paused = paused
        self.overlay.set_paused(paused)

    def _on_player_speed(self, speed: float) -> None:
        if not self.keyboard._is_speed_boost_active:
            self._normal_speed = speed
        self.overlay.set_speed_text(speed)
        self.drawer.set_data(current_speed=speed)

    def _on_player_buffered_ranges(self, ranges: list[tuple[float, float]]) -> None:
        self.overlay.set_buffered_ranges(ranges)

    def _on_player_network_speed(self, bytes_per_sec: float) -> None:
        self.overlay.set_network_speed(bytes_per_sec)

    def _on_player_loading(self, is_loading: bool) -> None:
        self.overlay.set_loading(is_loading)

    def _on_tracks_changed(self, tracks: list[dict]) -> None:
        if not isinstance(tracks, list) or self._payload is None:
            return
        subs: list[dict] = []
        audios: list[dict] = []
        current_sid: Any = "no"
        current_aid: Any = None
        for track in tracks:
            if track.get("type") == "sub":
                label = track.get("title") or f"字幕 #{track.get('id')}"
                if track.get("external"):
                    label = f"{label}（外挂）"
                subs.append({"id": track.get("id"), "label": label})
                if track.get("selected"):
                    current_sid = track.get("id")
            elif track.get("type") == "audio":
                audios.append(
                    {
                        "id": track.get("id"),
                        "title": track.get("title") or f"音轨 #{track.get('id')}",
                    }
                )
                if track.get("selected"):
                    current_aid = track.get("id")
        self.drawer.set_data(
            subtitles=subs,
            audio_tracks=audios,
            current_sid=current_sid,
            current_aid=current_aid,
            subtitle_hint=self._subtitle_hint(self._payload, has_tracks=bool(subs)),
        )

    # -- End of playback / errors --
    def _next_episode_id(self) -> int | None:
        if not self._payload:
            return None
        if self._payload.playlist and self._payload.current_index >= 0:
            index = self._payload.current_index
            if index + 1 < len(self._payload.playlist):
                entry = self._payload.playlist[index + 1]
                next_id = entry.get("item_id") or entry.get("id")
                if next_id:
                    return int(next_id)
        if self._payload.next_item_id:
            return int(self._payload.next_item_id)
        return None

    def _on_playback_finished(self) -> None:
        self.overlay.set_loading(False)
        self._is_paused = True
        self.overlay.set_paused(True)
        self.overlay.show_controls()
        self._card_mode = "end"
        if self._reporter:
            try:
                self._reporter.finish()
                self._reporter.request_flush()
            except Exception:
                pass

        next_id = self._next_episode_id()
        if next_id:
            next_label = ""
            if self._payload:
                for index, entry in enumerate(self._payload.playlist):
                    if (entry.get("item_id") or entry.get("id")) == next_id:
                        next_label = str(entry.get("title") or entry.get("code") or "")
                        break
                if not next_label:
                    next_label = self._payload.next_title or ""
            self.message_card.show_message(
                "播放结束",
                f"下一集：{next_label}" if next_label else "",
                primary="播放下一集",
                secondary="返回",
                countdown=NEXT_EPISODE_COUNTDOWN,
            )
        else:
            self.message_card.show_message(
                "播放结束",
                "已记录观看进度",
                primary="返回",
            )

    def _on_player_error(self, message: str) -> None:
        self.overlay.set_loading(False)
        self.overlay.show_controls()
        self._card_mode = "error"
        self.message_card.show_message(
            "播放失败",
            message or "无法打开片源，请检查网络或片源地址。",
            primary="重试",
            secondary="返回",
        )

    def _on_card_primary(self) -> None:
        mode = self._card_mode
        self._card_mode = None
        if mode == "end":
            next_id = self._next_episode_id()
            if next_id:
                self.next_episode_requested.emit(next_id)
                return
            self._on_back_clicked()
            return
        # Retry the current stream without losing the progress reporter.
        if self._stream_url:
            self.overlay.set_loading(True)
            self.controller.load_media(self._stream_url, start_ms=0)

    def _on_card_secondary(self) -> None:
        self._card_mode = None
        self._on_back_clicked()

    # -- User Interactions --
    def _toggle_play_pause(self) -> None:
        if not self._controller:
            return
        if self._card_mode == "end" and self.message_card.is_shown:
            self._on_card_primary()
            return
        self.message_card.hide_message()
        self._card_mode = None
        new_pause = not self._is_paused
        self._controller.set_pause(new_pause)
        self.overlay.flash_center_play_pause(new_pause)

    def _on_seek_requested(self, target_sec: float) -> None:
        if self._controller:
            self.message_card.hide_message()
            self._card_mode = None
            self._controller.seek(target_sec, relative=False)

    def _on_seek_relative(self, delta_sec: float) -> None:
        if self._controller:
            self._controller.seek(delta_sec, relative=True)
            sign = "+" if delta_sec > 0 else ""
            self.overlay.flash_seek_badge(f"{sign}{int(delta_sec)}s")

    def _on_speed_boost_started(self, speed: float) -> None:
        if self._controller:
            self._controller.set_speed(speed)
            self.overlay.show_speed_boost_badge(speed)

    def _on_speed_boost_ended(self) -> None:
        if self._controller:
            self._controller.set_speed(self._normal_speed)
            self.overlay.hide_speed_boost_badge()

    def _on_volume_relative(self, delta: int) -> None:
        if self._controller:
            self._controller.set_volume_relative(delta)
            self.overlay.flash_seek_badge(f"音量 {self._controller.volume()}")

    def _cycle_subtitle(self) -> None:
        if self._controller:
            self._controller.cycle_subtitle()
            self.overlay.flash_seek_badge("切换字幕")

    def _cycle_audio(self) -> None:
        if self._controller:
            self._controller.cycle_audio()
            self.overlay.flash_seek_badge("切换音轨")

    def _open_drawer(self, tab_id: str) -> None:
        self.drawer.open_tab(tab_id)
        self.overlay._hide_timer.stop()

    def _toggle_drawer(self) -> None:
        if self.drawer.isVisible():
            self.drawer.close_drawer()
        else:
            self._open_drawer("episodes")

    def _on_drawer_closed(self) -> None:
        self.setFocus()
        self.overlay.restart_auto_hide_timer()

    def _on_episode_selected(self, item_id: int) -> None:
        self.drawer.close_drawer()
        self.next_episode_requested.emit(item_id)

    def _on_speed_selected(self, speed: float) -> None:
        self._normal_speed = speed
        if self._controller:
            self._controller.set_speed(speed)

    def _on_subtitle_selected(self, sid: Any) -> None:
        if not self._controller:
            return
        if sid in ("no", None, False):
            self._controller.set_subtitle_track(-1)
        else:
            try:
                self._controller.set_subtitle_track(int(sid))
            except (TypeError, ValueError):
                return

    def _on_audio_selected(self, aid: Any) -> None:
        if not self._controller:
            return
        try:
            self._controller.set_audio_track(int(aid))
        except (TypeError, ValueError):
            return

    def _play_prev_episode(self) -> None:
        if not self._payload or not self._payload.playlist:
            return
        index = self._payload.current_index
        if index > 0:
            prev_ep = self._payload.playlist[index - 1]
            prev_id = prev_ep.get("item_id") or prev_ep.get("id")
            if prev_id:
                self.next_episode_requested.emit(int(prev_id))

    def _play_next_episode(self) -> None:
        next_id = self._next_episode_id()
        if next_id:
            self.next_episode_requested.emit(next_id)

    def _toggle_fullscreen(self) -> None:
        win = self.window()
        if win.isFullScreen():
            win.showNormal()
            self.overlay.set_fullscreen(False)
        else:
            win.showFullScreen()
            self.overlay.set_fullscreen(True)

    def _on_escape_pressed(self) -> None:
        if self.drawer.isVisible():
            self.drawer.close_drawer()
            return
        win = self.window()
        if win.isFullScreen():
            win.showNormal()
            self.overlay.set_fullscreen(False)
            return
        self._on_back_clicked()

    def _on_back_clicked(self) -> None:
        self.keyboard.cancel_boost()
        self.stop_playback()
        self.exit_requested.emit()

    # -- Event propagation --
    def resizeEvent(self, _event) -> None:
        rect = self.rect()
        self.video_widget.setGeometry(rect)
        self.overlay.setGeometry(rect)
        self.drawer.setGeometry(rect)
        self.message_card.setGeometry(rect)
        # No raise_() juggling needed: with the mpv backend the video is an FBO
        # that Qt composites itself, so widgets created after it paint on top.
        # (QVideoWidget was a native window, which is why raise_() never helped.)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        # Fallback for moves that are delivered to the view instead of the
        # overlay (for example when the pointer leaves a child widget).
        self.overlay.show_controls()
        self.overlay.restart_auto_hide_timer()
        super().mouseMoveEvent(event)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.setFocus()
            self.overlay.show_controls()
            self.overlay.restart_auto_hide_timer()
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._toggle_fullscreen()
        super().mouseDoubleClickEvent(event)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if not self.keyboard.handle_key_press(event):
            super().keyPressEvent(event)

    def keyReleaseEvent(self, event: QKeyEvent) -> None:
        if not self.keyboard.handle_key_release(event):
            super().keyReleaseEvent(event)

    def closeEvent(self, event) -> None:
        self.exit_requested.emit()
        event.ignore()
