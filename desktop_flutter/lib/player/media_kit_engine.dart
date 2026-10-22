import 'dart:async';
import 'dart:convert';
import 'dart:math' as math;

import 'package:media_kit/media_kit.dart';
import 'package:media_kit_video/media_kit_video.dart';

import '../core/app_logger.dart';
import '../models/playback_payload.dart';
import 'playback_engine.dart';

class MediaKitEngine extends PlaybackEngine {
  final AppLogger? logger;
  late final Player _player;
  late final VideoController _videoController;
  final List<StreamSubscription<dynamic>> _subscriptions = [];
  Timer? _cacheTimer;

  double _position = 0;
  double _duration = 0;
  bool _paused = true;
  double _speed = 1;
  double _volume = 100;
  bool _muted = false;
  double _volumeBeforeMute = 100;
  bool _loading = false;
  bool _buffering = false;
  bool _completed = false;
  String? _error;
  double? _networkSpeed;
  List<BufferedRange> _bufferedRanges = const [];
  double _bufferPosition = 0;
  List<TrackInfo> _audioTracks = const [];
  List<TrackInfo> _subtitleTracks = const [];
  String? _currentAudioId;
  String? _currentSubtitleId;
  Tracks? _tracks;
  Track? _track;
  bool _disposed = false;

  MediaKitEngine({this.logger}) {
    _player = Player();
    _videoController = VideoController(
      _player,
      configuration: const VideoControllerConfiguration(
        enableHardwareAcceleration: true,
      ),
    );
    _bindStreams();
  }

  @override
  VideoController? get videoController => _videoController;

  @override
  double get position => _position;

  @override
  double get duration => _duration;

  @override
  bool get isPaused => _paused;

  @override
  double get speed => _speed;

  @override
  double get volume => _volume;

  @override
  bool get isLoading => _loading;

  @override
  bool get isBuffering => _buffering;

  @override
  bool get completed => _completed;

  @override
  String? get errorMessage => _error;

  @override
  double? get networkSpeed => _networkSpeed;

  @override
  List<BufferedRange> get bufferedRanges => _bufferedRanges;

  @override
  List<TrackInfo> get audioTracks => _audioTracks;

  @override
  List<TrackInfo> get subtitleTracks => _subtitleTracks;

  @override
  String? get currentAudioId => _currentAudioId;

  @override
  String? get currentSubtitleId => _currentSubtitleId;

  void _bindStreams() {
    _subscriptions.add(
      _player.stream.playing.listen((playing) {
        _paused = !playing;
        if (playing) _loading = false;
        _notify();
      }),
    );
    _subscriptions.add(
      _player.stream.position.listen((value) {
        _position = value.inMilliseconds / 1000.0;
        _notify();
      }),
    );
    _subscriptions.add(
      _player.stream.duration.listen((value) {
        _duration = value.inMilliseconds / 1000.0;
        _notify();
      }),
    );
    _subscriptions.add(
      _player.stream.buffer.listen((value) {
        _bufferPosition = value.inMilliseconds / 1000.0;
        _refreshBufferFallback();
      }),
    );
    _subscriptions.add(
      _player.stream.rate.listen((value) {
        _speed = value;
        _notify();
      }),
    );
    _subscriptions.add(
      _player.stream.volume.listen((value) {
        _volume = value;
        if (value > 0) _muted = false;
        _notify();
      }),
    );
    _subscriptions.add(
      _player.stream.buffering.listen((value) {
        _buffering = value;
        _notify();
      }),
    );
    _subscriptions.add(
      _player.stream.completed.listen((value) {
        _completed = value;
        if (value) _paused = true;
        _notify();
      }),
    );
    _subscriptions.add(
      _player.stream.error.listen((message) {
        if (message.trim().isEmpty) return;
        _error = _friendlyError(message);
        _loading = false;
        _notify();
      }),
    );
    _subscriptions.add(
      _player.stream.tracks.listen((tracks) {
        _tracks = tracks;
        _syncTracks();
      }),
    );
    _subscriptions.add(
      _player.stream.track.listen((track) {
        _track = track;
        _syncTracks();
      }),
    );
  }

  void _syncTracks() {
    final tracks = _tracks;
    if (tracks == null) return;

    _audioTracks = tracks.audio
        .where((track) => track.id != 'auto' && track.id != 'no')
        .map(
          (track) => TrackInfo(
            id: track.id,
            type: 'audio',
            title: _trackTitle(track, '音轨'),
            external: track.uri,
          ),
        )
        .toList(growable: false);

    _subtitleTracks = tracks.subtitle
        .where((track) => track.id != 'auto' && track.id != 'no')
        .map(
          (track) => TrackInfo(
            id: track.id,
            type: 'sub',
            title: _trackTitle(track, '字幕'),
            external: track.uri,
          ),
        )
        .toList(growable: false);

    final current = _track;
    _currentAudioId = current != null &&
            current.audio.id != 'auto' &&
            current.audio.id != 'no'
        ? current.audio.id
        : null;
    _currentSubtitleId = current != null &&
            current.subtitle.id != 'auto' &&
            current.subtitle.id != 'no'
        ? current.subtitle.id
        : null;
    _notify();
  }

