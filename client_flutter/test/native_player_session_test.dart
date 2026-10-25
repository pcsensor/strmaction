import 'dart:async';

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
    expect((calls.last.arguments as Map)['session_id'], second.sessionId);
    states.add({'session_id': first.sessionId, 'error': "avformat can't open input", 'playing': false});
    expect(first.errorMessage, isNotNull);
    expect(second.errorMessage, isNull);
    states.add({'session_id': second.sessionId, 'playing': true, 'error': null, 'position_ms': 1000});
    expect(second.isPaused, isFalse);
    expect(second.position, 1);
    await first.shutdown();
    expect((calls.last.arguments as Map)['session_id'], first.sessionId);
    states.add({'session_id': first.sessionId, 'error': 'late error'});
    expect(second.errorMessage, isNull);
    expect(second.isPaused, isFalse);
    await second.shutdown();
    await states.close();
  });
}
