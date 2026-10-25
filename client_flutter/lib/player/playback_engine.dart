import 'package:flutter/widgets.dart';
import 'package:media_kit_video/media_kit_video.dart';

import '../models/playback_payload.dart';
import 'video_scale.dart';
import 'widgets/video_frame.dart';

export 'video_scale.dart';

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

/// Merge actual touching/overlapping intervals, preserving every real gap.
List<BufferedRange> mergeBufferedRanges(Iterable<BufferedRange> ranges) {
  final sorted = ranges.where((range) => range.start.isFinite && range.end.isFinite &&
      range.end > range.start && range.end > 0).toList()
    ..sort((a, b) => a.start.compareTo(b.start));
  final merged = <BufferedRange>[];
  for (final range in sorted) {
    final start = range.start < 0 ? 0.0 : range.start;
    if (merged.isEmpty || start > merged.last.end) {
      merged.add(BufferedRange(start, range.end));
    } else if (range.end > merged.last.end) {
      merged[merged.length - 1] = BufferedRange(merged.last.start, range.end);
    }
  }
  return merged;
}

abstract class PlaybackEngine extends ChangeNotifier {
  bool get isPiP => false;
  String? get notice => null;

  /// Picture mapping currently applied to the surface.
  VideoScaleMode videoScale = VideoScaleMode.fit;

  /// Natural width / height of the video, or null while it is unknown.
  double? get videoAspect => null;

  /// True when the platform renderer applies [mode] itself, so Flutter must
  /// not size or crop the surface on top of it.
  bool handlesScaleNatively(VideoScaleMode mode) => false;

  /// The raw decoded picture, laid out by [buildVideo].
  Widget buildSurface();

  Widget buildVideo() {
    final surface = buildSurface();
    if (handlesScaleNatively(videoScale)) {
      return SizedBox.expand(child: surface);
    }
    return VideoFrame(mode: videoScale, aspect: videoAspect, child: surface);
  }

  Future<void> setVideoScale(VideoScaleMode mode) async {
    if (videoScale == mode) return;
    videoScale = mode;
    notifyListeners();
  }

  Future<void> enterPiP() async {}
  Future<void> setBrightness(double value) async {}
  double? get brightness => null;
  Future<void> setBrightnessLevel(double level) => setBrightness(level - (brightness ?? 50) / 100);

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
