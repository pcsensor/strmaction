"""Buffered seekbar matching Android companion app (BufferedSeekBar.kt).

Features:
- 8px high track with rounded corners (semi-transparent white #3DFFFFFF).
- Played progress in golden orange (#F0A94D).
- 2.5px white cache/buffer lines overlaid on top (#E8FFFFFF).
- 3.5x16px white vertical pill head with rounded corners.
- Hover time tooltip preview.
"""

from __future__ import annotations

from typing import Sequence
from PySide6.QtCore import QPoint, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QMouseEvent, QPainter, QPaintEvent
from PySide6.QtWidgets import QToolTip, QWidget


def format_time(seconds: float) -> str:
    if seconds < 0:
        seconds = 0
    total_sec = int(seconds)
    hours = total_sec // 3600
    minutes = (total_sec % 3600) // 60
    secs = total_sec % 60
    if hours > 0:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


class BufferedSeekBar(QWidget):
    seek_requested = Signal(float)  # Emits target seconds
    seeking_changed = Signal(bool)  # Emits True when dragging, False on release

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setFixedHeight(32)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        self._position: float = 0.0
        self._duration: float = 0.0
        # List of (start_sec, end_sec) ranges
        self._buffered_ranges: list[tuple[float, float]] = []
        self._is_dragging: bool = False
        self._drag_position: float = 0.0

        # Colors matching Companion App
        self._track_color = QColor(255, 255, 255, 61)       # #3DFFFFFF
        self._played_color = QColor(240, 169, 77)           # #F0A94D
        self._buffered_color = QColor(255, 255, 255, 232)   # #E8FFFFFF
        self._head_color = QColor(255, 255, 255)           # #FFFFFF

    def set_position(self, seconds: float) -> None:
        if not self._is_dragging:
            if abs(self._position - seconds) > 0.05:
                self._position = max(0.0, seconds)
                self.update()

    def set_duration(self, seconds: float) -> None:
        if abs(self._duration - seconds) > 0.1:
            self._duration = max(0.0, seconds)
            self.update()

    def set_buffered_ranges(self, ranges: Sequence[tuple[float, float]]) -> None:
        self._buffered_ranges = list(ranges)
        self.update()

    def set_buffer_progress(self, progress: float) -> None:
        """Set buffer progress as a fraction 0.0 - 1.0."""
        if self._duration > 0:
            target_end = max(0.0, min(1.0, progress)) * self._duration
            self.set_buffer_end(target_end)

    def set_buffer_end(self, end_sec: float) -> None:
        """Convenience method to set forward buffer end. Preserves buffer stability during seek."""
        target = max(0.0, end_sec)
        # Avoid abrupt collapse to 0 while dragging or seeking
        if self._is_dragging and target == 0 and self._buffered_ranges:
            return
        if not self._buffered_ranges or abs(self._buffered_ranges[0][1] - target) > 0.3:
            self._buffered_ranges = [(0.0, target)]
            self.update()

    def _sec_to_x(self, sec: float, left: float, right: float) -> float:
        if self._duration <= 0:
            return left
        ratio = max(0.0, min(sec / self._duration, 1.0))
        return left + ratio * (right - left)

    def _x_to_sec(self, x: float, left: float, right: float) -> float:
        if right <= left or self._duration <= 0:
            return 0.0
        ratio = max(0.0, min((x - left) / (right - left), 1.0))
        return ratio * self._duration

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._is_dragging = True
            self.seeking_changed.emit(True)
            head_half = 1.75
            left = 10.0 + head_half
            right = self.width() - 10.0 - head_half
            self._drag_position = self._x_to_sec(event.position().x(), left, right)
            self.update()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        head_half = 1.75
        left = 10.0 + head_half
        right = self.width() - 10.0 - head_half
        target_sec = self._x_to_sec(event.position().x(), left, right)

        if self._is_dragging:
            self._drag_position = target_sec
            self.update()

        # Tooltip with time preview
        if self._duration > 0:
            QToolTip.showText(
                event.globalPosition().toPoint(),
                format_time(target_sec),
                self,
            )

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self._is_dragging:
            self._is_dragging = False
            self.seeking_changed.emit(False)
            head_half = 1.75
            left = 10.0 + head_half
            right = self.width() - 10.0 - head_half
            target_sec = self._x_to_sec(event.position().x(), left, right)
            self._position = target_sec
            self.seek_requested.emit(target_sec)
            self.update()

    def paintEvent(self, _event: QPaintEvent) -> None:
        w = float(self.width())
        h = float(self.height())
        if w <= 0 or h <= 0:
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        head_w = 3.5
        head_h = 16.0
        head_half = head_w / 2.0
        left = 10.0 + head_half
        right = w - 10.0 - head_half
        center_y = h / 2.0
        track_h = 8.0
        track_radius = track_h / 2.0

        if right <= left:
            painter.end()
            return

        # 1. Base Track: 8px height, rounded corners
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(self._track_color)
        painter.drawRoundedRect(
            QRectF(left, center_y - track_radius, right - left, track_h),
            track_radius,
            track_radius,
        )

        pos_sec = self._drag_position if self._is_dragging else self._position
        head_x = self._sec_to_x(pos_sec, left, right)

        # 2. Played bar: From left to head_x
        if head_x > left:
            played_w = head_x - left
            painter.setBrush(self._played_color)
            painter.drawRoundedRect(
                QRectF(left, center_y - track_radius, played_w, track_h),
                track_radius,
                track_radius,
            )

        # 3. Buffered line: 2.5px height white line on top
        if self._buffered_ranges:
            line_h = 2.5
            painter.setBrush(self._buffered_color)
            for b_start, b_end in self._buffered_ranges:
                if b_end <= b_start:
                    continue
                bx1 = self._sec_to_x(b_start, left, right)
                bx2 = self._sec_to_x(b_end, left, right)
                if bx2 > bx1:
                    painter.drawRoundedRect(
                        QRectF(bx1, center_y - line_h / 2.0, bx2 - bx1, line_h),
                        1.0,
                        1.0,
                    )

        # 4. Playhead (thumb): 3.5x16px white vertical pill, centered vertically
        painter.setBrush(self._head_color)
        painter.drawRoundedRect(
            QRectF(head_x - head_half, center_y - head_h / 2.0, head_w, head_h),
            head_half,
            head_half,
        )

        painter.end()
