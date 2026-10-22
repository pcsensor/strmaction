"""Controls overlay: Top bar, Center feedback badges, and Bottom bar."""

from __future__ import annotations

from typing import Sequence
from PySide6.QtCore import QPoint, QRect, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QMouseEvent, QPainter, QPaintEvent
from PySide6.QtWidgets import (
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .icons import (
    PATH_BACK,
    PATH_EPISODES,
    PATH_FULLSCREEN,
    PATH_FULLSCREEN_EXIT,
    PATH_MORE,
    PATH_NEXT,
    PATH_PAUSE,
    PATH_PLAY,
    PATH_PREV,
    PATH_SPEED,
    make_svg_icon,
    make_svg_pixmap,
)
from .seekbar import BufferedSeekBar, format_time


class GradientBar(QWidget):
    """Bar with gradient black background for readability."""

    def __init__(self, is_top: bool = True, parent: QWidget | None = None):
        super().__init__(parent)
        self.is_top = is_top
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)

    def paintEvent(self, _event: QPaintEvent) -> None:
        painter = QPainter(self)
        w = float(self.width())
        h = float(self.height())
        if self.is_top:
            # Gradient top to bottom
            for y in range(int(h)):
                alpha = int(180 * (1.0 - y / h))
                painter.setPen(QColor(0, 0, 0, alpha))
                painter.drawLine(0, y, int(w), y)
        else:
            # Gradient bottom to top
            for y in range(int(h)):
                alpha = int(220 * (y / h))
                painter.setPen(QColor(0, 0, 0, alpha))
                painter.drawLine(0, y, int(w), y)
        painter.end()


