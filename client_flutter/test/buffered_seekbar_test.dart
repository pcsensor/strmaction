import 'package:flutter/material.dart';
import 'dart:ui' as ui;
import 'dart:typed_data';
import 'package:flutter_test/flutter_test.dart';
import 'package:strmaction_desktop/player/playback_engine.dart';
import 'package:strmaction_desktop/player/widgets/buffered_seekbar.dart';

void main() {
  group('BufferedRange and areBufferedRangesEqual', () {
    test('merges thousands of adjacent fragments and overlaps without filling holes', () {
      final fragments = List.generate(2000, (i) => BufferedRange(i.toDouble(), i + 1.0)).reversed;
      final merged = mergeBufferedRanges([...fragments, const BufferedRange(100, 400),
        const BufferedRange(2001, 2100), const BufferedRange(double.nan, 20)]);
      expect(merged, [const BufferedRange(0, 2000), const BufferedRange(2001, 2100)]);
    });
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
    testWidgets('dense adjacent fragments paint a solid line while actual holes stay visible', (tester) async {
      Future<ByteData> raster(List<BufferedRange> ranges) async {
        await tester.pumpWidget(MaterialApp(home: Scaffold(body: Center(child: SizedBox(
          width: 320, child: BufferedSeekBar(position: 0, duration: 3600,
            bufferedRanges: ranges, onSeek: (_) {}),
        )))));
        final painter = tester.widget<CustomPaint>(find.descendant(
          of: find.byType(BufferedSeekBar), matching: find.byType(CustomPaint))).painter!;
        final recorder = ui.PictureRecorder();
        painter.paint(Canvas(recorder), const Size(320, 32));
        final picture = recorder.endRecording();
        return (await tester.runAsync(() async {
          final image = await picture.toImage(320, 32);
          final bytes = (await image.toByteData(format: ui.ImageByteFormat.rawRgba))!;
          image.dispose(); picture.dispose();
          return bytes;
        }))!;
      }
      final solid = await raster(List.generate(1000, (i) => BufferedRange(i.toDouble(), i + 1.0)));
      for (var x = 20; x < 85; x++) {
        expect(solid.getUint8((16 * 320 + x) * 4 + 3), greaterThan(220), reason: 'dotted at pixel $x');
      }
      final gap = await raster(const [BufferedRange(0, 500), BufferedRange(1000, 1500)]);
      expect(gap.getUint8((16 * 320 + 60) * 4 + 3), lessThan(100));
    });
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

    testWidgets('a slow seek keeps the head on the target instead of snapping back', (tester) async {
      var position = 10.0;
      Widget bar() => MaterialApp(
        home: Scaffold(
          body: Center(
            child: SizedBox(
              width: 500,
              child: BufferedSeekBar(
                position: position,
                duration: 100.0,
                bufferedRanges: const [BufferedRange(0, 50)],
                onSeek: (_) {},
              ),
            ),
          ),
        ),
      );
      double shown() => ((tester
              .widget<CustomPaint>(find.descendant(
                  of: find.byType(BufferedSeekBar),
                  matching: find.byType(CustomPaint)))
              .painter) as dynamic)
          .position as double;

      await tester.pumpWidget(bar());
      await tester.tapAt(tester.getCenter(find.byType(BufferedSeekBar)));
      await tester.pump();
      final target = shown();
      expect(target, closeTo(50.6, 2));

      // The origin connection can take seconds. While the engine still reports
      // the old position the head must stay where the user clicked.
      await tester.pump(const Duration(seconds: 2));
      expect(shown(), closeTo(target, 0.01));
      await tester.pumpWidget(bar());
      await tester.pump(const Duration(seconds: 2));
      expect(shown(), closeTo(target, 0.01));

      // Playback reaches the target: the bar follows the engine again.
      position = target;
      await tester.pumpWidget(bar());
      await tester.pump();
      expect(shown(), closeTo(target, 0.01));
    });

    testWidgets('the cached line stays frozen while the user drags', (tester) async {
      var ranges = const [BufferedRange(0, 50)];
      Widget bar() => MaterialApp(
        home: Scaffold(
          body: Center(
            child: SizedBox(
              width: 500,
              child: BufferedSeekBar(
                position: 10.0,
                duration: 100.0,
                bufferedRanges: ranges,
                onSeek: (_) {},
              ),
            ),
          ),
        ),
      );
      List<BufferedRange> painted() => ((tester
              .widget<CustomPaint>(find.descendant(
                  of: find.byType(BufferedSeekBar),
                  matching: find.byType(CustomPaint)))
              .painter) as dynamic)
          .bufferedRanges as List<BufferedRange>;

      await tester.pumpWidget(bar());
      final gesture = await tester.startGesture(tester.getCenter(find.byType(BufferedSeekBar)));
      // Let the tap deadline resolve, then drag: both paths freeze the line.
      await tester.pump(const Duration(milliseconds: 200));
      await gesture.moveBy(const Offset(24, 0));
      await tester.pump();
      // The engine publishes a longer cached range mid-drag.
      ranges = const [BufferedRange(0, 80)];
      await tester.pumpWidget(bar());
      await tester.pump();
      expect(painted(), const [BufferedRange(0, 50)],
          reason: 'the line must not crawl under the finger');

      // Still frozen while the seek settles.
      await gesture.up();
      await tester.pump();
      await tester.pumpWidget(bar());
      await tester.pump();
      expect(painted(), const [BufferedRange(0, 50)]);
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
