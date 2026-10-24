import 'dart:async';

import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:strmaction_desktop/models/playback_payload.dart';
import 'package:strmaction_desktop/player/native_player_engine.dart';

const payload = PlaybackPayload(itemId: 1, playUrl: 'https://media.invalid/video.mp4',
  headers: {}, playToken: 'test', resumeMs: 0, progressIntervalMs: 60000,
  subtitles: [], title: 'Video', seriesTitle: '', playlist: [], nextItemId: null,
  nextTitle: '', currentIndex: 0, durationMs: 100000);

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
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
