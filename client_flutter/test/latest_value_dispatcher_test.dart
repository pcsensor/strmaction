import 'dart:async';

import 'package:flutter_test/flutter_test.dart';
import 'package:strmaction_desktop/player/input/latest_value_dispatcher.dart';

void main() {
  testWidgets('gesture bursts apply only the newest target and flush the final value', (tester) async {
    final applied = <int>[];
    final dispatcher = LatestValueDispatcher<int>(apply: (value) async { applied.add(value); }, onError: (_) {});
    for (var i = 0; i < 100; i++) { dispatcher.schedule(i); }
    expect(applied, isEmpty);
    await tester.pump(const Duration(milliseconds: 40));
    expect(applied, [99]);
    dispatcher.schedule(100);
    await dispatcher.flush();
    expect(applied, [99, 100]);
    dispatcher.dispose();
  });

  testWidgets('slow native calls remain single-flight while the latest pending target wins', (tester) async {
    final first = Completer<void>();
    final applied = <int>[];
    final dispatcher = LatestValueDispatcher<int>(apply: (value) async {
      applied.add(value);
      if (value == 1) await first.future;
    }, onError: (_) {});
    dispatcher.schedule(1); await tester.pump(const Duration(milliseconds: 40));
    for (var i = 2; i < 100; i++) { dispatcher.schedule(i); }
    await tester.pump(const Duration(seconds: 1));
    expect(applied, [1]);
    final flushed = dispatcher.flush();
    first.complete(); await flushed;
    expect(applied, [1, 99]);
    dispatcher.dispose();
  });

  testWidgets('errors are handled and disposed gestures cannot send queued commands', (tester) async {
    final applied = <int>[];
    final errors = <Object>[];
    final dispatcher = LatestValueDispatcher<int>(apply: (value) async {
      applied.add(value); throw StateError('native unavailable');
    }, onError: errors.add);
    dispatcher.schedule(1); await dispatcher.flush();
    expect(errors, hasLength(1));
    dispatcher.schedule(2); dispatcher.dispose();
    await tester.pump(const Duration(seconds: 1));
    expect(applied, [1]); expect(tester.takeException(), isNull);
  });
}
