"""Keyboard shortcuts controller with Right-arrow hold-to-speed state machine."""

from __future__ import annotations

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtGui import QKeyEvent


class KeyboardHandler(QObject):
    play_pause_toggled = Signal()
    seek_relative = Signal(float)  # seconds (+5 or -5)
    speed_boost_started = Signal(float)  # target fast speed, e.g. 2.0
    speed_boost_ended = Signal()
    volume_relative = Signal(int)  # delta percent (+5 or -5)
    mute_toggled = Signal()
    fullscreen_toggled = Signal()
    escape_pressed = Signal()
    prev_episode_requested = Signal()
    next_episode_requested = Signal()
    cycle_subtitle_requested = Signal()
    cycle_audio_requested = Signal()
    toggle_drawer_requested = Signal()

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self.fast_speed: float = 2.0

        # State for Right Arrow key
        self._right_pressed: bool = False
        self._is_speed_boost_active: bool = False

        self._hold_timer = QTimer(self)
        self._hold_timer.setSingleShot(True)
        self._hold_timer.setInterval(250)  # 250ms threshold for hold-to-speed
        self._hold_timer.timeout.connect(self._on_hold_timer_fired)

    def handle_key_press(self, event: QKeyEvent) -> bool:
        key = event.key()

        # 1. Space: Play / Pause toggle
        if key == Qt.Key.Key_Space:
            if not event.isAutoRepeat():
                self.play_pause_toggled.emit()
            return True

        # 2. Right Arrow: Hold to 2.0x speed vs click to seek +5s
        if key == Qt.Key.Key_Right:
            if not event.isAutoRepeat():
                self._right_pressed = True
                self._is_speed_boost_active = False
                self._hold_timer.start()
            return True  # Consume all auto-repeat events to prevent seek storm

        # 3. Left Arrow: Seek -5s
        if key == Qt.Key.Key_Left:
            if not event.isAutoRepeat():
                self.seek_relative.emit(-5.0)
            return True

        # 4. Volume Up / Down
        if key == Qt.Key.Key_Up:
            self.volume_relative.emit(5)
            return True
        if key == Qt.Key.Key_Down:
            self.volume_relative.emit(-5)
            return True

        # 5. Mute
        if key == Qt.Key.Key_M and not event.isAutoRepeat():
            self.mute_toggled.emit()
            return True

        # 6. Fullscreen
        if key in (Qt.Key.Key_F, Qt.Key.Key_F11) and not event.isAutoRepeat():
            self.fullscreen_toggled.emit()
            return True

        # 7. Escape
        if key == Qt.Key.Key_Escape and not event.isAutoRepeat():
            self.escape_pressed.emit()
            return True

        # 8. Previous / Next episode: [ / ]
        if key == Qt.Key.Key_BracketLeft and not event.isAutoRepeat():
            self.prev_episode_requested.emit()
            return True
        if key == Qt.Key.Key_BracketRight and not event.isAutoRepeat():
            self.next_episode_requested.emit()
            return True

        # 9. Subtitle: C or S
        if key in (Qt.Key.Key_C, Qt.Key.Key_S) and not event.isAutoRepeat():
            self.cycle_subtitle_requested.emit()
            return True

        # 10. Audio: A
        if key == Qt.Key.Key_A and not event.isAutoRepeat():
            self.cycle_audio_requested.emit()
            return True

        # 11. Drawer toggle: E or Tab
        if key in (Qt.Key.Key_E, Qt.Key.Key_Tab) and not event.isAutoRepeat():
            self.toggle_drawer_requested.emit()
            return True

        return False

    def handle_key_release(self, event: QKeyEvent) -> bool:
        key = event.key()

        if key == Qt.Key.Key_Right:
            # Ignore OS auto-repeat release signals
            if event.isAutoRepeat():
                return True

            self._right_pressed = False
            self._hold_timer.stop()

            if self._is_speed_boost_active:
                # Long press finished, restore original speed
                self._is_speed_boost_active = False
                self.speed_boost_ended.emit()
            else:
                # Released before 250ms threshold: treat as single click seek +5s
                self.seek_relative.emit(5.0)
            return True

        return False

    def _on_hold_timer_fired(self) -> None:
        """Triggered when Right key has been continuously held for > 250ms."""
        if self._right_pressed:
            self._is_speed_boost_active = True
            self.speed_boost_started.emit(self.fast_speed)

    def cancel_boost(self) -> None:
        self._right_pressed = False
        self._hold_timer.stop()
        if self._is_speed_boost_active:
            self._is_speed_boost_active = False
            self.speed_boost_ended.emit()
