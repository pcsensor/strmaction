import 'package:flutter/foundation.dart';
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
}

abstract class PlaybackEngine extends ChangeNotifier {
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