class ControlsOverlay(QWidget):
    back_clicked = Signal()
    play_pause_clicked = Signal()
    prev_clicked = Signal()
    next_clicked = Signal()
    seek_requested = Signal(float)
    episodes_drawer_clicked = Signal()
    speed_drawer_clicked = Signal()
    tracks_drawer_clicked = Signal()
    fullscreen_clicked = Signal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setMouseTracking(True)

        self._is_paused: bool = False
        self._is_fullscreen: bool = False
        self._position: float = 0.0
        self._duration: float = 0.0
        self._is_seeking: bool = False

        # Auto-hide timer
        self._hide_timer = QTimer(self)
        self._hide_timer.setInterval(3500)
        self._hide_timer.timeout.connect(self._auto_hide)

        # Pulse fade-out timer for badges
        self._badge_fade_timer = QTimer(self)
        self._badge_fade_timer.setSingleShot(True)
        self._badge_fade_timer.setInterval(600)
        self._badge_fade_timer.timeout.connect(self._hide_transient_badges)

        self._init_ui()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # 1. Top Bar
        self.top_bar = GradientBar(is_top=True, parent=self)
        self.top_bar.setFixedHeight(72)
        top_layout = QHBoxLayout(self.top_bar)
        top_layout.setContentsMargins(20, 14, 20, 0)
        top_layout.setSpacing(14)

        # Back button
        self.btn_back = QPushButton(self.top_bar)
        self.btn_back.setIcon(make_svg_icon(PATH_BACK, "#FFFFFF", 24))
        self.btn_back.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_back.setStyleSheet(
            "QPushButton { background: rgba(0, 0, 0, 0.4); border: 1px solid rgba(255, 255, 255, 0.15); "
            "border-radius: 20px; width: 40px; height: 40px; }"
            "QPushButton:hover { background: rgba(255, 255, 255, 0.2); }"
        )
        self.btn_back.clicked.connect(self.back_clicked)
        top_layout.addWidget(self.btn_back)

        # Title & Episode label
        self.title_label = QLabel("正在加载...", self.top_bar)
        self.title_label.setStyleSheet(
            "color: #FFFFFF; font-size: 16px; font-weight: bold; text-shadow: 0 1px 3px rgba(0,0,0,0.8);"
        )
        top_layout.addWidget(self.title_label, stretch=1)

        layout.addWidget(self.top_bar)

        # 2. Center Area (Feedback Badges)
        self.center_area = QWidget(self)
        self.center_area.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        center_layout = QVBoxLayout(self.center_area)
        center_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # Speed Badge (e.g. "⚡ 2.0x 极速播放中")
        self.speed_badge = QLabel("⚡ 2.0x 极速播放中", self.center_area)
        self.speed_badge.setStyleSheet(
            "background: rgba(0, 0, 0, 0.85); color: #F0A94D; font-size: 15px; font-weight: bold; "
            "padding: 8px 18px; border-radius: 20px; border: 1px solid rgba(240, 169, 77, 0.6);"
        )
        self.speed_badge.setVisible(False)
        center_layout.addWidget(self.speed_badge, alignment=Qt.AlignmentFlag.AlignCenter)

        # Center pulse icon (Play/Pause)
        self.center_icon = QLabel(self.center_area)
        self.center_icon.setStyleSheet(
            "background: rgba(0, 0, 0, 0.6); padding: 18px; border-radius: 40px;"
        )
        self.center_icon.setVisible(False)
        center_layout.addWidget(self.center_icon, alignment=Qt.AlignmentFlag.AlignCenter)

        # Seek feedback badge (e.g. "+5s" / "-5s")
        self.seek_badge = QLabel("+5s", self.center_area)
        self.seek_badge.setStyleSheet(
            "background: rgba(0, 0, 0, 0.8); color: #FFFFFF; font-size: 16px; font-weight: bold; "
            "padding: 8px 16px; border-radius: 18px; border: 1px solid rgba(255, 255, 255, 0.2);"
        )
        self.seek_badge.setVisible(False)
        center_layout.addWidget(self.seek_badge, alignment=Qt.AlignmentFlag.AlignCenter)

        # Loading badge
        self.loading_badge = QLabel("缓冲中...", self.center_area)
        self.loading_badge.setStyleSheet(
            "background: rgba(0, 0, 0, 0.7); color: #B0B3B8; font-size: 13px; "
            "padding: 6px 14px; border-radius: 14px;"
        )
        self.loading_badge.setVisible(False)
        center_layout.addWidget(self.loading_badge, alignment=Qt.AlignmentFlag.AlignCenter)

        layout.addWidget(self.center_area, stretch=1)

        # 3. Bottom Bar
        self.bottom_bar = GradientBar(is_top=False, parent=self)
        self.bottom_bar.setFixedHeight(88)
        bottom_layout = QVBoxLayout(self.bottom_bar)
        bottom_layout.setContentsMargins(20, 0, 20, 12)
        bottom_layout.setSpacing(4)

        # 3.1 Seekbar
        self.seekbar = BufferedSeekBar(self.bottom_bar)
        self.seekbar.seek_requested.connect(self._on_seek_requested)
        self.seekbar.seeking_changed.connect(self._on_seeking_changed)
        bottom_layout.addWidget(self.seekbar)

        # 3.2 Controls Row
        ctrl_row = QHBoxLayout()
        ctrl_row.setContentsMargins(0, 0, 0, 0)
        ctrl_row.setSpacing(12)

        # Play/Pause button
        self.btn_play_pause = QPushButton(self.bottom_bar)
        self.btn_play_pause.setIcon(make_svg_icon(PATH_PAUSE, "#FFFFFF", 22))
        self.btn_play_pause.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_play_pause.setStyleSheet(
            "QPushButton { background: transparent; border: none; padding: 6px; border-radius: 4px; }"
            "QPushButton:hover { background: rgba(255, 255, 255, 0.15); }"
        )
        self.btn_play_pause.clicked.connect(self.play_pause_clicked)
        ctrl_row.addWidget(self.btn_play_pause)

        # Previous episode
        self.btn_prev = QPushButton(self.bottom_bar)
        self.btn_prev.setIcon(make_svg_icon(PATH_PREV, "#FFFFFF", 20))
        self.btn_prev.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_prev.setStyleSheet(
            "QPushButton { background: transparent; border: none; padding: 6px; border-radius: 4px; }"
            "QPushButton:hover { background: rgba(255, 255, 255, 0.15); }"
            "QPushButton:disabled { opacity: 0.3; }"
        )
        self.btn_prev.clicked.connect(self.prev_clicked)
        ctrl_row.addWidget(self.btn_prev)

        # Next episode
        self.btn_next = QPushButton(self.bottom_bar)
        self.btn_next.setIcon(make_svg_icon(PATH_NEXT, "#FFFFFF", 20))
        self.btn_next.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_next.setStyleSheet(
            "QPushButton { background: transparent; border: none; padding: 6px; border-radius: 4px; }"
            "QPushButton:hover { background: rgba(255, 255, 255, 0.15); }"
            "QPushButton:disabled { opacity: 0.3; }"
        )
        self.btn_next.clicked.connect(self.next_clicked)
        ctrl_row.addWidget(self.btn_next)

        # Time label
        self.time_label = QLabel("00:00 / 00:00", self.bottom_bar)
        self.time_label.setStyleSheet("color: #D1D5DB; font-size: 13px; font-weight: 500;")
        ctrl_row.addWidget(self.time_label)

        ctrl_row.addStretch()

        # Speed button (e.g. "1.0x")
        self.btn_speed = QPushButton("1.0x", self.bottom_bar)
        self.btn_speed.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_speed.setStyleSheet(
            "QPushButton { background: rgba(255, 255, 255, 0.08); color: #FFFFFF; font-size: 13px; "
            "font-weight: bold; border-radius: 14px; padding: 4px 12px; border: 1px solid rgba(255, 255, 255, 0.15); }"
            "QPushButton:hover { background: rgba(255, 255, 255, 0.2); border-color: #F0A94D; color: #F0A94D; }"
        )
        self.btn_speed.clicked.connect(self.speed_drawer_clicked)
        ctrl_row.addWidget(self.btn_speed)

        # Episodes button
        self.btn_episodes = QPushButton(self.bottom_bar)
        self.btn_episodes.setIcon(make_svg_icon(PATH_EPISODES, "#FFFFFF", 20))
        self.btn_episodes.setToolTip("选集")
        self.btn_episodes.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_episodes.setStyleSheet(
            "QPushButton { background: transparent; border: none; padding: 6px; border-radius: 4px; }"
            "QPushButton:hover { background: rgba(255, 255, 255, 0.15); }"
        )
        self.btn_episodes.clicked.connect(self.episodes_drawer_clicked)
        ctrl_row.addWidget(self.btn_episodes)

        # Tracks (audio/sub) button
        self.btn_tracks = QPushButton(self.bottom_bar)
        self.btn_tracks.setIcon(make_svg_icon(PATH_MORE, "#FFFFFF", 20))
        self.btn_tracks.setToolTip("音轨与字幕")
        self.btn_tracks.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_tracks.setStyleSheet(
            "QPushButton { background: transparent; border: none; padding: 6px; border-radius: 4px; }"
            "QPushButton:hover { background: rgba(255, 255, 255, 0.15); }"
        )
        self.btn_tracks.clicked.connect(self.tracks_drawer_clicked)
        ctrl_row.addWidget(self.btn_tracks)

        # Fullscreen button
        self.btn_fullscreen = QPushButton(self.bottom_bar)
        self.btn_fullscreen.setIcon(make_svg_icon(PATH_FULLSCREEN, "#FFFFFF", 20))
        self.btn_fullscreen.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_fullscreen.setStyleSheet(
            "QPushButton { background: transparent; border: none; padding: 6px; border-radius: 4px; }"
            "QPushButton:hover { background: rgba(255, 255, 255, 0.15); }"
        )
        self.btn_fullscreen.clicked.connect(self.fullscreen_clicked)
        ctrl_row.addWidget(self.btn_fullscreen)

        bottom_layout.addLayout(ctrl_row)
        layout.addWidget(self.bottom_bar)

    def set_title(self, title: str, series_title: str = "") -> None:
        full_title = f"{series_title} - {title}" if series_title and series_title != title else title
        self.title_label.setText(full_title)

    def set_position(self, seconds: float) -> None:
        self._position = seconds
        self.seekbar.set_position(seconds)
        self._update_time_label()

    def set_duration(self, seconds: float) -> None:
        self._duration = seconds
        self.seekbar.set_duration(seconds)
        self._update_time_label()

    def set_buffered_ranges(self, ranges: Sequence[tuple[float, float]]) -> None:
        self.seekbar.set_buffered_ranges(ranges)

    def set_paused(self, paused: bool) -> None:
        self._is_paused = paused
        icon_path = PATH_PLAY if paused else PATH_PAUSE
        self.btn_play_pause.setIcon(make_svg_icon(icon_path, "#FFFFFF", 22))
        if paused:
            self.show_controls()
        else:
            self.restart_auto_hide_timer()

    def set_speed_text(self, speed: float) -> None:
        self.btn_speed.setText(f"{speed:.2f}".rstrip("0").rstrip(".") + "x")

    def set_fullscreen(self, fullscreen: bool) -> None:
        self._is_fullscreen = fullscreen
        icon_path = PATH_FULLSCREEN_EXIT if fullscreen else PATH_FULLSCREEN
        self.btn_fullscreen.setIcon(make_svg_icon(icon_path, "#FFFFFF", 20))

    def set_nav_buttons(self, has_prev: bool, has_next: bool) -> None:
        self.btn_prev.setEnabled(has_prev)
        self.btn_next.setEnabled(has_next)

    def _update_time_label(self) -> None:
        cur_str = format_time(self._position)
        dur_str = format_time(self._duration)
        self.time_label.setText(f"{cur_str} / {dur_str}")

    def _on_seek_requested(self, target_sec: float) -> None:
        self.seek_requested.emit(target_sec)

    def _on_seeking_changed(self, is_seeking: bool) -> None:
        self._is_seeking = is_seeking
        if is_seeking:
            self._hide_timer.stop()
        else:
            self.restart_auto_hide_timer()

    # -- Feedback animations --
    def flash_center_play_pause(self, paused: bool) -> None:
        icon_path = PATH_PAUSE if paused else PATH_PLAY
        self.center_icon.setPixmap(make_svg_pixmap(icon_path, "#FFFFFF", 44))
        self.center_icon.setVisible(True)
        self._badge_fade_timer.start()

    def flash_seek_badge(self, text: str) -> None:
        self.seek_badge.setText(text)
        self.seek_badge.setVisible(True)
        self._badge_fade_timer.start()

    def show_speed_boost_badge(self, speed: float) -> None:
        self.speed_badge.setText(f"⚡ {speed}x 极速播放中")
        self.speed_badge.setVisible(True)

    def hide_speed_boost_badge(self) -> None:
        self.speed_badge.setVisible(False)

    def set_loading(self, loading: bool) -> None:
        self.loading_badge.setVisible(loading)

    def _hide_transient_badges(self) -> None:
        self.center_icon.setVisible(False)
        self.seek_badge.setVisible(False)

    # -- Auto hide logic --
    def mouseMoveEvent(self, _event: QMouseEvent) -> None:
        self.show_controls()
        self.restart_auto_hide_timer()

    def show_controls(self) -> None:
        self.top_bar.setVisible(True)
        self.bottom_bar.setVisible(True)
        self.setCursor(Qt.CursorShape.ArrowCursor)

    def restart_auto_hide_timer(self) -> None:
        self._hide_timer.start()

    def _auto_hide(self) -> None:
        if not self._is_paused and not self._is_seeking:
            self.top_bar.setVisible(False)
            self.bottom_bar.setVisible(False)
            self.setCursor(Qt.CursorShape.BlankCursor)
