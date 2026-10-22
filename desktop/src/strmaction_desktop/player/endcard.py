"""Centered end-of-playback / error card for the embedded player."""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

_CARD_STYLE = """
QFrame#StrmActionCard {
    background: rgba(12, 15, 20, 0.94);
    border: 1px solid rgba(255, 255, 255, 0.12);
    border-radius: 18px;
}
"""

_PRIMARY_STYLE = """
QPushButton {
    background: #F0A94D; color: #17120B; border: none; border-radius: 10px;
    padding: 10px 22px; font-size: 14px; font-weight: bold;
}
QPushButton:hover { background: #F6BA66; }
"""

_SECONDARY_STYLE = """
QPushButton {
    background: rgba(255, 255, 255, 0.08); color: #E8EAEF;
    border: 1px solid rgba(255, 255, 255, 0.16); border-radius: 10px;
    padding: 10px 22px; font-size: 14px;
}
QPushButton:hover { background: rgba(255, 255, 255, 0.16); }
"""


class MessageCard(QWidget):
    """Blocks the video area with a short message and up to two actions."""

    primary_clicked = Signal()
    secondary_clicked = Signal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.hide()

        outer = QVBoxLayout(self)
        outer.setContentsMargins(40, 40, 40, 40)
        outer.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.panel = QFrame(self)
        self.panel.setObjectName("StrmActionCard")
        self.panel.setStyleSheet(_CARD_STYLE)
        self.panel.setFixedWidth(420)

        panel_layout = QVBoxLayout(self.panel)
        panel_layout.setContentsMargins(28, 24, 28, 22)
        panel_layout.setSpacing(10)

        self.title_label = QLabel("", self.panel)
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        self.title_label.setStyleSheet(
            "color: #FFFFFF; font-size: 19px; font-weight: bold;"
        )
        panel_layout.addWidget(self.title_label)

        self.desc_label = QLabel("", self.panel)
        self.desc_label.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        self.desc_label.setWordWrap(True)
        self.desc_label.setStyleSheet("color: #A9B0BE; font-size: 12.5px;")
        self.desc_label.setVisible(False)
        panel_layout.addWidget(self.desc_label)

        buttons = QHBoxLayout()
        buttons.setContentsMargins(0, 10, 0, 0)
        buttons.setSpacing(10)
        buttons.setAlignment(Qt.AlignmentFlag.AlignHCenter)

        self.btn_primary = QPushButton(self.panel)
        self.btn_primary.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_primary.setStyleSheet(_PRIMARY_STYLE)
        self.btn_primary.setVisible(False)
        self.btn_primary.clicked.connect(self._on_primary)
        buttons.addWidget(self.btn_primary)

        self.btn_secondary = QPushButton(self.panel)
        self.btn_secondary.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_secondary.setStyleSheet(_SECONDARY_STYLE)
        self.btn_secondary.setVisible(False)
        self.btn_secondary.clicked.connect(self._on_secondary)
        buttons.addWidget(self.btn_secondary)

        panel_layout.addLayout(buttons)
        outer.addWidget(self.panel)

        self._countdown = 0
        self._primary_text = ""
        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self._tick)

    # -- public API -----------------------------------------------------
    @property
    def is_shown(self) -> bool:
        return self.isVisible()

    def show_message(
        self,
        title: str,
        description: str = "",
        *,
        primary: str | None = None,
        secondary: str | None = None,
        countdown: int | None = None,
    ) -> None:
        self.title_label.setText(title)
        self.desc_label.setText(description)
        self.desc_label.setVisible(bool(description))

        self._primary_text = primary or ""
        self.btn_primary.setVisible(bool(primary))
        self.btn_secondary.setVisible(bool(secondary))
        if secondary:
            self.btn_secondary.setText(secondary)

        self._timer.stop()
        if countdown and primary:
            self._countdown = int(countdown)
            self.btn_primary.setText(f"{primary} ({self._countdown})")
            self._timer.start()
        else:
            self._countdown = 0
            self.btn_primary.setText(self._primary_text)

        self.show()
        self.raise_()

    def hide_message(self) -> None:
        self._timer.stop()
        self._countdown = 0
        self.hide()

    # -- internals ------------------------------------------------------
    def _tick(self) -> None:
        self._countdown -= 1
        if self._countdown > 0:
            self.btn_primary.setText(f"{self._primary_text} ({self._countdown})")
            return
        self._timer.stop()
        self.hide()
        self.primary_clicked.emit()

    def _on_primary(self) -> None:
        self._timer.stop()
        self.hide()
        self.primary_clicked.emit()

    def _on_secondary(self) -> None:
        self._timer.stop()
        self.hide()
        self.secondary_clicked.emit()
