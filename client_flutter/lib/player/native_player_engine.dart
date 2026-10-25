import 'dart:async';
import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:media_kit_video/media_kit_video.dart';

import '../models/playback_payload.dart';
import 'playback_engine.dart';

/// Native video surfaces use the same Flutter controls and progress reporter.
class NativePlayerEngine extends PlaybackEngine {
  static int _nextSession = 0;
  final String sessionId = '${DateTime.now().microsecondsSinceEpoch}-${_nextSession++}';
  static const channel = MethodChannel('strmaction/player');
  static const events = EventChannel('strmaction/player/events');
  late final StreamSubscription<dynamic> _subscription;
  Map<String, dynamic> _state = {};
  bool _disposed = false;
  String? _error;
  double _previousVolume = 100;
  List<BufferedRange> _bufferedRanges = const [];
  /// Seek target held until the native player reports that it arrived.
  /// AVPlayer and ExoPlayer both keep publishing the old position for a few
  /// frames after a seek; forwarding that makes the bar snap backwards.
  double? _seekTarget;
  DateTime? _seekTargetAt;
  static const Duration _seekSettleTimeout = Duration(seconds: 20);
  late final Widget _surface = Platform.isAndroid
      ? const AndroidView(viewType: 'strmaction/video')
      : UiKitView(viewType: 'strmaction/video', creationParams: {'session_id': sessionId},
          creationParamsCodec: const StandardMessageCodec());

  NativePlayerEngine({Stream<dynamic>? stateEvents}) {
    _subscription = (stateEvents ?? events.receiveBroadcastStream()).listen((event) {
      if (_disposed || event is! Map) return;
      if (event['session_id'] != null && event['session_id'] != sessionId) return;
      _state = Map<String, dynamic>.from(event);
      final target = _seekTarget;
      if (target != null) {
        final actual = _number('position_ms') / 1000;
        final settled = (actual - target).abs() <= 0.8;
        final expired = _seekTargetAt == null ||
            DateTime.now().difference(_seekTargetAt!) > _seekSettleTimeout;
        if (settled || expired || _state['completed'] == true) {
          _seekTarget = null;
          _seekTargetAt = null;
        }
      }
      final actualPosition = _number('position_ms') / 1000;
      _bufferedRanges = mergeBufferedRanges([
        if (_number('buffered_ms') > _number('position_ms'))
          BufferedRange(actualPosition, _number('buffered_ms') / 1000),
        ...((_state['cached_ranges'] as List?) ?? []).whereType<Map>().map((r) =>
          BufferedRange((r['start_ms'] as num).toDouble() / 1000, (r['end_ms'] as num).toDouble() / 1000)),
      ]);
      _error = _state['error'] as String?;
      notifyListeners();
    }, onError: (Object error) {
      _error = '$error';
      if (!_disposed) notifyListeners();
    });
  }

  double _number(String key, [double fallback = 0]) => (_state[key] as num?)?.toDouble() ?? fallback;
  List<TrackInfo> _tracks(String key, String type) => ((_state[key] as List?) ?? []).whereType<Map>().map((t) => TrackInfo(
    id: '${t['id']}', type: type, title: '${t['title'] ?? t['id']}', external: t['external'] == true,
  )).toList();
  @override bool get isPiP => _state['pip'] == true;
  @override String? get notice => _state['notice'] as String?;
  @override VideoController? get videoController => null;

  /// Reported by the native player once the video track is parsed.
  @override double? get videoAspect {
    final width = _number('video_width');
    final height = _number('video_height');
    if (width <= 0 || height <= 0) return null;
    return width / height;
  }

  /// ExoPlayer owns resize modes and KSPlayer owns aspect-fill, so those modes
  /// must not be double-applied by sizing the platform view in Flutter.
  @override bool handlesScaleNatively(VideoScaleMode mode) {
    if (Platform.isIOS) return mode == VideoScaleMode.crop;
    if (Platform.isAndroid) {
      return mode == VideoScaleMode.crop || mode == VideoScaleMode.stretch;
    }
    return false;
  }

  @override Future<void> setVideoScale(VideoScaleMode mode) async {
    final changed = videoScale != mode;
    videoScale = mode;
    if (changed) notifyListeners();
    await _pushScaleToNative();
  }

  /// Re-apply the current mode after a load: a new session rebuilds the
  /// platform view and forgets whatever the previous one was told.
  Future<void> _pushScaleToNative() async {
    if (Platform.isIOS) {
      try {
        await _call('aspectFill', videoScale == VideoScaleMode.crop);
      } on Object catch (error) {
        debugPrint('画面比例设置失败（iOS）：$error');
      }
      return;
    }
    if (!Platform.isAndroid) return;
    try {
      await _call('scale', videoScale.id);
    } on Object catch (error) {
      debugPrint('画面比例设置失败（Android）：$error');
    }
  }

