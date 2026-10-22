"""40% Right-side drawer for Episodes, Speed, and Tracks (PlayerDrawer.kt)."""

from __future__ import annotations

from typing import Any, Sequence
from PySide6.QtCore import QEasingCurve, QPropertyAnimation, QRect, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPaintEvent
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from .icons import PATH_CLOSE, make_svg_icon


class DrawerContentWidget(QWidget):
    """Container with #13161F background and rounded left corners."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)

    def paintEvent(self, _event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(Qt.PenStyle.NoPen)
        # 0xF713161F dark blue-gray with 97% opacity
        painter.setBrush(QColor(19, 22, 31, 248))
        # Draw rounded on left side
        w = float(self.width())
        h = float(self.height())
        r = 16.0
        # Draw base rect and left round
        painter.drawRoundedRect(0, 0, w + r, h, r, r)
        painter.end()


class PlayerDrawer(QWidget):
    closed = Signal()
    episode_selected = Signal(int)  # item_id
    speed_selected = Signal(float)  # speed multiplier
    subtitle_selected = Signal(object)  # sid (int or str)
    audio_selected = Signal(object)  # aid (int or str)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setVisible(False)

        # State
        self._current_tab: str = "episodes"  # "episodes" | "speed" | "tracks"
        self._playlist: list[dict] = []
        self._current_item_id: int = 0
        self._current_speed: float = 1.0
        self._subtitles: list[dict] = []
        self._audio_tracks: list[dict] = []
        self._current_sid: Any = None
        self._current_aid: Any = None

        self._init_ui()

    def _init_ui(self) -> None:
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # 1. Left semi-transparent backdrop (click to close)
        self.backdrop = QWidget(self)
        self.backdrop.setStyleSheet("background-color: rgba(0, 0, 0, 140);")
        self.backdrop.mousePressEvent = lambda _e: self.close_drawer()
        main_layout.addWidget(self.backdrop, stretch=6)

        # 2. Right content drawer (40% width)
        self.drawer_widget = DrawerContentWidget(self)
        drawer_layout = QVBoxLayout(self.drawer_widget)
        drawer_layout.setContentsMargins(20, 24, 20, 24)
        drawer_layout.setSpacing(16)

        # Header: Title & Close Button
        header_layout = QHBoxLayout()
        header_layout.setContentsMargins(0, 0, 0, 0)

        self.title_label = QLabel("选集", self.drawer_widget)
        self.title_label.setStyleSheet(
            "color: #FFFFFF; font-size: 18px; font-weight: bold;"
        )
        header_layout.addWidget(self.title_label)

        header_layout.addStretch()

        close_btn = QPushButton(self.drawer_widget)
        close_btn.setIcon(make_svg_icon(PATH_CLOSE, "#AAAAAA", 20))
        close_btn.setStyleSheet(
            "QPushButton { background: transparent; border: none; padding: 4px; border-radius: 4px; }"
            "QPushButton:hover { background: rgba(255, 255, 255, 0.1); }"
        )
        close_btn.clicked.connect(self.close_drawer)
        header_layout.addWidget(close_btn)
        drawer_layout.addLayout(header_layout)

        # Tabs bar (选集 / 倍速 / 音轨与字幕)
        self.tabs_layout = QHBoxLayout()
        self.tabs_layout.setSpacing(8)
        self.btn_tab_episodes = self._make_tab_btn("选集", "episodes")
        self.btn_tab_speed = self._make_tab_btn("倍速", "speed")
        self.btn_tab_tracks = self._make_tab_btn("音轨与字幕", "tracks")
        self.tabs_layout.addWidget(self.btn_tab_episodes)
        self.tabs_layout.addWidget(self.btn_tab_speed)
        self.tabs_layout.addWidget(self.btn_tab_tracks)
        self.tabs_layout.addStretch()
        drawer_layout.addLayout(self.tabs_layout)

        # Scrollable content area
        self.scroll_area = QScrollArea(self.drawer_widget)
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setStyleSheet(
            "QScrollArea { background: transparent; border: none; }"
            "QScrollBar:vertical { background: transparent; width: 6px; margin: 0; }"
            "QScrollBar::handle:vertical { background: rgba(255, 255, 255, 0.2); border-radius: 3px; }"
            "QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }"
        )
        self.scroll_content = QWidget()
        self.scroll_content.setStyleSheet("background: transparent;")
        self.content_vbox = QVBoxLayout(self.scroll_content)
        self.content_vbox.setContentsMargins(0, 0, 0, 0)
        self.content_vbox.setSpacing(8)
        self.scroll_area.setWidget(self.scroll_content)

        drawer_layout.addWidget(self.scroll_area, stretch=1)
        main_layout.addWidget(self.drawer_widget, stretch=4)

    def _make_tab_btn(self, text: str, tab_id: str) -> QPushButton:
        btn = QPushButton(text, self.drawer_widget)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.clicked.connect(lambda: self.switch_tab(tab_id))
        return btn

    def _update_tab_styles(self) -> None:
        for tab_id, btn in (
            ("episodes", self.btn_tab_episodes),
            ("speed", self.btn_tab_speed),
            ("tracks", self.btn_tab_tracks),
        ):
            if tab_id == self._current_tab:
                btn.setStyleSheet(
                    "QPushButton { background: rgba(240, 169, 77, 0.2); color: #F0A94D; "
                    "font-size: 13px; font-weight: bold; border: 1px solid #F0A94D; "
                    "border-radius: 14px; padding: 4px 12px; }"
                )
            else:
                btn.setStyleSheet(
                    "QPushButton { background: rgba(255, 255, 255, 0.08); color: #8E9297; "
                    "font-size: 13px; border: 1px solid transparent; "
                    "border-radius: 14px; padding: 4px 12px; }"
                    "QPushButton:hover { background: rgba(255, 255, 255, 0.15); color: #FFFFFF; }"
                )

    def switch_tab(self, tab_id: str) -> None:
        self._current_tab = tab_id
        self._update_tab_styles()
        self._rebuild_content()

    def set_data(
        self,
        *,
        playlist: Sequence[dict] | None = None,
        current_item_id: int | None = None,
        current_speed: float | None = None,
        subtitles: Sequence[dict] | None = None,
        audio_tracks: Sequence[dict] | None = None,
        current_sid: Any = None,
        current_aid: Any = None,
    ) -> None:
        if playlist is not None:
            self._playlist = list(playlist)
            self.btn_tab_episodes.setVisible(len(self._playlist) > 1)
        if current_item_id is not None:
            self._current_item_id = current_item_id
        if current_speed is not None:
            self._current_speed = current_speed
        if subtitles is not None:
            self._subtitles = list(subtitles)
        if audio_tracks is not None:
            self._audio_tracks = list(audio_tracks)
        if current_sid is not None:
            self._current_sid = current_sid
        if current_aid is not None:
            self._current_aid = current_aid

        # Auto-switch to speed/tracks if single video has no playlist
        if len(self._playlist) <= 1 and self._current_tab == "episodes":
            self._current_tab = "speed"

        self._update_tab_styles()
        self._rebuild_content()

    def _clear_content(self) -> None:
        while self.content_vbox.count() > 0:
            item = self.content_vbox.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def _rebuild_content(self) -> None:
        self._clear_content()

        if self._current_tab == "episodes":
            self.title_label.setText(f"选集 ({len(self._playlist)})")
            for ep in self._playlist:
                item_id = ep.get("item_id")
                is_current = item_id == self._current_item_id
                code = ep.get("code") or f"P{ep.get('episode_no', 0):02d}"
                title = ep.get("title") or ""
                watched = ep.get("watched", False)

                btn = QPushButton(self.scroll_content)
                btn.setCursor(Qt.CursorShape.PointingHandCursor)
                btn.setFixedHeight(50)

                # Layout inside episode card
                h_card = QHBoxLayout(btn)
                h_card.setContentsMargins(12, 6, 12, 6)

                code_lbl = QLabel(code, btn)
                code_lbl.setStyleSheet(
                    f"font-size: 14px; font-weight: bold; color: {'#F0A94D' if is_current else '#FFFFFF'};"
                )
                h_card.addWidget(code_lbl)

                title_lbl = QLabel(title, btn)
                title_lbl.setStyleSheet(
                    f"font-size: 13px; color: {'#F0A94D' if is_current else '#B0B3B8'};"
                )
                h_card.addWidget(title_lbl, stretch=1)

                if watched:
                    w_badge = QLabel("已看", btn)
                    w_badge.setStyleSheet(
                        "font-size: 10px; color: #8E9297; background: rgba(255, 255, 255, 0.1); "
                        "padding: 2px 6px; border-radius: 4px;"
                    )
                    h_card.addWidget(w_badge)

                if is_current:
                    btn.setStyleSheet(
                        "QPushButton { background: rgba(240, 169, 77, 0.15); "
                        "border: 1.5px solid #F0A94D; border-radius: 8px; }"
                    )
                else:
                    btn.setStyleSheet(
                        "QPushButton { background: rgba(255, 255, 255, 0.05); "
                        "border: 1px solid transparent; border-radius: 8px; }"
                        "QPushButton:hover { background: rgba(255, 255, 255, 0.12); border-color: rgba(255, 255, 255, 0.2); }"
                    )

                if item_id is not None:
                    btn.clicked.connect(
                        lambda _checked=False, i_id=item_id: self._select_episode(i_id)
                    )
                self.content_vbox.addWidget(btn)

        elif self._current_tab == "speed":
            self.title_label.setText("播放倍速")
            speeds = [0.5, 0.75, 1.0, 1.25, 1.5, 2.0, 3.0]
            for s in speeds:
                is_cur = abs(s - self._current_speed) < 0.01
                btn = QPushButton(f"{s:.2f}".rstrip("0").rstrip(".") + "x", self.scroll_content)
                btn.setCursor(Qt.CursorShape.PointingHandCursor)
                btn.setFixedHeight(44)
                if is_cur:
                    btn.setStyleSheet(
                        "QPushButton { background: rgba(240, 169, 77, 0.2); color: #F0A94D; "
                        "font-size: 15px; font-weight: bold; border: 1px solid #F0A94D; border-radius: 8px; }"
                    )
                else:
                    btn.setStyleSheet(
                        "QPushButton { background: rgba(255, 255, 255, 0.05); color: #FFFFFF; "
                        "font-size: 14px; border: none; border-radius: 8px; }"
                        "QPushButton:hover { background: rgba(255, 255, 255, 0.12); }"
                    )
                btn.clicked.connect(lambda _c=False, sp=s: self._select_speed(sp))
                self.content_vbox.addWidget(btn)

        elif self._current_tab == "tracks":
            self.title_label.setText("音轨与字幕")

            # Subtitles section
            sub_title = QLabel("字幕", self.scroll_content)
            sub_title.setStyleSheet("color: #F0A94D; font-size: 14px; font-weight: bold; margin-top: 4px;")
            self.content_vbox.addWidget(sub_title)

            # Option to turn off subtitles
            off_btn = QPushButton("关闭字幕", self.scroll_content)
            off_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            off_btn.setFixedHeight(40)
            is_off = self._current_sid in (None, "no", False, 0)
            self._style_track_btn(off_btn, is_off)
            off_btn.clicked.connect(lambda: self.subtitle_selected.emit("no"))
            self.content_vbox.addWidget(off_btn)

            for sub in self._subtitles:
                sid = sub.get("id") or sub.get("url")
                label = sub.get("label") or sub.get("lang") or sub.get("title") or "字幕"
                btn = QPushButton(label, self.scroll_content)
                btn.setCursor(Qt.CursorShape.PointingHandCursor)
                btn.setFixedHeight(40)
                is_active = self._current_sid == sid
                self._style_track_btn(btn, is_active)
                btn.clicked.connect(lambda _c=False, s_id=sid: self.subtitle_selected.emit(s_id))
                self.content_vbox.addWidget(btn)

            # Audio tracks section
            audio_title = QLabel("音轨", self.scroll_content)
            audio_title.setStyleSheet("color: #F0A94D; font-size: 14px; font-weight: bold; margin-top: 14px;")
            self.content_vbox.addWidget(audio_title)

            if not self._audio_tracks:
                hint = QLabel("暂无额外音轨", self.scroll_content)
                hint.setStyleSheet("color: #8E9297; font-size: 12px;")
                self.content_vbox.addWidget(hint)
            else:
                for audio in self._audio_tracks:
                    aid = audio.get("id")
                    label = audio.get("title") or audio.get("lang") or f"音轨 #{aid}"
                    btn = QPushButton(label, self.scroll_content)
                    btn.setCursor(Qt.CursorShape.PointingHandCursor)
                    btn.setFixedHeight(40)
                    is_active = self._current_aid == aid
                    self._style_track_btn(btn, is_active)
                    btn.clicked.connect(lambda _c=False, a_id=aid: self.audio_selected.emit(a_id))
                    self.content_vbox.addWidget(btn)

        self.content_vbox.addStretch()

    def _style_track_btn(self, btn: QPushButton, is_active: bool) -> None:
        if is_active:
            btn.setStyleSheet(
                "QPushButton { background: rgba(240, 169, 77, 0.2); color: #F0A94D; "
                "font-size: 13px; font-weight: bold; border: 1px solid #F0A94D; border-radius: 6px; text-align: left; padding-left: 12px; }"
            )
        else:
            btn.setStyleSheet(
                "QPushButton { background: rgba(255, 255, 255, 0.05); color: #FFFFFF; "
                "font-size: 13px; border: none; border-radius: 6px; text-align: left; padding-left: 12px; }"
                "QPushButton:hover { background: rgba(255, 255, 255, 0.12); }"
            )

    def _select_episode(self, item_id: int) -> None:
        self._current_item_id = item_id
        self._rebuild_content()
        self.episode_selected.emit(item_id)

    def _select_speed(self, speed: float) -> None:
        self._current_speed = speed
        self._rebuild_content()
        self.speed_selected.emit(speed)

    def open_tab(self, tab_id: str) -> None:
        self.switch_tab(tab_id)
        self.show()
        self.raise_()

    def close_drawer(self) -> None:
        self.hide()
        self.closed.emit()
