import 'package:flutter/widgets.dart';
import 'package:media_kit_video/media_kit_video.dart';

import '../models/playback_payload.dart';

class TrackInfo {
  final String id;
  final String type; // audio | sub
  final String title;
  final bool external;

  const TrackInfo({
    required this.id,
    required this.type,
    required this.title,
    required this.external,
  });
}

class BufferedRange {
  final double start;
  final double end;

  const BufferedRange(this.start, this.end);

  @override
  bool operator ==(Object other) =>
      identical(this, other) ||
      other is BufferedRange &&
          runtimeType == other.runtimeType &&
          (start - other.start).abs() < 0.1 &&
          (end - other.end).abs() < 0.1;

  @override
  int get hashCode => Object.hash((start * 10).round(), (end * 10).round());
}

bool areBufferedRangesEqual(List<BufferedRange> a, List<BufferedRange> b) {
  if (identical(a, b)) return true;
  if (a.length != b.length) return false;
  for (var i = 0; i < a.length; i++) {
    if (a[i] != b[i]) return false;
  }
  return true;
}

abstract class PlaybackEngine extends ChangeNotifier {
  bool get isPiP => false;
  String? get notice => null;
  Widget buildVideo() {
    final controller = videoController;
    return controller == null ? const SizedBox.expand() : Video(
      controller: controller, fit: BoxFit.contain,
      controls: null, wakelock: true,
    );
  }

  Future<void> enterPiP() async {}
  Future<void> setBrightness(double value) async {}

  VideoController? get videoController;

  double get position;
  double get duration;
  bool get isPaused;
  double get speed;
  double get volume;
  bool get isLoading;
  bool get isBuffering;
  bool get completed;
  String? get errorMessage;
  double? get networkSpeed;
  String? get networkStatus {
    if ((networkSpeed ?? 0) > 0) return null;
    if (isLoading || isBuffering) return '等待数据';
    if (bufferedRanges.any((range) => range.start <= position && range.end > position + 1)) return '读取缓存';
    return null;
  }
  List<BufferedRange> get bufferedRanges;
  List<TrackInfo> get audioTracks;
  List<TrackInfo> get subtitleTracks;
  String? get currentAudioId;
  String? get currentSubtitleId;

  Future<void> load(
    PlaybackPayload payload, {
    required int cacheLimitMb,
    required bool tlsVerify,
  });

  Future<void> applySettings({
    required int cacheLimitMb,
    required bool tlsVerify,
  });

  Future<void> play();
  Future<void> pause();
  Future<void> setPaused(bool paused);
  Future<void> seek(double seconds, {bool relative = false});
  Future<void> setSpeed(double speed);
  Future<void> setVolume(int percent);
  Future<void> setVolumeRelative(int deltaPercent);
  Future<void> toggleMute();
  Future<void> setAudioTrack(String? id);
  Future<void> setSubtitleTrack(String? id);
  Future<void> cycleAudio();
  Future<void> cycleSubtitle();
  Future<void> stop();
  Future<void> shutdown();
}
