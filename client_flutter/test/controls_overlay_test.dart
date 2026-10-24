import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:strmaction_desktop/player/playback_engine.dart';
import 'package:strmaction_desktop/player/widgets/buffered_seekbar.dart';
import 'package:strmaction_desktop/player/widgets/controls_overlay.dart';

ControlsOverlay controls() => ControlsOverlay(
  visible: true, title: 'Test Episode', seriesTitle: 'Test Series',
  position: 10, duration: 100, bufferedRanges: const [BufferedRange(10, 40)],
  speed: 1, paused: false, fullscreen: false, loading: false,
  networkSpeed: 1024, hasPrevious: true, hasNext: true,
  speedBoost: false, speedBoostValue: 2, centerIconPath: null,
  centerText: null, showCenterIcon: false, showCenterText: false,
  onBack: () {}, onPlayPause: () {}, onPrevious: () {}, onNext: () {},
  onSeek: (_) {}, onSeekingChanged: (_) {}, onSpeed: () {},
  onEpisodes: () {}, onTracks: () {}, onFullscreen: () {},
);

Future<void> showControls(WidgetTester tester, Size size, EdgeInsets insets) async {
  tester.view.physicalSize = size;
  tester.view.devicePixelRatio = 1;
  await tester.pumpWidget(MaterialApp(home: MediaQuery(
    data: MediaQueryData(size: size, padding: insets, viewPadding: insets),
    child: Scaffold(backgroundColor: Colors.black, body: controls()),
  )));
}

void main() {
  for (final width in [320.0, 1280.0]) {
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