  String _trackTitle(dynamic track, String prefix) {
    final title = (track.title as String?)?.trim();
    if (title != null && title.isNotEmpty) return title;
    final language = (track.language as String?)?.trim();
    if (language != null && language.isNotEmpty) return language;
    final codec = (track.codec as String?)?.trim();
    if (codec != null && codec.isNotEmpty) return codec;
    return '$prefix #${track.id}';
  }

  @override
  Future<void> load(
    PlaybackPayload payload, {
    required int cacheLimitMb,
    required bool tlsVerify,
  }) async {
    _error = null;
    _completed = false;
    _loading = true;
    _position = 0;
    _duration = (payload.durationMs ?? 0) / 1000.0;
    _bufferedRanges = const [];
    _networkSpeed = null;
    _notify();

    await applySettings(cacheLimitMb: cacheLimitMb, tlsVerify: tlsVerify);
    final media = Media(
      payload.playUrl,
      httpHeaders: payload.headers.isEmpty ? null : payload.headers,
      start: payload.resumeMs > 0
          ? Duration(milliseconds: payload.resumeMs)
          : null,
    );
    try {
      await _player.open(media, play: true);
      _loading = false;
      await _addExternalSubtitles(payload.subtitles);
      _startCachePolling();
      _notify();
    } on Object catch (error) {
      _error = _friendlyError('$error');
      _loading = false;
      _notify();
    }
  }

  Future<void> _addExternalSubtitles(List<SubtitleInfo> subtitles) async {
    if (subtitles.isEmpty) return;
    final platform = _player.platform;
    if (platform is! NativePlayer) return;
    for (var index = 0; index < subtitles.length; index++) {
      final subtitle = subtitles[index];
      try {
        await platform.command([
          'sub-add',
          subtitle.url,
          index == 0 ? 'select' : 'auto',
          subtitle.label,
        ]);
      } on Object catch (error) {
        logger?.warning('外挂字幕加载失败：${subtitle.label}: $error');
      }
    }
  }

  @override
  Future<void> applySettings({
    required int cacheLimitMb,
    required bool tlsVerify,
  }) async {
    final platform = _player.platform;
    if (platform is! NativePlayer) return;
    try {
      if (cacheLimitMb <= 0) {
        await platform.setProperty('cache', 'no');
        await platform.setProperty('demuxer-max-bytes', '0');
      } else {
        await platform.setProperty('cache', 'yes');
        await platform.setProperty('demuxer-max-bytes', '${cacheLimitMb}MiB');
        await platform.setProperty(
          'demuxer-max-back-bytes',
          '${math.max(1, cacheLimitMb ~/ 4)}MiB',
        );
      }
      await platform.setProperty('tls-verify', tlsVerify ? 'yes' : 'no');
      await platform.setProperty('hwdec', 'auto-safe');
      await platform.setProperty('keep-open', 'always');
    } on Object catch (error) {
      logger?.debug('player 设置失败：$error');
    }
  }

  void _startCachePolling() {
    _cacheTimer?.cancel();
    _cacheTimer = Timer.periodic(
      const Duration(milliseconds: 500),
      (_) => unawaited(_readCacheState()),
    );
  }

  Future<void> _readCacheState() async {
    final platform = _player.platform;
    if (platform is! NativePlayer) return;
    try {
      final raw = await platform.getProperty('demuxer-cache-state');
      if (raw.trim().isEmpty) return;
      final decoded = jsonDecode(raw);
      if (decoded is! Map) return;

      final ranges = <BufferedRange>[];
      final rawRanges = decoded['seekable-ranges'];
      if (rawRanges is List) {
        for (final entry in rawRanges) {
          if (entry is! Map) continue;
          final start = _asDouble(entry['start']);
          final end = _asDouble(entry['end']);
          if (start == null || end == null || end <= start) continue;
          ranges.add(BufferedRange(math.max(0, start), end));
        }
      }
      final merged = _mergeRanges(ranges);
      if (merged.isNotEmpty) {
        _bufferedRanges = merged;
        _notify();
      } else {
        _refreshBufferFallback();
      }

      final speed = _asDouble(decoded['raw-input-rate']);
      if (speed != null && speed >= 0 && speed != _networkSpeed) {
        _networkSpeed = speed;
        _notify();
      }
    } on Object {
      // The property is unavailable while idle or before the file is loaded.
    }
  }

  void _refreshBufferFallback() {
    if (_bufferedRanges.isNotEmpty) return;
    if (_bufferPosition > _position + 0.1) {
      _bufferedRanges = [BufferedRange(_position, _bufferPosition)];
      _notify();
    }
  }

  List<BufferedRange> _mergeRanges(List<BufferedRange> ranges) {
    if (ranges.isEmpty) return const [];
    final sorted = [...ranges]..sort((a, b) => a.start.compareTo(b.start));
    final merged = <BufferedRange>[];
    for (final range in sorted) {
      final end = _duration > 0 ? math.min(range.end, _duration) : range.end;
      final start = math.max(0.0, range.start);
      if (end <= start) continue;
      if (merged.isEmpty || start > merged.last.end + 0.1) {
        merged.add(BufferedRange(start, end));
      } else if (end > merged.last.end) {
        merged[merged.length - 1] = BufferedRange(merged.last.start, end);
      }
    }
    return merged;
  }

