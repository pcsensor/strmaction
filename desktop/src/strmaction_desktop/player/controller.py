"""In-process media player controller wrapping PySide6 QtMultimedia.

Replaces external mpv process with native QMediaPlayer and QAudioOutput.
"""

from __future__ import annotations

import logging
from PySide6.QtCore import QObject, QUrl, Signal, Slot
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer

logger = logging.getLogger(__name__)


class QtPlayerController(QObject):
    """Wraps QMediaPlayer and QAudioOutput into a unified playback controller."""

    position_changed = Signal(float)       # current position in seconds
    duration_changed = Signal(float)       # duration in seconds
    paused_changed = Signal(bool)          # True if paused
    speed_changed = Signal(float)          # playback rate
    buffer_progress_changed = Signal(float)  # 0.0 to 1.0
    loading_changed = Signal(bool)         # True when buffering/loading
    error_occurred = Signal(str)

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)

        self._player = QMediaPlayer(self)
        self._audio_output = QAudioOutput(self)
        self._player.setAudioOutput(self._audio_output)

        self._duration_sec: float = 0.0
        self._position_sec: float = 0.0
        self._is_paused: bool = False
        self._speed: float = 1.0

        # Wire QMediaPlayer signals
        self._player.positionChanged.connect(self._on_position_changed)
        self._player.durationChanged.connect(self._on_duration_changed)
        self._player.playbackRateChanged.connect(self._on_playback_rate_changed)
        self._player.bufferProgressChanged.connect(self._on_buffer_progress_changed)
        self._player.playbackStateChanged.connect(self._on_playback_state_changed)
        self._player.mediaStatusChanged.connect(self._on_media_status_changed)
        self._player.errorOccurred.connect(self._on_error_occurred)

    def set_video_output(self, video_widget) -> None:
        self._player.setVideoOutput(video_widget)

    @Slot(str)
    def load_media(self, url: str) -> None:
        logger.info("Loading media URL: %s", url)
        self._player.stop()
        if url.startswith("http://") or url.startswith("https://"):
            qurl = QUrl(url)
        else:
            qurl = QUrl.fromLocalFile(url)
        self._player.setSource(qurl)
        self._player.play()

    @Slot()
    def play(self) -> None:
        self._player.play()

    @Slot()
    def pause(self) -> None:
        self._player.pause()

    @Slot(bool)
    def set_pause(self, paused: bool) -> None:
        if paused:
            self._player.pause()
        else:
            self._player.play()

    @Slot(float, bool)
    def seek(self, target_sec: float, relative: bool = False) -> None:
        if relative:
            target_sec = max(0.0, self._position_sec + target_sec)
        else:
            target_sec = max(0.0, target_sec)

        if self._duration_sec > 0:
            target_sec = min(target_sec, self._duration_sec)

        ms = int(target_sec * 1000)
        self._player.setPosition(ms)

    @Slot(float)
    def set_speed(self, speed: float) -> None:
        speed = max(0.25, min(float(speed), 4.0))
        self._player.setPlaybackRate(speed)

    @Slot(int, bool)
    def set_volume_relative(self, delta_percent: int) -> None:
        current = int(self._audio_output.volume() * 100)
        new_vol = max(0, min(100, current + delta_percent))
        self._audio_output.setVolume(new_vol / 100.0)

    @Slot()
    def stop(self) -> None:
        self._player.stop()

    # -- Internal signal handlers --
    def _on_position_changed(self, position_ms: int) -> None:
        self._position_sec = position_ms / 1000.0
        self.position_changed.emit(self._position_sec)

    def _on_duration_changed(self, duration_ms: int) -> None:
        self._duration_sec = max(0.0, duration_ms / 1000.0)
        self.duration_changed.emit(self._duration_sec)

    def _on_playback_rate_changed(self, rate: float) -> None:
        self._speed = rate
        self.speed_changed.emit(rate)

    def _on_buffer_progress_changed(self, progress: float) -> None:
        # progress is 0.0 to 1.0
        self.buffer_progress_changed.emit(progress)

    def _on_playback_state_changed(self, state: QMediaPlayer.PlaybackState) -> None:
        is_paused = (state != QMediaPlayer.PlaybackState.PlayingState)
        if self._is_paused != is_paused:
            self._is_paused = is_paused
            self.paused_changed.emit(is_paused)

    def _on_media_status_changed(self, status: QMediaPlayer.MediaStatus) -> None:
        is_loading = (
            status == QMediaPlayer.MediaStatus.BufferingMedia
            or status == QMediaPlayer.MediaStatus.LoadingMedia
        )
        self.loading_changed.emit(is_loading)

    def _on_error_occurred(self, error: QMediaPlayer.Error, error_string: str) -> None:
        logger.error("Player error (%s): %s", error, error_string)
        self.error_occurred.emit(error_string)
