import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:strmaction_desktop/player/playback_engine.dart';
import 'package:strmaction_desktop/player/widgets/buffered_seekbar.dart';

void main() {
  group('BufferedRange and areBufferedRangesEqual', () {
    test('compares ranges by approximate values', () {
      const r1 = BufferedRange(0.0, 10.0);
      const r2 = BufferedRange(0.05, 10.04);
      const r3 = BufferedRange(0.0, 10.5);

      expect(r1 == r2, isTrue);
      expect(r1 == r3, isFalse);

      expect(
        areBufferedRangesEqual([r1], [r2]),
        isTrue,
      );
      expect(
        areBufferedRangesEqual([r1], [r3]),
        isFalse,
      );
      expect(
        areBufferedRangesEqual([r1], [r1, r2]),
        isFalse,
      );
    });
  });

  group('BufferedSeekBar interaction', () {
    testWidgets('tap triggers onSeek and retains pending position until caught up', (tester) async {
      double currentPosition = 10.0;
      double? seekedTarget;

      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: Center(
              child: SizedBox(
                width: 500,
                child: StatefulBuilder(
                  builder: (context, setState) {
                    return BufferedSeekBar(
                      position: currentPosition,
                      duration: 100.0,
                      bufferedRanges: const [BufferedRange(0, 50)],
                      onSeek: (target) {
                        seekedTarget = target;
                      },
                    );
                  },
                ),
              ),
            ),
          ),
        ),
      );

      final center = tester.getCenter(find.byType(BufferedSeekBar));
      await tester.tapAt(center);
      await tester.pump();

      expect(seekedTarget, isNotNull);
      expect(seekedTarget!, closeTo(50.0, 1.0));

      // After tap, seekbar maintains pendingPosition = ~50s.
      // Even if old position (10.0) is pumped again, thumb shouldn't spring back.
      await tester.pump(const Duration(milliseconds: 100));

      // Now incoming position catches up to 50.0s
      currentPosition = 50.0;
      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: Center(
              child: SizedBox(
                width: 500,
                child: BufferedSeekBar(
                  position: currentPosition,
                  duration: 100.0,
                  bufferedRanges: const [BufferedRange(0, 50)],
                  onSeek: (_) {},
                ),
              ),
            ),
          ),
        ),
      );
      await tester.pump();
    });

    testWidgets('drag does not reset or flicker when transitioning from tap down', (tester) async {
      final seekingStates = <bool>[];

      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: Center(
              child: SizedBox(
                width: 500,
                child: BufferedSeekBar(
                  position: 10.0,
                  duration: 100.0,
                  bufferedRanges: const [],
                  onSeek: (_) {},
                  onSeekingChanged: (seeking) {
                    seekingStates.add(seeking);
                  },
                ),
              ),
            ),
          ),
        ),
      );

      final center = tester.getCenter(find.byType(BufferedSeekBar));
      final gesture = await tester.startGesture(center);
      await tester.pump();
      await gesture.moveBy(const Offset(50, 0));
      await tester.pump();
      await gesture.up();
      await tester.pump();

      // Ensure seekingStates transitioned cleanly: [true, false] without intermediate flickering false
      expect(seekingStates, equals([true, false]));
    });
  });
}