  static double? _asDouble(dynamic value) {
    if (value is num) return value.toDouble();
    if (value is String) return double.tryParse(value);
    return null;
  }

  @override
  Future<void> play() async {
    await _player.play();
  }

  @override
  Future<void> pause() async {
    await _player.pause();
  }

  @override
  Future<void> setPaused(bool paused) async {
    if (paused) {
      await _player.pause();
    } else {
      if (_completed && _duration > 0) {
        _completed = false;
        await _player.seek(Duration.zero);
      }
      await _player.play();
    }
  }

  @override
  Future<void> seek(double seconds, {bool relative = false}) async {
    var target = relative ? _position + seconds : seconds;
    target = math.max(0, target);
    if (_duration > 0) target = math.min(target, _duration);
    await _player.seek(Duration(milliseconds: (target * 1000).round()));
  }

  @override
  Future<void> setSpeed(double speed) async {
    final value = speed.clamp(0.25, 4.0).toDouble();
    await _player.setRate(value);
  }

  @override
  Future<void> setVolume(int percent) async {
    final value = percent.clamp(0, 100).toDouble();
    _muted = value == 0;
    await _player.setVolume(value);
  }

  @override
  Future<void> setVolumeRelative(int deltaPercent) async {
    await setVolume(_volume.round() + deltaPercent);
  }

  @override
  Future<void> toggleMute() async {
    if (_muted || _volume <= 0) {
      _muted = false;
      await _player.setVolume(_volumeBeforeMute.clamp(1, 100).toDouble());
    } else {
      _volumeBeforeMute = _volume;
      _muted = true;
      await _player.setVolume(0);
    }
  }

  @override
  Future<void> setAudioTrack(String? id) async {
    if (id == null || id.isEmpty) {
      await _player.setAudioTrack(AudioTrack.no());
      return;
    }
    AudioTrack? track;
    for (final item in _tracks?.audio ?? const <AudioTrack>[]) {
      if (item.id == id) {
        track = item;
        break;
      }
    }
    if (track != null) await _player.setAudioTrack(track);
  }

  @override
  Future<void> setSubtitleTrack(String? id) async {
    if (id == null || id.isEmpty || id == 'no') {
      await _player.setSubtitleTrack(SubtitleTrack.no());
      return;
    }
    SubtitleTrack? track;
    for (final item in _tracks?.subtitle ?? const <SubtitleTrack>[]) {
      if (item.id == id) {
        track = item;
        break;
      }
    }
    if (track != null) await _player.setSubtitleTrack(track);
  }

  @override
  Future<void> cycleAudio() async {
    if (_audioTracks.length <= 1) return;
    final index = _audioTracks.indexWhere((track) => track.id == _currentAudioId);
    final next = _audioTracks[(index + 1) % _audioTracks.length];
    await setAudioTrack(next.id);
  }

  @override
  Future<void> cycleSubtitle() async {
    if (_subtitleTracks.isEmpty) return;
    final ids = _subtitleTracks.map((track) => track.id).toList();
    final index = ids.indexOf(_currentSubtitleId ?? '');
    final next = index + 1;
    if (next >= ids.length) {
      await setSubtitleTrack(null);
    } else {
      await setSubtitleTrack(ids[next]);
    }
  }

  @override
  Future<void> stop() async {
    _cacheTimer?.cancel();
    _cacheTimer = null;
    _bufferedRanges = const [];
    _networkSpeed = null;
    _position = 0;
    _duration = 0;
    _completed = false;
    _loading = false;
    _notify();
    try {
      await _player.stop();
    } on Object {
      // Stopping is best-effort.
    }
  }

  String _friendlyError(String raw) {
    final text = raw.trim();
    final lowered = text.toLowerCase();
    if (lowered.contains('failed to open') ||
        lowered.contains('loading failed') ||
        lowered.contains('403') ||
        lowered.contains('404')) {
      return '无法打开片源（链接可能已过期、被防盗链拒绝，或证书校验未通过）';
    }
    if (lowered.contains('unsupported') || lowered.contains('unknown format')) {
      return '无法播放该媒体（格式不受支持或片源已损坏）';
    }
    if (lowered.contains('audio') && lowered.contains('init')) {
      return '音频设备初始化失败，请检查系统音频输出';
    }
    if (lowered.contains('video') && lowered.contains('init')) {
      return '视频输出初始化失败，请更新显卡驱动';
    }
    return text.isEmpty ? '播放失败，请查看日志或稍后重试' : text;
  }

  @override
  Future<void> shutdown() async {
    if (_disposed) return;
    _disposed = true;
    _cacheTimer?.cancel();
    _cacheTimer = null;
    for (final subscription in _subscriptions) {
      await subscription.cancel();
    }
    _subscriptions.clear();
    try {
      await _player.dispose();
    } on Object {
      // Best effort.
    }
  }

  void _notify() {
    if (_disposed) return;
    notifyListeners();
  }
}
