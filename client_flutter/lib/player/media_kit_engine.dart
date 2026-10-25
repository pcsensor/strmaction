import 'dart:async';
import 'dart:convert';
import 'dart:math' as math;
import 'dart:io';

import 'package:flutter/widgets.dart';
import 'package:media_kit/media_kit.dart';
import 'package:media_kit_video/media_kit_video.dart';

import '../core/app_logger.dart';
import '../core/redaction.dart';
import '../models/playback_payload.dart';
import '../services/download_policy.dart';
import '../services/sequential_media_cache.dart';
import 'playback_engine.dart';

class MediaKitEngine extends PlaybackEngine {
  final AppLogger? logger;
  late final Player _player;
  late final VideoController _videoController;
  final List<StreamSubscription<dynamic>> _subscriptions = [];
  Timer? _cacheTimer;
  Timer? _networkTimer;
  bool _readingCache = false;
  int _cacheEpoch = 0;
  NetworkRate _fallbackRate = NetworkRate();
  final Stopwatch _pollClock = Stopwatch()..start();
  Duration _lastRateSample = Duration.zero;
  Duration _lastTransportLog = Duration.zero;

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

  /// The seek target shown while the decoder is still catching up. MPV reports
  /// the pre-seek position until the target is demuxed; accepting it would make
  /// every seek flash backwards before jumping to the requested time.
  double? _seekTarget;
  DateTime? _seekTargetAt;
  static const Duration _seekSettleTimeout = Duration(seconds: 20);

  SequentialMediaCache? _diskCache;
  final String trustedCaPem;
  final String? caBundlePath;
  final String? cacheDirectory;
  final int diskLimitMb;
  MediaKitEngine({this.logger, this.hardwareAcceleration = false, this.caBundlePath, this.cacheDirectory, this.diskLimitMb = 2048, this.trustedCaPem = ''}) {
    _player = Player();
    // The GPU (ANGLE/DXGI shared-handle) output registers and swaps external
    // textures from media_kit's worker thread while the Flutter raster thread
    // composites them. On some GPU/driver combinations that races the engine
    // and crashes the process inside GrDirectContext::flush, so we only use it
    // when explicitly enabled.
    _videoController = VideoController(
      _player,
      configuration: VideoControllerConfiguration(
        enableHardwareAcceleration: hardwareAcceleration,
      ),
    );
    logger?.info(
      '播放器渲染模式：${hardwareAcceleration ? '硬件加速（ANGLE/DXGI）' : '软件渲染'}',
    );
    _bindStreams();
  }

  final bool hardwareAcceleration;

  @override
  VideoController? get videoController => _videoController;

  /// MPV reports the display size of the decoded frame (rotation applied).
  @override
  double? get videoAspect {
    final width = _player.state.width;
    final height = _player.state.height;
    if (width == null || height == null || width <= 0 || height <= 0) return null;
    return width / height;
  }

