import 'dart:async';

import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:strmaction_desktop/models/playback_payload.dart';
import 'package:strmaction_desktop/player/native_player_engine.dart';
import 'package:strmaction_desktop/player/playback_engine.dart';

const payload = PlaybackPayload(itemId: 1, playUrl: 'https://media.invalid/video.mp4',
  headers: {}, playToken: 'test', resumeMs: 0, progressIntervalMs: 60000,
  subtitles: [], title: 'Video', seriesTitle: '', playlist: [], nextItemId: null,
  nextTitle: '', currentIndex: 0, durationMs: 100000);

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  test('native cache fragments are merged once per event and preserve gaps on both mobile bridges', () async {
    final messenger = TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger;
    final calls = <MethodCall>[];
    messenger.setMockMethodCallHandler(NativePlayerEngine.channel, (call) async { calls.add(call); return null; });
    addTearDown(() => messenger.setMockMethodCallHandler(NativePlayerEngine.channel, null));
    final states = StreamController<dynamic>.broadcast(sync: true);
    final engine = NativePlayerEngine(stateEvents: states.stream);
    states.add({'session_id': engine.sessionId, 'position_ms': 1000, 'buffered_ms': 6000,
      'brightness': 40, 'cached_ranges': List.generate(1000, (i) => {'start_ms': i * 10, 'end_ms': (i + 1) * 10})});
    expect(engine.bufferedRanges, hasLength(1));
    expect(engine.bufferedRanges.single.start, 0);
    expect(engine.bufferedRanges.single.end, 10);
    expect(identical(engine.bufferedRanges, engine.bufferedRanges), isTrue);
    states.add({'position_ms': 1000, 'cached_ranges': [{'start_ms': 0, 'end_ms': 2000}, {'start_ms': 3000, 'end_ms': 4000}]});
    expect(engine.bufferedRanges, hasLength(2));
    await engine.setBrightnessLevel(0.65);
    expect(calls.last.method, 'brightnessLevel'); expect(calls.last.arguments, 0.65);
    expect(engine.brightness, 65);
    await engine.setVolume(73); expect(engine.volume, 73);
    await engine.shutdown(); await states.close();
  });
  test('the native engine reports the video aspect and re-applies the picture mode after a load', () async {
    final calls = <MethodCall>[];
    final messenger = TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger;
    messenger.setMockMethodCallHandler(NativePlayerEngine.channel, (call) async { calls.add(call); return null; });
    addTearDown(() => messenger.setMockMethodCallHandler(NativePlayerEngine.channel, null));
    final states = StreamController<dynamic>.broadcast(sync: true);
    final engine = NativePlayerEngine(stateEvents: states.stream);
    expect(engine.videoAspect, isNull);
    states.add({'session_id': engine.sessionId, 'video_width': 1920, 'video_height': 800});
    expect(engine.videoAspect, closeTo(2.4, 0.001));
    var notified = 0;
    engine.addListener(() => notified++);
    await engine.setVideoScale(VideoScaleMode.crop);
    expect(engine.videoScale, VideoScaleMode.crop);
    expect(notified, 1);
    // Re-selecting the same mode must not spam listeners, but a fresh load
    // still has to hand it to the (rebuilt) native surface again.
    await engine.setVideoScale(VideoScaleMode.crop);
    expect(notified, 1);
    await engine.load(payload, cacheLimitMb: 128, tlsVerify: true);
    expect(calls.any((call) => call.method == 'load'), isTrue);
    await engine.shutdown();
    await states.close();
  });
  test('reentered native player rejects old-session errors and disposes its own session', () async {
    final calls = <MethodCall>[];
    final messenger = TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger;
    messenger.setMockMethodCallHandler(NativePlayerEngine.channel, (call) async { calls.add(call); return null; });
    addTearDown(() => messenger.setMockMethodCallHandler(NativePlayerEngine.channel, null));
    final states = StreamController<dynamic>.broadcast(sync: true);
    final first = NativePlayerEngine(stateEvents: states.stream);
    await first.load(payload, cacheLimitMb: 128, tlsVerify: true);
    final second = NativePlayerEngine(stateEvents: states.stream);
    await second.load(payload, cacheLimitMb: 128, tlsVerify: true);
    expect(first.sessionId, isNot(second.sessionId));
    expect(
      (calls.lastWhere((call) => call.method == 'load').arguments as Map)['session_id'],
      second.sessionId,
    );
    states.add({'session_id': first.sessionId, 'error': "avformat can't open input", 'playing': false});
    expect(first.errorMessage, isNotNull);
    expect(second.errorMessage, isNull);
    states.add({'session_id': second.sessionId, 'playing': true, 'error': null, 'position_ms': 1000});
    expect(second.isPaused, isFalse);
    expect(second.position, 1);
    await first.shutdown();
    expect(
      (calls.lastWhere((call) => call.method == 'dispose').arguments as Map)['session_id'],
      first.sessionId,
    );
    states.add({'session_id': first.sessionId, 'error': 'late error'});
    expect(second.errorMessage, isNull);
    expect(second.isPaused, isFalse);
    await second.shutdown();
    await states.close();
  });
  test('mobile renderers stay in fit mode so Flutter owns cropping', () async {
    final calls = <MethodCall>[];
    final messenger =
        TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger;
    messenger.setMockMethodCallHandler(NativePlayerEngine.channel, (call) async {
      calls.add(call);
      return null;
    });
    addTearDown(() {
      debugDefaultTargetPlatformOverride = null;
      messenger.setMockMethodCallHandler(NativePlayerEngine.channel, null);
    });
    final states = StreamController<dynamic>.broadcast(sync: true);
    final engine = NativePlayerEngine(stateEvents: states.stream);

    debugDefaultTargetPlatformOverride = TargetPlatform.android;
    // 裁剪必须由 Flutter 的 VideoFrame 完成，原生保持 FIT；拉伸仍可用原生的
    // FILL，因为它不依赖视频尺寸，也不会有黑边。
    expect(engine.handlesScaleNatively(VideoScaleMode.crop), isFalse);
    expect(engine.handlesScaleNatively(VideoScaleMode.stretch), isTrue);
    await engine.setVideoScale(VideoScaleMode.crop);
    expect(calls.where((call) => call.method == 'scale').single.arguments, 'fit');

    debugDefaultTargetPlatformOverride = TargetPlatform.iOS;
    expect(engine.handlesScaleNatively(VideoScaleMode.crop), isFalse);
    expect(engine.handlesScaleNatively(VideoScaleMode.stretch), isFalse);
    await engine.setVideoScale(VideoScaleMode.crop);
    expect(
      calls.where((call) => call.method == 'aspectFill').single.arguments,
      false,
    );

    debugDefaultTargetPlatformOverride = TargetPlatform.macOS;
    expect(engine.handlesScaleNatively(VideoScaleMode.crop), isFalse);

    await engine.shutdown();
    await states.close();
  });

  test('mobile player displays buffered range prior to current playback position', () async {
    final messenger = TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger;
    messenger.setMockMethodCallHandler(NativePlayerEngine.channel, (call) async => null);
    addTearDown(() => messenger.setMockMethodCallHandler(NativePlayerEngine.channel, null));
    final states = StreamController<dynamic>.broadcast(sync: true);
    final engine = NativePlayerEngine(stateEvents: states.stream);

    // Initial playback from 0 to 60s, buffered up to 90s
    states.add({
      'session_id': engine.sessionId,
      'position_ms': 60000,
      'buffered_ms': 90000,
      'duration_ms': 300000,
    });

    expect(engine.bufferedRanges, hasLength(1));
    // The range must start at 0 (prior to the 60s current position), not at 60s!
    expect(engine.bufferedRanges.first.start, 0.0);
    expect(engine.bufferedRanges.first.end, 90.0);

    // User seeks forward to 180s
    await engine.seek(180.0);
    states.add({
      'session_id': engine.sessionId,
      'position_ms': 180000,
      'buffered_ms': 200000,
      'duration_ms': 300000,
    });

    // Both the previous watched range [0, 90] and new range [180, 200] must be preserved
    expect(engine.bufferedRanges, hasLength(2));
    expect(engine.bufferedRanges[0].start, 0.0);
    expect(engine.bufferedRanges[0].end, 90.0);
    expect(engine.bufferedRanges[1].start, 180.0);
    expect(engine.bufferedRanges[1].end, 200.0);

    // User seeks back into the first range (at 30s)
    await engine.seek(30.0);
    states.add({
      'session_id': engine.sessionId,
      'position_ms': 30000,
      'buffered_ms': 90000,
      'duration_ms': 300000,
    });

    // The [0, 90] range is fully retained without losing the 0..30s portion
    expect(engine.bufferedRanges, hasLength(2));
    expect(engine.bufferedRanges[0].start, 0.0);
    expect(engine.bufferedRanges[0].end, 90.0);

    await engine.shutdown();
    await states.close();
  });

  test('PlaybackTimelineBuffer handles seeking, keyframe snaps, and resets cleanly', () {
    final buffer = PlaybackTimelineBuffer();

    // Start at 0, play to 10, buffered to 25
    var ranges = buffer.update(position: 10.0, bufferedPosition: 25.0, duration: 100.0);
    expect(ranges, [const BufferedRange(0.0, 25.0)]);

    // Seek to 50
    buffer.onSeek(50.0);
    // Keyframe snap lands slightly earlier at 48.5
    ranges = buffer.update(position: 48.5, bufferedPosition: 65.0, duration: 100.0);
    expect(ranges, [const BufferedRange(0.0, 25.0), const BufferedRange(48.5, 65.0)]);

    // Play continuously past 65 to 70
    ranges = buffer.update(position: 60.0, bufferedPosition: 70.0, duration: 100.0);
    expect(ranges, [const BufferedRange(0.0, 25.0), const BufferedRange(48.5, 70.0)]);

    // Reset with initial resume position
    buffer.reset(initialPosition: 80.0);
    ranges = buffer.update(position: 80.0, bufferedPosition: 95.0, duration: 100.0);
    expect(ranges, [const BufferedRange(80.0, 95.0)]);
  });
}
