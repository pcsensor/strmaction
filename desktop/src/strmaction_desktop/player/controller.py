"""In-process media player controller wrapping PySide6 QtMultimedia.

Uses a native QMediaPlayer + QAudioOutput.
Codec support comes from Qt's FFmpeg backend, so no external binary ships with
the app.
"""

from __future__ import annotations

import logging

from PySide6.QtCore import QObject, QUrl, Signal, Slot
from PySide6.QtMultimedia import QAudioOutput, QMediaMetaData, QMediaPlayer

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
    playback_finished = Signal()           # end of media reached
    tracks_changed = Signal(list)          # [{"type": "audio"|"sub", ...}]

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)

        self._player = QMediaPlayer(self)
        self._audio_output = QAudioOutput(self)
        self._player.setAudioOutput(self._audio_output)

        self._duration_sec: float = 0.0
        self._position_sec: float = 0.0
        self._is_paused: bool = False
        self._speed: float = 1.0
        self._pending_seek_ms: int | None = None
        self._finished_emitted = False

        # Wire QMediaPlayer signals
        self._player.positionChanged.connect(self._on_position_changed)
        self._player.durationChanged.connect(self._on_duration_changed)
        self._player.playbackRateChanged.connect(self._on_playback_rate_changed)
        self._player.bufferProgressChanged.connect(self._on_buffer_progress_changed)
        self._player.playbackStateChanged.connect(self._on_playback_state_changed)
        self._player.mediaStatusChanged.connect(self._on_media_status_changed)
        self._player.errorOccurred.connect(self._on_error_occurred)
        self._player.tracksChanged.connect(self._emit_tracks)

    # -- output ---------------------------------------------------------
    def set_video_output(self, video_widget) -> None:
        self._player.setVideoOutput(video_widget)

    @property
    def duration(self) -> float:
        return self._duration_sec

    @property
    def position(self) -> float:
        return self._position_sec

    # -- loading --------------------------------------------------------
    @Slot(str, int)
    def load_media(self, url: str, start_ms: int = 0) -> None:
        """Start playback of ``url``, resuming at ``start_ms`` once it is loaded."""
        logger.info("Loading media URL: %s", url)
        self._player.stop()
        self._finished_emitted = False
        self._duration_sec = 0.0
        self._position_sec = 0.0
        # QMediaPlayer drops setPosition() before the media is loaded, so the
        # resume offset is applied on LoadedMedia instead.
        self._pending_seek_ms = int(start_ms) if start_ms and start_ms > 1000 else None
        if "://" in url:
            # Covers http(s):// and file:// (a bare path has no scheme).
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
            if self._finished_emitted and self._duration_sec > 0:
                # Replay from the start after the media finished.
                self._finished_emitted = False
                self._player.setPosition(0)
            self._player.play()

    @Slot(float, bool)
    def seek(self, target_sec: float, relative: bool = False) -> None:
        if relative:
            target_sec = max(0.0, self._position_sec + target_sec)
        else:
            target_sec = max(0.0, target_sec)

        # Only clamp when the duration is actually known, otherwise a resume
        # seek issued right after load_media() would be clamped to 0.
        if self._duration_sec > 0:
            target_sec = min(target_sec, self._duration_sec)

        ms = int(target_sec * 1000)
        if self._duration_sec <= 0:
            self._pending_seek_ms = ms
        self._player.setPosition(ms)

    @Slot(float)
    def set_speed(self, speed: float) -> None:
        speed = max(0.25, min(float(speed), 4.0))
        self._player.setPlaybackRate(speed)

    @Slot(int)
    def set_volume(self, volume_percent: int) -> None:
        self._audio_output.setVolume(max(0, min(int(volume_percent), 100)) / 100.0)

    @Slot(int, bool)
    def set_volume_relative(self, delta_percent: int) -> None:
        current = int(round(self._audio_output.volume() * 100))
        self.set_volume(current + delta_percent)

    def volume(self) -> int:
        return int(round(self._audio_output.volume() * 100))

    @Slot()
    def stop(self) -> None:
        self._pending_seek_ms = None
        self._finished_emitted = False
        self._player.stop()
        self._player.setSource(QUrl())

    # -- tracks ---------------------------------------------------------
    def tracks(self) -> list[dict]:
        """Audio and subtitle tracks reported by the container."""
        result: list[dict] = []
        active_audio = self._player.activeAudioTrack()
        active_sub = self._player.activeSubtitleTrack()
        for index, meta in enumerate(self._player.audioTracks()):
            result.append(
                {
                    "type": "audio",
                    "id": index,
                    "title": _track_label(meta, f"音轨 {index + 1}"),
                    "selected": index == active_audio,
                }
            )
        for index, meta in enumerate(self._player.subtitleTracks()):
            result.append(
                {
                    "type": "sub",
                    "id": index,
                    "title": _track_label(meta, f"字幕 {index + 1}"),
                    "selected": index == active_sub,
                }
            )
        return result

    @Slot(int)
    def set_audio_track(self, index: int) -> None:
        self._player.setActiveAudioTrack(int(index))

    @Slot(int)
    def set_subtitle_track(self, index: int) -> None:
        self._player.setActiveSubtitleTrack(int(index))

    @Slot()
    def cycle_audio(self) -> None:
        count = len(self._player.audioTracks())
        if count <= 1:
            return
        current = self._player.activeAudioTrack()
        self._player.setActiveAudioTrack((current + 1) % count)

    @Slot()
    def cycle_subtitle(self) -> None:
        # -1 (subtitles off) is part of the cycle.
        count = len(self._player.subtitleTracks())
        if count == 0:
            return
        current = self._player.activeSubtitleTrack()
        self._player.setActiveSubtitleTrack(-1 if current + 1 >= count else current + 1)

    # -- internal signal handlers ---------------------------------------
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
        self.buffer_progress_changed.emit(progress)

    def _on_playback_state_changed(self, state: QMediaPlayer.PlaybackState) -> None:
        is_paused = state != QMediaPlayer.PlaybackState.PlayingState
        if self._is_paused != is_paused:
            self._is_paused = is_paused
            self.paused_changed.emit(is_paused)

    def _on_media_status_changed(self, status: QMediaPlayer.MediaStatus) -> None:
        if status == QMediaPlayer.MediaStatus.LoadedMedia:
            self._apply_pending_seek()
        is_loading = status in (
            QMediaPlayer.MediaStatus.BufferingMedia,
            QMediaPlayer.MediaStatus.LoadingMedia,
            QMediaPlayer.MediaStatus.StalledMedia,
        )
        self.loading_changed.emit(is_loading)
        if status == QMediaPlayer.MediaStatus.EndOfMedia and not self._finished_emitted:
            self._finished_emitted = True
            self.playback_finished.emit()
        elif status == QMediaPlayer.MediaStatus.InvalidMedia:
            # errorOccurred usually fires first; this is a safety net so the UI
            # never stays on a silent black screen.
            self.error_occurred.emit("无法播放该媒体（格式或片源不可用）")

    def _apply_pending_seek(self) -> None:
        if self._pending_seek_ms is None:
            return
        target = self._pending_seek_ms
        self._pending_seek_ms = None
        if target > 0:
            self._player.setPosition(target)

    def _emit_tracks(self) -> None:
        self.tracks_changed.emit(self.tracks())

    def _on_error_occurred(self, error: QMediaPlayer.Error, error_string: str) -> None:
        if error == QMediaPlayer.Error.NoError:
            return
        message = error_string.strip()
        logger.error("Player error (%s): %s", error, message)
        if error == QMediaPlayer.Error.ResourceError:
            message = message or "片源无法打开（可能是证书、防盗链或网络问题）"
        elif error == QMediaPlayer.Error.FormatError:
            message = message or "片源格式不受支持"
        self.error_occurred.emit(message or "播放失败")


def _track_label(meta: QMediaMetaData, fallback: str) -> str:
    for key in (QMediaMetaData.Key.Title, QMediaMetaData.Key.Language,
                QMediaMetaData.Key.AudioCodec):
        value = meta.stringValue(key)
        if value:
            return str(value)
    return fallback
