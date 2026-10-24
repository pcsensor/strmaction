import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:strmaction_desktop/player/playback_engine.dart';
import 'package:strmaction_desktop/player/widgets/controls_overlay.dart';

void main() {
  for (final width in [320.0, 1280.0]) {
  testWidgets('controls render without overflow at width $width', (tester) async {
    tester.view.physicalSize = Size(width, 800);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          backgroundColor: Colors.black,
          body: SizedBox(
            width: width,
            height: 800,
            child: ControlsOverlay(
              visible: true,
              title: 'Test Episode',
              seriesTitle: 'Test Series',
              position: 10,
              duration: 100,
              bufferedRanges: const [BufferedRange(10, 40)],
              speed: 1,
              paused: false,
              fullscreen: false,
              loading: false,
              networkSpeed: 1024,
              hasPrevious: true,
              hasNext: true,
              speedBoost: false,
              speedBoostValue: 2,
              centerIconPath: null,
              centerText: null,
              showCenterIcon: false,
              showCenterText: false,
              onBack: () {},
              onPlayPause: () {},
              onPrevious: () {},
              onNext: () {},
              onSeek: (_) {},
              onSeekingChanged: (_) {},
              onSpeed: () {},
              onEpisodes: () {},
              onTracks: () {},
              onFullscreen: () {},
            ),
          ),
        ),
      ),
    );
    expect(find.text('Test Series - Test Episode'), findsOneWidget);
    expect(find.text('00:10 / 01:40'), findsOneWidget);
    expect(find.text('↓ 1 KB/s'), findsOneWidget);
    expect(find.text('1x'), findsOneWidget);
    final timeRect = tester.getRect(find.text('00:10 / 01:40'));
    expect(timeRect.bottom, lessThanOrEqualTo(800));
    expect(tester.takeException(), isNull);
  });
  }
}
