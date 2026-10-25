import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:strmaction_desktop/core/config.dart';
import 'package:strmaction_desktop/player/playback_engine.dart';
import 'package:strmaction_desktop/player/widgets/video_frame.dart';

/// 16:9 video in a tall phone-shaped viewport: every mode is easy to check.
const Size container = Size(400, 800);
const double aspect = 16 / 9;

Future<void> showFrame(WidgetTester tester, VideoScaleMode mode, {double? videoAspect = aspect}) async {
  tester.view.physicalSize = container;
  tester.view.devicePixelRatio = 1;
  await tester.pumpWidget(Directionality(
    textDirection: TextDirection.ltr,
    child: Center(
      child: SizedBox(
        width: container.width,
        height: container.height,
        child: VideoFrame(
          mode: mode,
          aspect: videoAspect,
          child: const ColoredBox(color: Colors.red, key: ValueKey('surface')),
        ),
      ),
    ),
  ));
}

Rect surface(WidgetTester tester) => tester.getRect(find.byKey(const ValueKey('surface')));

void main() {
  test('every configured scale id round-trips through the mode enum', () {
    for (final id in videoScaleIds) {
      expect(videoScaleModeFromId(id).id, id, reason: 'scale id $id');
    }
    expect(videoScaleModeFromId('nonsense'), VideoScaleMode.fit);
    expect(videoScaleModeFromId(null), VideoScaleMode.fit);
    expect(AppConfig.fromJson({'video_scale': '16:9'}).videoScale, '16:9');
    expect(AppConfig.fromJson({'video_scale': 'nonsense'}).videoScale, 'fit');
    expect(const AppConfig().videoScale, 'fit');
    expect(const AppConfig().copyWith(videoScale: 'crop').videoScale, 'crop');
  });

  test('fit and crop derive their rectangle from the video aspect', () {
    expect(VideoFrame.targetSize(VideoScaleMode.fit, container, aspect),
        const Size(400, 225));
    // Cover: the height drives the scale, so the width overflows and is clipped.
    expect(VideoFrame.targetSize(VideoScaleMode.crop, container, aspect).height, 800);
    expect(VideoFrame.targetSize(VideoScaleMode.crop, container, aspect).width,
        closeTo(800 * 16 / 9, 0.01));
    // A viewport wider than the video: fit is limited by height, crop by width.
    const wide = Size(1000, 400);
    final fitted = VideoFrame.targetSize(VideoScaleMode.fit, wide, aspect);
    expect(fitted.height, closeTo(400, 0.01));
    expect(fitted.width, closeTo(400 * 16 / 9, 0.01));
    final cropped = VideoFrame.targetSize(VideoScaleMode.crop, wide, aspect);
    expect(cropped.width, closeTo(1000, 0.01));
    expect(cropped.height, closeTo(562.5, 0.01));
  });

  test('stretch keeps the video rectangle and distorts it while scaling', () {
    // The rectangle still carries the video ratio; BoxFit.fill does the stretch.
    expect(VideoFrame.targetSize(VideoScaleMode.stretch, container, aspect),
        const Size(400, 225));
    expect(VideoFrame.boxFitFor(VideoScaleMode.stretch), BoxFit.fill);
    expect(VideoFrame.boxFitFor(VideoScaleMode.crop), BoxFit.cover);
    expect(VideoFrame.boxFitFor(VideoScaleMode.fit), BoxFit.contain);
  });

  test('forced frames follow the requested ratio, not the video', () {
    expect(VideoFrame.targetSize(VideoScaleMode.ratio4x3, container, aspect),
        const Size(400, 300));
    expect(VideoFrame.targetSize(VideoScaleMode.ratio16x9, container, aspect),
        const Size(400, 225));
    final cinema = VideoFrame.targetSize(VideoScaleMode.ratio21x9, container, aspect);
    expect(cinema.width, closeTo(400, 0.01));
    expect(cinema.height, closeTo(400 * 9 / 21, 0.01));
  });

  test('an unknown aspect keeps the surface filling the viewport', () {
    for (final mode in VideoScaleMode.values) {
      if (mode.forcedAspect != null) continue;
      expect(VideoFrame.targetSize(mode, container, null), container);
      expect(VideoFrame.targetSize(mode, container, double.nan), container);
      expect(VideoFrame.targetSize(mode, container, 0), container);
    }
  });

  testWidgets('fit letterboxes the picture inside the viewport', (tester) async {
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    await showFrame(tester, VideoScaleMode.fit);
    final rect = surface(tester);
    expect(rect.width, closeTo(400, 0.01));
    expect(rect.height, closeTo(225, 0.01));
    expect(rect.center.dy, closeTo(400, 0.01));
    expect(tester.takeException(), isNull);
  });

  testWidgets('crop fills the viewport and overflows on the long axis', (tester) async {
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    await showFrame(tester, VideoScaleMode.crop);
    final rect = surface(tester);
    expect(rect.height, closeTo(800, 0.01));
    expect(rect.width, greaterThan(400));
    expect(rect.width / rect.height, closeTo(aspect, 0.01));
    expect(rect.center, const Offset(200, 400));
    expect(tester.takeException(), isNull);
  });

  testWidgets('stretch fills the viewport even though it distorts the picture', (tester) async {
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    await showFrame(tester, VideoScaleMode.stretch);
    final rect = surface(tester);
    expect(rect.width, closeTo(400, 0.01));
    expect(rect.height, closeTo(800, 0.01));
    expect(rect.topLeft, Offset.zero);
    expect(tester.takeException(), isNull);
  });

  testWidgets('a forced frame keeps the video ratio inside that frame', (tester) async {
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    await showFrame(tester, VideoScaleMode.ratio4x3);
    final rect = surface(tester);
    expect(rect.width / rect.height, closeTo(4 / 3, 0.01));
    expect(rect.bottom, lessThanOrEqualTo(800));
    expect(tester.takeException(), isNull);
  });
}
