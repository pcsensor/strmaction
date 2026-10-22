"""Integrated embedded PlayerView: video surface, overlay, drawer, keyboard."""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QKeyEvent, QMouseEvent
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtWidgets import QWidget

from ..security import PlaybackPayload
from .controller import QtPlayerController
from .drawer import PlayerDrawer
from .endcard import MessageCard
from .keyboard import KeyboardHandler
from .overlay import ControlsOverlay

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

        self._init_ui()
        self._init_keyboard()

    def _init_ui(self) -> None:
        # 1. Native Qt video surface widget (uses OS GPU via Direct3D/Metal)
        self.video_widget = QVideoWidget(self)
        self.video_widget.setStyleSheet("background-color: #000000;")

        # Built-in Qt multimedia controller
        self.controller = QtPlayerController(self)
        self.controller.set_video_output(self.video_widget)
        self._controller = self.controller

        # Wire controller signals
        self.controller.position_changed.connect(self._on_player_position)
        self.controller.duration_changed.connect(self._on_player_duration)
        self.controller.paused_changed.connect(self._on_player_paused)
        self.controller.speed_changed.connect(self._on_player_speed)
        self.controller.buffer_progress_changed.connect(self._on_player_buffer_progress)
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
            subtitle_hint=(
                "外挂字幕暂不支持内嵌播放器，请使用伴侣 App 或网页端观看。"
                if payload.subtitles
                else ""
            ),
        )

        self.setFocus()
        self.overlay.show_controls()
        self.overlay.restart_auto_hide_timer()

        # Load media into Qt player; resume offset is applied once loaded.
        self.controller.load_media(stream_url, start_ms=int(payload.resume_ms or 0))

    def stop_playback(self) -> None:
        self.message_card.hide_message()
        self.controller.stop()
        if self._reporter:
            try:
                self._reporter.stop(flush=True)
            except Exception:
                pass
            self._reporter = None

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

    def _on_player_buffer_progress(self, fraction: float) -> None:
        self.overlay.seekbar.set_buffer_progress(fraction)

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
                subs.append(
                    {
                        "id": track.get("id"),
                        "label": track.get("title") or f"字幕 #{track.get('id')}",
                    }
                )
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
            subtitle_hint=(
                "" if subs else
                ("片中无内嵌字幕；外挂字幕暂不支持。" if self._payload.subtitles
                 else "片中无字幕轨道")
            ),
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
        self.overlay.raise_()
        self.drawer.raise_()
        self.message_card.raise_()

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
