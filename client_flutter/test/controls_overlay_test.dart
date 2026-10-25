import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:strmaction_desktop/player/playback_engine.dart';
import 'package:strmaction_desktop/player/widgets/buffered_seekbar.dart';
import 'package:strmaction_desktop/player/widgets/controls_overlay.dart';

ControlsOverlay controls({double position = 10,
  ValueChanged<double>? onSeek}) => ControlsOverlay(
  visible: true, title: 'Test Episode', seriesTitle: 'Test Series',
  position: position, duration: 100, bufferedRanges: const [BufferedRange(10, 40)],
  speed: 1, paused: false, fullscreen: false,
  networkSpeed: 1024, hasPrevious: true, hasNext: true,
  speedBoost: false, speedBoostValue: 2,
  onBack: () {}, onPlayPause: () {}, onPrevious: () {}, onNext: () {},
  onSeek: onSeek ?? (_) {}, onSeekingChanged: (_) {}, onSpeed: () {},
  onEpisodes: () {}, onTracks: () {}, onFrame: () {}, onFullscreen: () {},
);

Future<void> showControls(WidgetTester tester, Size size, EdgeInsets insets,
    {ControlsOverlay? overlay}) async {
  tester.view.physicalSize = size;
  tester.view.devicePixelRatio = 1;
  await tester.pumpWidget(MaterialApp(home: MediaQuery(
    data: MediaQueryData(size: size, padding: insets, viewPadding: insets),
    child: Scaffold(backgroundColor: Colors.black, body: overlay ?? controls()),
  )));
}

void main() {
  for (final width in [320.0, 1280.0]) {
    testWidgets('time follows seek preview and keeps the target until playback catches up at width $width', (tester) async {
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      final seeks = <double>[];
      Future<void> render(double position) => showControls(tester,
        Size(width, 800), EdgeInsets.zero,
        overlay: controls(position: position, onSeek: seeks.add));
      await render(10);
      final bar = tester.getRect(find.byType(BufferedSeekBar));
      Offset at(double ratio) => Offset(bar.left + 11.75 + (bar.width - 23.5) * ratio, bar.center.dy);
      final drag = await tester.startGesture(at(.2));
      await drag.moveTo(at(.4));
      await tester.pump();
      await drag.moveTo(at(.7525));
      await tester.pump();
      expect(find.text('01:15 / 01:40'), findsOneWidget);
      expect(seeks, isEmpty);

      // Playback ticks must not overwrite an active preview.
      await render(11);
      expect(find.text('01:15 / 01:40'), findsOneWidget);
      await drag.moveTo(at(.6025));
      await tester.pump();
      expect(find.text('01:00 / 01:40'), findsOneWidget);
      await drag.up();
      await tester.pump();
      expect(seeks, hasLength(1));
      expect(seeks.single, closeTo(60.25, .01));
      expect(find.text('01:00 / 01:40'), findsOneWidget);
      await render(12);
      expect(find.text('01:00 / 01:40'), findsOneWidget);
      await render(60.25);
      await tester.pump();
      await render(61);
      expect(find.text('01:01 / 01:40'), findsOneWidget);
      expect(tester.takeException(), isNull);
    });

    testWidgets('a pending seek survives a slow seek and restores only after the target arrives at width $width', (tester) async {
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      final seeks = <double>[];
      await showControls(tester, Size(width, 800), EdgeInsets.zero,
        overlay: controls(onSeek: seeks.add));
      final center = tester.getCenter(find.byType(BufferedSeekBar));
      final drag = await tester.startGesture(center);
      await drag.moveBy(const Offset(40, 0));
      await tester.pump();
      expect(find.text('00:10 / 01:40'), findsNothing);
      await drag.cancel();
      await tester.pump();
      expect(find.text('00:10 / 01:40'), findsOneWidget);
      expect(seeks, isEmpty);

      await tester.tapAt(center);
      await tester.pump();
      expect(find.text('00:50 / 01:40'), findsOneWidget);
      // A CDN-backed seek can take seconds. The old 1.5 s timeout made the
      // bar snap back to the playback position before the target arrived.
      await tester.pump(const Duration(milliseconds: 1600));
      expect(find.text('00:50 / 01:40'), findsOneWidget);
      // The safety net still restores the playback time if the seek fails.
      await tester.pump(const Duration(seconds: 21));
      expect(find.text('00:10 / 01:40'), findsOneWidget);

      // Once playback reaches the target the preview ends on its own.
      await tester.tapAt(center);
      await tester.pump();
      expect(find.text('00:50 / 01:40'), findsOneWidget);
      await showControls(tester, Size(width, 800), EdgeInsets.zero,
        overlay: controls(position: 50, onSeek: seeks.add));
      await tester.pump();
      expect(find.text('00:50 / 01:40'), findsOneWidget);
      expect(seeks, hasLength(2));
      expect(tester.takeException(), isNull);
    });

    testWidgets('controls render without overflow at width $width', (tester) async {
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      await showControls(tester, Size(width, 800), EdgeInsets.zero);
      expect(find.text('Test Series - Test Episode'), findsOneWidget);
      expect(find.text('00:10 / 01:40'), findsOneWidget);
      expect(find.text('↓ 1 KB/s'), findsOneWidget);
      expect(find.text('1x'), findsOneWidget);
      expect(tester.getRect(find.text('00:10 / 01:40')).bottom, lessThanOrEqualTo(800));
      expect(tester.takeException(), isNull);
    });
  }

  testWidgets('controls fill the screen while buttons avoid cutouts after rotation', (tester) async {
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    const cases = [
      (Size(393, 852), EdgeInsets.fromLTRB(0, 59, 0, 34)),
      (Size(852, 393), EdgeInsets.fromLTRB(59, 0, 59, 21)),
      (Size(852, 393), EdgeInsets.fromLTRB(0, 0, 59, 21)),
      (Size(412, 915), EdgeInsets.fromLTRB(0, 32, 0, 24)),
    ];
    for (final (size, insets) in cases) {
      await showControls(tester, size, insets);
      final top = tester.getRect(find.byKey(const ValueKey('player-top-bar')));
      final bottom = tester.getRect(find.byKey(const ValueKey('player-bottom-bar')));
      expect(top.topLeft, Offset.zero);
      expect(top.width, size.width);
      expect(bottom.bottom, size.height);
      expect(bottom.left, 0);
      expect(bottom.width, size.width);
      final title = tester.getRect(find.text('Test Series - Test Episode'));
      expect(title.top, greaterThanOrEqualTo(insets.top));
      expect(title.right, lessThanOrEqualTo(size.width - insets.right));
      final seek = tester.getRect(find.byType(BufferedSeekBar));
      expect(seek.left, greaterThanOrEqualTo(insets.left));
      expect(seek.right, lessThanOrEqualTo(size.width - insets.right));
      expect(seek.bottom, lessThanOrEqualTo(size.height - insets.bottom));
      expect(tester.takeException(), isNull);
    }
  });
}