  @override double get position => _seekTarget ?? _number('position_ms') / 1000;
  @override double get duration => _number('duration_ms') / 1000;
  @override bool get isPaused => _state['playing'] != true;
  @override double get speed => _number('speed', 1);
  @override double get volume => _number('volume', 100);
  @override double? get brightness => (_state['brightness'] as num?)?.toDouble();
  @override bool get isLoading => _state['loading'] == true;
  @override bool get isBuffering => _state['buffering'] == true;
  @override bool get completed => _state['completed'] == true;
  @override String? get errorMessage => _error;
  @override double? get networkSpeed => (_state['network_speed'] as num?)?.toDouble();
  @override List<BufferedRange> get bufferedRanges => _bufferedRanges;
  @override List<TrackInfo> get audioTracks => _tracks('audio_tracks', 'audio');
  @override List<TrackInfo> get subtitleTracks => _tracks('subtitle_tracks', 'sub');
  @override String? get currentAudioId => _state['audio_id'] as String?;
  @override String? get currentSubtitleId => _state['subtitle_id'] as String?;

  Future<void> _call(String method, [dynamic arguments]) async {
    await channel.invokeMethod<void>(method, arguments);
  }

  @override Future<void> load(PlaybackPayload payload, {required int cacheLimitMb, required bool tlsVerify}) async {
    _state = {'loading': true};
    _bufferedRanges = const [];
    _seekTarget = null;
    _seekTargetAt = null;
    _error = null;
    notifyListeners();
    try {
      await _call('load', {...payload.toNativeJson(), 'session_id': sessionId, 'buffer_limit_mb': cacheLimitMb, 'disk_cache_limit_mb': payload.diskCacheLimitMb ?? 2048});
      await _pushScaleToNative();
    } on Object catch (error) {
      if (_disposed) return;
      _state = {};
      _error = '$error';
      notifyListeners();
    }
  }
  @override Future<void> applySettings({required int cacheLimitMb, required bool tlsVerify}) => _call('settings', {'buffer_limit_mb': cacheLimitMb});
  @override Future<void> play() => _call('play');
  @override Future<void> pause() => _call('pause');
  @override Future<void> setPaused(bool paused) => paused ? pause() : play();
  @override Future<void> seek(double seconds, {bool relative = false}) {
    var target = relative ? position + seconds : seconds;
    if (target < 0) target = 0;
    final total = duration;
    if (total > 0 && target > total) target = total;
    _seekTarget = target;
    _seekTargetAt = DateTime.now();
    notifyListeners();
    return _call('seek', (target * 1000).round());
  }
  @override Future<void> setSpeed(double speed) => _call('speed', speed);
  @override Future<void> setVolume(int percent) {
    _state['volume'] = percent.clamp(0, 100);
    return _call('volume', percent.clamp(0, 100));
  }
  @override Future<void> setVolumeRelative(int deltaPercent) => setVolume(volume.round() + deltaPercent);
  @override Future<void> toggleMute() {
    if (volume > 0) { _previousVolume = volume; return setVolume(0); }
    return setVolume(_previousVolume.round());
  }
  @override Future<void> setAudioTrack(String? id) => _call('audio', id);
  @override Future<void> setSubtitleTrack(String? id) => _call('subtitle', id);
  @override Future<void> cycleAudio() => _cycle(audioTracks, currentAudioId, setAudioTrack);
  @override Future<void> cycleSubtitle() => _cycle(subtitleTracks, currentSubtitleId, setSubtitleTrack);
  Future<void> _cycle(List<TrackInfo> tracks, String? current, Future<void> Function(String?) select) async {
    if (tracks.isEmpty) return;
    final index = tracks.indexWhere((t) => t.id == current);
    await select(tracks[(index + 1) % tracks.length].id);
  }
  @override Future<void> enterPiP() => _call('pip');
  @override Future<void> setBrightness(double value) => _call('brightness', value);
  @override Future<void> setBrightnessLevel(double level) {
    _state['brightness'] = level.clamp(0.02, 1) * 100;
    return _call('brightnessLevel', level.clamp(0.02, 1));
  }
  @override Future<void> stop() => pause();
  @override Future<void> shutdown() async {
    if (_disposed) return;
    _disposed = true;
    await _subscription.cancel();
    await _call('dispose', {'session_id': sessionId});
  }

  @override Widget buildSurface() => Stack(fit: StackFit.expand, children: [
    _surface,
    if (_state['subtitle_text'] is String && (_state['subtitle_text'] as String).isNotEmpty)
      Positioned(left: 20, right: 20, bottom: 100, child: IgnorePointer(child: Text(
        _state['subtitle_text'] as String, textAlign: TextAlign.center,
        style: const TextStyle(color: Colors.white, fontSize: 18, backgroundColor: Colors.black54),
      ))),
  ]);
}
