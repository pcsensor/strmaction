"""Integrated embedded PlayerView combining video surface, overlay, drawer, and keyboard handler."""

from __future__ import annotations

from typing import Any, Callable, Sequence
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QKeyEvent, QMouseEvent
from PySide6.QtWidgets import QWidget

from ..security import PlaybackPayload
from .drawer import PlayerDrawer
from .keyboard import KeyboardHandler
from .overlay import ControlsOverlay


class PlayerView(QWidget):
    exit_requested = Signal()
    next_episode_requested = Signal(int)  # item_id

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setStyleSheet("background-color: #000000;")
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMouseTracking(True)

        self._controller = None  # MpvController
        self._payload: PlaybackPayload | None = None
        self._normal_speed: float = 1.0
        self._is_paused: bool = False
        self._duration: float = 0.0

        self._init_ui()
        self._init_keyboard()

    def _init_ui(self) -> None:
        # 1. Native video surface widget (where mpv draws via --wid)
        self.video_widget = QWidget(self)
        self.video_widget.setAttribute(Qt.WidgetAttribute.WA_NativeWindow, True)
        self.video_widget.setStyleSheet("background-color: #000000;")

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

    def get_video_wid(self) -> int:
        return int(self.video_widget.winId())

    def bind_controller(self, controller, payload: PlaybackPayload) -> None:
        self._controller = controller
        self._payload = payload
        self._normal_speed = 1.0
        self._is_paused = False
        self._duration = (payload.duration_ms or 0) / 1000.0 if payload.duration_ms else 0.0

        # Setup Overlay UI
        self.overlay.set_title(payload.title, payload.series_title)
        self.overlay.set_duration(self._duration)
        self.overlay.set_position((payload.resume_ms or 0) / 1000.0)
        self.overlay.set_speed_text(1.0)
        self.overlay.set_paused(False)

        # Prev / Next navigation
        has_prev, has_next = self._check_nav_available(payload)
        self.overlay.set_nav_buttons(has_prev, has_next)

        # Setup Drawer UI
        self.drawer.set_data(
            playlist=payload.playlist,
            current_item_id=payload.item_id,
            current_speed=1.0,
            subtitles=[{"label": s.label, "url": s.url} for s in payload.subtitles],
        )

        self.setFocus()
        self.overlay.show_controls()
        self.overlay.restart_auto_hide_timer()

    def _check_nav_available(self, payload: PlaybackPayload) -> tuple[bool, bool]:
        if not payload.playlist or payload.current_index < 0:
            return False, payload.next_item_id is not None
        has_prev = payload.current_index > 0
        has_next = payload.current_index + 1 < len(payload.playlist) or payload.next_item_id is not None
        return has_prev, has_next

    # -- MPV Event Listeners --
    def on_mpv_position(self, seconds: float) -> None:
        self.overlay.set_position(seconds)

    def on_mpv_duration(self, seconds: float) -> None:
        self._duration = seconds
        self.overlay.set_duration(seconds)

    def on_mpv_paused(self, paused: bool) -> None:
        self._is_paused = paused
        self.overlay.set_paused(paused)

    def on_mpv_speed(self, speed: float) -> None:
        if not self.keyboard._is_speed_boost_active:
            self._normal_speed = speed
        self.overlay.set_speed_text(speed)
        self.drawer.set_data(current_speed=speed)

    def on_mpv_cache_state(self, cache_info: dict) -> None:
        if not isinstance(cache_info, dict):
            return
        # Calculate forward buffered seconds
        cache_duration = cache_info.get("cache-duration", 0)
        if cache_duration and self.overlay._position >= 0:
            b_end = self.overlay._position + float(cache_duration)
            self.overlay.seekbar.set_buffer_end(b_end)

    def on_mpv_tracks(self, tracks: list[dict]) -> None:
        if not isinstance(tracks, list):
            return
        subs = []
        audios = []
        cur_sid = None
        cur_aid = None
        for t in tracks:
            t_type = t.get("type")
            t_id = t.get("id")
            selected = t.get("selected", False)
            title = t.get("title") or t.get("lang") or f"#{t_id}"
            if t_type == "sub":
                subs.append({"id": t_id, "label": title, "selected": selected})
                if selected:
                    cur_sid = t_id
            elif t_type == "audio":
                audios.append({"id": t_id, "title": title, "selected": selected})
                if selected:
                    cur_aid = t_id
        self.drawer.set_data(
            subtitles=subs,
            audio_tracks=audios,
            current_sid=cur_sid,
            current_aid=cur_aid,
        )

    def on_mpv_idle(self, is_idle: bool) -> None:
        self.overlay.set_loading(is_idle)

    # -- User Interactions --
    def _toggle_play_pause(self) -> None:
        if self._controller:
            new_pause = not self._is_paused
            self._controller.set_pause(new_pause)
            self.overlay.flash_center_play_pause(new_pause)

    def _on_seek_requested(self, target_sec: float) -> None:
        if self._controller:
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
            cur_vol = getattr(self._controller, "volume", 100) or 100
            new_vol = max(0, min(100, cur_vol + delta))
            self._controller.set_volume(new_vol)
            self.overlay.flash_seek_badge(f"音量 {new_vol}%")

    def _cycle_subtitle(self) -> None:
        if self._controller:
            self._controller.cycle_sub()
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
        if self._controller:
            self._controller.set_sub(sid)

    def _on_audio_selected(self, aid: Any) -> None:
        if self._controller:
            self._controller.set_audio(aid)

    def _play_prev_episode(self) -> None:
        if not self._payload or not self._payload.playlist:
            return
        idx = self._payload.current_index
        if idx > 0:
            prev_ep = self._payload.playlist[idx - 1]
            prev_id = prev_ep.get("item_id")
            if prev_id:
                self.next_episode_requested.emit(prev_id)

    def _play_next_episode(self) -> None:
        if not self._payload:
            return
        if self._payload.playlist and self._payload.current_index >= 0:
            idx = self._payload.current_index
            if idx + 1 < len(self._payload.playlist):
                next_ep = self._payload.playlist[idx + 1]
                next_id = next_ep.get("item_id")
                if next_id:
                    self.next_episode_requested.emit(next_id)
                    return
        if self._payload.next_item_id:
            self.next_episode_requested.emit(self._payload.next_item_id)

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
        self.exit_requested.emit()

    # -- Event propagation --
    def resizeEvent(self, _event) -> None:
        rect = self.rect()
        self.video_widget.setGeometry(rect)
        self.overlay.setGeometry(rect)
        self.drawer.setGeometry(rect)
        self.overlay.raise_()
        self.drawer.raise_()

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