  @override
  Widget buildSurface() => Video(
        controller: _videoController,
        fit: BoxFit.contain,
        controls: null,
        wakelock: true,
      );

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
  String? get networkStatus => (_networkSpeed ?? 0) == 0 &&
      !_loading && !_buffering && _diskCache?.cacheReady == true
      ? '缓存充足' : super.networkStatus;

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
        final seconds = value.inMilliseconds / 1000.0;
        final target = _seekTarget;
        if (target != null) {
          final settled = (seconds - target).abs() <= 0.8;
          final expired = _seekTargetAt == null ||
              DateTime.now().difference(_seekTargetAt!) > _seekSettleTimeout;
          if (!settled && !expired) {
            // MPV keeps reporting the old position until the target is
            // decoded. Publishing it makes the bar jump backwards for a frame.
            return;
          }
          _seekTarget = null;
          _seekTargetAt = null;
        }
        _position = seconds;
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
        _updateDownloadPriority();
        _notify();
      }),
    );
    _subscriptions.add(
      _player.stream.completed.listen((value) {
        _completed = value;
        if (value) {
          _paused = true;
          // A seek to the very end lands short of the duration; do not hold the
          // target for the whole settle window once playback has completed.
          _seekTarget = null;
          _seekTargetAt = null;
        }
        _notify();
      }),
    );
    _subscriptions.add(
      _player.stream.error.listen((message) {
        if (message.trim().isEmpty) return;
        logger?.warning('播放器错误：${_redacted(message)}');
        _error = _friendlyError(message);
        _loading = false;
        _seekTarget = null;
        _seekTargetAt = null;
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
    final epoch = ++_cacheEpoch;
    _fallbackRate = NetworkRate();
    _lastRateSample = _pollClock.elapsed;
    _error = null;
    _completed = false;
    _loading = true;
    _position = 0;
    _seekTarget = null;
    _seekTargetAt = null;
    _duration = (payload.durationMs ?? 0) / 1000.0;
    _bufferedRanges = const [];
    _networkSpeed = null;
    _notify();

    await applySettings(cacheLimitMb: cacheLimitMb, tlsVerify: tlsVerify);
    if (_disposed || epoch != _cacheEpoch) return;
    try {
    final previous = _diskCache;
    _diskCache = null;
    await previous?.close();
    if (_disposed || epoch != _cacheEpoch) return;
    if (cacheDirectory != null && diskLimitMb > 0) {
      SequentialMediaCache? opened;
      try {
        opened = await SequentialMediaCache.open(url: payload.playUrl, headers: payload.headers,
          trustedCaPem: trustedCaPem, directory: '$cacheDirectory/$epoch', budgetBytes: diskLimitMb * 1024 * 1024,
          prefetchBytes: cacheLimitMb * 1024 * 1024, onDiagnostic: logger?.info);
      } on Object catch (error) {
        // A cache that cannot resolve the origin must not abort playback:
        // media_kit can still open the origin directly with the same headers.
        logger?.warning('本地缓存初始化失败，回退直连：${error.runtimeType}: ${_redacted('$error')}');
      }
      if (_disposed || epoch != _cacheEpoch) {
        await opened?.close();
        // A delayed opener may finish after shutdown removed the parent.
        // Non-recursive removal cannot delete a newer playback's cache.
        try { await Directory(cacheDirectory!).delete(); } on FileSystemException { /* another load owns it */ }
        return;
      }
      _diskCache = opened;
      if (opened != null) {
        logger?.info('本地缓存就绪 origin=${redactUrl(payload.playUrl)} '
            'length=${(opened.length / 1024 / 1024).toStringAsFixed(1)}MB');
        opened.setConsumed(_duration > 0 ? (opened.length * payload.resumeMs / 1000 / _duration).round() : 0);
      }
    }
    if (_diskCache == null) {
      logger?.info('播放直连 origin=${redactUrl(payload.playUrl)} '
          '磁盘上限=${diskLimitMb}MB 预读=${cacheLimitMb}MB');
    }
    final media = Media(
      _diskCache?.localUrl.toString() ?? payload.playUrl,
      // The cache owns origin headers. Passing them to the loopback decoder
      // can override its own Range/Host and applies media credentials locally.
      httpHeaders: _diskCache != null ? const <String, String>{} : payload.headers,
      start: payload.resumeMs > 0
          ? Duration(milliseconds: payload.resumeMs)
          : null,
    );
      await _player.open(media, play: true);
      if (_disposed || epoch != _cacheEpoch) return;
      _loading = false;
      await _addExternalSubtitles(payload.subtitles);
      if (_disposed || epoch != _cacheEpoch) return;
      _startCachePolling();
      _notify();
    } on Object catch (error) {
      if (_disposed || epoch != _cacheEpoch) return;
      logger?.warning('打开媒体失败：${error.runtimeType}: ${_redacted('$error')}');
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
    _diskCache?.prefetchBytes = cacheLimitMb * 1024 * 1024;
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
      await platform.setProperty('tls-verify', 'yes');
      if (caBundlePath != null) await platform.setProperty('tls-ca-file', caBundlePath!);
      // The sequential cache may need one full connect timeout (25s) before
      // the first byte reaches the decoder. Keep the local read alive long
      // enough for that single attempt instead of failing it at five seconds.
      await platform.setProperty('network-timeout', '30');
      await platform.setProperty('cache-on-disk', 'no');
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
    _networkTimer?.cancel();
    _networkTimer = Timer.periodic(const Duration(milliseconds: 500), (_) {
      // Independent of MPV property latency and loopback/disk read throughput.
      final disk = _diskCache;
      _updateDownloadPriority();
      if (disk != null && _duration > 0) disk.setConsumed((disk.length * _position / _duration).round());
      _networkSpeed = _diskCache?.networkSpeed ?? _fallbackRate.bytesPerSecond;
      final now = _pollClock.elapsed;
      if (disk != null && disk.activeDownloads > 0 && (_networkSpeed ?? 0) == 0 &&
          now - _lastTransportLog >= const Duration(seconds: 5)) {
        _lastTransportLog = now;
        logger?.warning('桌面媒体无上游数据 position=$_position paused=$_paused '
            'buffering=$_buffering ${disk.diagnosticState}');
      }
      _notify();
    });
  }

  void _updateDownloadPriority() {
    _diskCache?.setPlaybackUrgent(_buffering || _loading || _bufferPosition - _position < 10);
  }

  Future<void> _readCacheState() async {
    if (_readingCache || _disposed) return;
    final platform = _player.platform;
    if (platform is! NativePlayer) return;
    _readingCache = true;
    final epoch = _cacheEpoch;
    try {
      final raw = await platform.getProperty('demuxer-cache-state').timeout(const Duration(seconds: 2));
      if (_disposed || epoch != _cacheEpoch) return;
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
        if (!areBufferedRangesEqual(_bufferedRanges, merged)) {
          _bufferedRanges = merged;
          _notify();
        }
      } else {
        _refreshBufferFallback();
      }

      final disk = _diskCache;
      if (disk != null && _duration > 0) {
        final diskRanges = disk.ranges.map((r) => BufferedRange(r.$1 / disk.length * _duration, r.$2 / disk.length * _duration));
        _bufferedRanges = _mergeRanges([...merged, ...diskRanges]);
      }
      if (disk == null) {
        final speed = _asDouble(decoded['raw-input-rate']);
        final now = _pollClock.elapsed;
        if (speed != null && speed >= 0) {
          _fallbackRate.add((speed * (now - _lastRateSample).inMicroseconds / 1000000).round());
        }
        _lastRateSample = now;
      }
    } on Object {
      // The property is unavailable while idle or before the file is loaded.
    } finally { _readingCache = false; }
  }

  void _refreshBufferFallback() {
    if (_bufferedRanges.isNotEmpty) return;
    if (_bufferPosition > _position + 0.1) {
      final fallback = [BufferedRange(_position, _bufferPosition)];
      if (!areBufferedRangesEqual(_bufferedRanges, fallback)) {
        _bufferedRanges = fallback;
        _notify();
      }
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
    // Publish the requested position immediately. The UI, the prefetch window
    // and the progress reporter should all follow the seek, not wait for MPV
    // to finish demuxing at the new offset.
    _seekTarget = target;
    _seekTargetAt = DateTime.now();
    _position = target;
    _notify();
    if (_duration > 0 && _diskCache != null) {
      final byte = (_diskCache!.length * target / _duration).round();
      logger?.info('桌面 seek target=${target.toStringAsFixed(1)}s '
          'offset=$byte cached=${_diskCache!.covers(byte)}');
      _diskCache!.seek(byte);
    }
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
    _cacheEpoch++;
    final cache = _diskCache;
    _diskCache = null;
    _networkTimer?.cancel();
    _cacheTimer?.cancel();
    _cacheTimer = null;
    _bufferedRanges = const [];
    _seekTarget = null;
    _seekTargetAt = null;
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
    } finally {
      await cache?.close();
    }
  }

  /// Keeps tokens and signed query strings out of the desktop log.
  static String _redacted(String raw) => raw.replaceAllMapped(
        RegExp(r'https?://[^\s"<>]+'),
        (match) => redactUrl(match[0]),
      );

  String _friendlyError(String raw) {
    final text = raw.trim();
    final lowered = text.toLowerCase();
    if (lowered.contains('502') ||
        lowered.contains('503') ||
        lowered.contains('504') ||
        lowered.contains('timed out') ||
        lowered.contains('timeout')) {
      return '片源拉取超时，请检查网络或稍后重试';
    }
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
    _cacheEpoch++;
    _networkTimer?.cancel();
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
    await _diskCache?.close();
    _diskCache = null;
    if (cacheDirectory != null) {
      final directory = Directory(cacheDirectory!);
      try { if (await directory.exists()) await directory.delete(recursive: true); }
      on Object catch (error) { logger?.warning('清理播放缓存失败：$error'); }
    }
  }

  void _notify() {
    if (_disposed) return;
    notifyListeners();
  }
}
