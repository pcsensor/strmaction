import 'dart:async';
import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:media_kit_video/media_kit_video.dart';
import 'package:strmaction_desktop/app_controller.dart';
import 'package:strmaction_desktop/core/app_logger.dart';
import 'package:strmaction_desktop/core/app_paths.dart';
import 'package:strmaction_desktop/core/cli_options.dart';
import 'package:strmaction_desktop/core/config.dart';
import 'package:strmaction_desktop/models/playback_payload.dart';
import 'package:strmaction_desktop/player/playback_engine.dart';
import 'package:strmaction_desktop/player/player_page.dart';
import 'package:strmaction_desktop/player/widgets/controls_overlay.dart';
import 'package:strmaction_desktop/player/widgets/message_card.dart';
import 'package:strmaction_desktop/player/widgets/player_drawer.dart';

class FakeEngine extends PlaybackEngine {
  bool paused = false;
  int nativeTaps = 0;
  int loadCalls = 0;
  int videoBuilds = 0;
  String? failure;
  bool buffering = false;
  double volumeValue = 50;
  double brightnessValue = 40;
  double speedValue = 1;
  final speeds = <double>[];
  final volumes = <int>[];
  final brightnesses = <double>[];
  final seeks = <double>[];
  final loading = Completer<void>();
  @override VideoController? get videoController => null;
  @override double get position => 10;
  @override double get duration => 100;
  @override bool get isPaused => paused;
  @override double get speed => speedValue;
  @override double get volume => volumeValue;
  @override double? get brightness => brightnessValue;
  @override bool get isLoading => false;
  @override bool get isBuffering => buffering;
  @override bool get completed => false;
  @override String? get errorMessage => failure;
  @override double? get networkSpeed => null;
  @override List<BufferedRange> get bufferedRanges => const [];
  @override List<TrackInfo> get audioTracks => const [];
  @override List<TrackInfo> get subtitleTracks => const [];
  @override String? get currentAudioId => null;
  @override String? get currentSubtitleId => null;
  @override Future<void> load(PlaybackPayload payload, {required int cacheLimitMb, required bool tlsVerify}) {
    loadCalls += 1;
    notifyListeners();
    // Keep networking out of the input tests; player state still arrives normally.
    return loading.future;
  }
  @override Future<void> setPaused(bool value) async { paused = value; notifyListeners(); }
  @override Future<void> play() => setPaused(false);
  @override Future<void> pause() => setPaused(true);
  @override Future<void> setSpeed(double value) async { speeds.add(value); speedValue = value; notifyListeners(); }
  @override Future<void> shutdown() async {}
  @override Future<void> setVolume(int percent) async { volumes.add(percent); volumeValue = percent.toDouble(); }
  @override Future<void> setBrightnessLevel(double level) async { brightnesses.add(level); brightnessValue = level * 100; }
  @override Future<void> seek(double seconds, {bool relative = false}) async { seeks.add(seconds); }
  @override Widget buildVideo() { videoBuilds++; return GestureDetector(
    behavior: HitTestBehavior.opaque, onTap: () => nativeTaps++,
    child: const ColoredBox(color: Colors.black),
  ); }
  @override dynamic noSuchMethod(Invocation invocation) => super.noSuchMethod(invocation);
}

Future<FakeEngine> mountPlayer(WidgetTester tester) async {
  tester.view.physicalSize = const Size(393, 852);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.resetPhysicalSize);
  addTearDown(tester.view.resetDevicePixelRatio);
  final directory = Directory.systemTemp.createTempSync('strmaction-input-');
  final paths = AppPaths(directory.path);
  final app = AppController(paths: paths, configStore: ConfigStore(paths),
    logger: AppLogger(paths), options: const CliOptions(), initialConfig: const AppConfig());
  final engine = FakeEngine();
  addTearDown(() async {
    await tester.pumpWidget(const SizedBox.shrink());
    await tester.pump();
    await app.shutdown();
    app.dispose();
    directory.deleteSync(recursive: true);
  });
  await tester.pumpWidget(MaterialApp(theme: ThemeData.dark(), home: MediaQuery(
    data: const MediaQueryData(size: Size(393, 852),
      padding: EdgeInsets.fromLTRB(0, 59, 0, 34), viewPadding: EdgeInsets.fromLTRB(0, 59, 0, 34)),
    child: PlayerPage(app: app, engine: engine, payload: const PlaybackPayload(
      itemId: 1, playUrl: 'https://media.invalid/video.mp4', headers: {}, playToken: 'test',
      resumeMs: 0, progressIntervalMs: 60000, subtitles: [], title: 'Video', seriesTitle: '',
      playlist: [], nextItemId: null, nextTitle: '', currentIndex: 0, durationMs: 100000,
    )),
  )));
  await tester.pump();
  return engine;
}

bool controlsVisible(WidgetTester tester) => tester.widget<ControlsOverlay>(find.byType(ControlsOverlay)).visible;
Future<void> tapScreen(WidgetTester tester) async {
  await tester.tapAt(const Offset(196, 400));
  await tester.pump(const Duration(milliseconds: 350));
}

void main() {
  for (final platform in [TargetPlatform.android, TargetPlatform.iOS]) {
    testWidgets('$platform brightness swipe animates feedback with hidden controls', (tester) async {
      final engine = await mountPlayer(tester);
      await tapScreen(tester);
      expect(controlsVisible(tester), isFalse);
      final gesture = await tester.startGesture(const Offset(80, 500));
      await gesture.moveBy(const Offset(0, -30)); await tester.pump();
      await gesture.moveBy(const Offset(0, -100)); await tester.pump(const Duration(milliseconds: 100));
      await tester.pump(const Duration(milliseconds: 100));
      expect(find.byKey(const ValueKey('player-gesture-feedback')), findsOneWidget);
      expect(find.textContaining('亮度 '), findsOneWidget);
      final level = tester.widget<LinearProgressIndicator>(find.byKey(const ValueKey('player-gesture-level'))).value!;
      expect(level, greaterThan(0.4));
      expect(engine.brightnesses.last, greaterThan(0.4));
      expect(controlsVisible(tester), isFalse);
      await gesture.up(); await tester.pump(const Duration(milliseconds: 700));
      await tester.pump(const Duration(milliseconds: 220));
      expect(find.byKey(const ValueKey('player-gesture-feedback')), findsNothing);
      expect(tester.takeException(), isNull);
    }, variant: TargetPlatformVariant({platform}));

    testWidgets('$platform small volume movements accumulate and platform calls stay bounded', (tester) async {
      final engine = await mountPlayer(tester);
      await tapScreen(tester);
      final videoBuilds = engine.videoBuilds;
      final gesture = await tester.startGesture(const Offset(310, 500));
      await gesture.moveBy(const Offset(0, -30)); await tester.pump();
      for (var i = 0; i < 100; i++) {
        await gesture.moveBy(const Offset(0, -0.5));
        await tester.pump(const Duration(milliseconds: 1));
      }
      expect(find.textContaining('音量 '), findsOneWidget);
      await gesture.up(); await tester.pump();
      expect(engine.volumes.last, greaterThan(55));
      expect(engine.volumes.length, lessThan(10));
      expect(engine.brightnesses, isEmpty);
      expect(engine.videoBuilds, videoBuilds, reason: 'gesture frames must only rebuild the feedback layer');
      expect(tester.takeException(), isNull);
    }, variant: TargetPlatformVariant({platform}));

    testWidgets('$platform visible controls block brightness, volume and long press boost', (tester) async {
      final engine = await mountPlayer(tester);
      await tester.dragFrom(const Offset(80, 500), const Offset(0, -150));
      await tester.pump();
      await tester.dragFrom(const Offset(310, 500), const Offset(0, -150));
      await tester.pump();
      final hold = await tester.startGesture(const Offset(196, 400));
      await tester.pump(const Duration(milliseconds: 600));
      expect(engine.brightnesses, isEmpty);
      expect(engine.volumes, isEmpty);
      expect(engine.speeds, isEmpty);
      expect(find.byKey(const ValueKey('player-gesture-feedback')), findsNothing);
      expect(find.byKey(const ValueKey('player-speed-boost')), findsNothing);
      expect(controlsVisible(tester), isTrue);
      await hold.up();
      await tester.pump();
      expect(engine.speeds, isEmpty);
      expect(tester.takeException(), isNull);
    }, variant: TargetPlatformVariant({platform}));

    testWidgets('$platform boost stays visible with hidden controls until release', (tester) async {
      final engine = await mountPlayer(tester);
      engine.speedValue = 1.25;
      await tapScreen(tester);
      final hold = await tester.startGesture(const Offset(196, 400));
      await tester.pump(const Duration(milliseconds: 600));
      expect(engine.speeds, [2]);
      expect(controlsVisible(tester), isFalse);
      final badge = find.byKey(const ValueKey('player-speed-boost'));
      expect(badge, findsOneWidget);
      expect(find.ancestor(of: badge, matching: find.byType(AnimatedOpacity)), findsNothing);
      await tester.pump(const Duration(seconds: 5));
      engine.notifyListeners();
      await tester.pump();
      expect(badge, findsOneWidget);
      expect(controlsVisible(tester), isFalse);
      await hold.up();
      await tester.pump();
      expect(engine.speeds, [2, 1.25]);
      expect(badge, findsNothing);
      expect(controlsVisible(tester), isFalse);
      expect(tester.takeException(), isNull);
    }, variant: TargetPlatformVariant({platform}));

    testWidgets('$platform cancelling a boost restores playback speed and hides the badge', (tester) async {
      final engine = await mountPlayer(tester);
      await tapScreen(tester);
      final hold = await tester.startGesture(const Offset(196, 400));
      await tester.pump(const Duration(milliseconds: 600));
      expect(engine.speeds, [2]);
      await hold.cancel();
      await tester.pump();
      expect(engine.speeds, [2, 1]);
      expect(find.byKey(const ValueKey('player-speed-boost')), findsNothing);
      expect(controlsVisible(tester), isFalse);
      expect(tester.takeException(), isNull);
    }, variant: TargetPlatformVariant({platform}));

    testWidgets('$platform seek swipe previews locally and only seeks once on release', (tester) async {
      final engine = await mountPlayer(tester);
      final gesture = await tester.startGesture(const Offset(100, 400));
      await gesture.moveBy(const Offset(30, 0)); await tester.pump();
      for (var i = 0; i < 20; i++) {
        await gesture.moveBy(const Offset(3, 0)); await tester.pump(const Duration(milliseconds: 10));
      }
      expect(find.byKey(const ValueKey('player-gesture-feedback')), findsOneWidget);
      expect(engine.seeks, isEmpty);
      await gesture.up(); await tester.pump();
      expect(engine.seeks, hasLength(1)); expect(engine.seeks.single, greaterThan(10));
      expect(tester.takeException(), isNull);
    }, variant: TargetPlatformVariant({platform}));

    testWidgets('$platform locked swipes neither show feedback nor adjust device levels', (tester) async {
      final engine = await mountPlayer(tester);
      await tester.tap(find.byTooltip('锁定')); await tester.pump();
      await tester.dragFrom(const Offset(310, 500), const Offset(0, -150));
      await tester.pump(const Duration(milliseconds: 200));
      expect(engine.volumes, isEmpty); expect(engine.brightnesses, isEmpty);
      expect(find.byKey(const ValueKey('player-gesture-feedback')), findsNothing);
    }, variant: TargetPlatformVariant({platform}));

    testWidgets('$platform taps show and hide controls without reaching native video', (tester) async {
      final engine = await mountPlayer(tester);
      expect(controlsVisible(tester), isTrue);
      expect(tester.getRect(find.byKey(const ValueKey('player-viewport'))), const Rect.fromLTWH(0, 0, 393, 852));
      await tapScreen(tester);
      expect(controlsVisible(tester), isFalse);
      await tapScreen(tester);
      expect(controlsVisible(tester), isTrue);
      expect(engine.nativeTaps, 0);
      expect(tester.takeException(), isNull);
    }, variant: TargetPlatformVariant({platform}));

    testWidgets('$platform auto hides after starting and allows hiding while paused', (tester) async {
      final engine = await mountPlayer(tester);
      await tester.pump(const Duration(seconds: 2));
      engine.notifyListeners();
      await tester.pump(const Duration(milliseconds: 1600));
      expect(controlsVisible(tester), isFalse);
      await engine.pause();
      await tester.pump();
      expect(controlsVisible(tester), isTrue);
      await tapScreen(tester);
      engine.notifyListeners();
      await tester.pump(const Duration(seconds: 1));
      expect(controlsVisible(tester), isFalse);
      await tapScreen(tester);
      expect(controlsVisible(tester), isTrue);
      expect(tester.takeException(), isNull);
    }, variant: TargetPlatformVariant({platform}));

    testWidgets('$platform control buttons and drawer taps do not toggle the screen', (tester) async {
      await mountPlayer(tester);
      await tester.tap(find.descendant(of: find.byType(ControlsOverlay), matching: find.text('1x')));
      await tester.pump(const Duration(milliseconds: 300));
      expect(tester.widget<PlayerDrawer>(find.byType(PlayerDrawer)).visible, isTrue);
      expect(controlsVisible(tester), isTrue);
      await tester.tapAt(const Offset(20, 400));
      await tester.pump(const Duration(milliseconds: 350));
      expect(tester.widget<PlayerDrawer>(find.byType(PlayerDrawer)).visible, isFalse);
      expect(controlsVisible(tester), isTrue);
      expect(tester.takeException(), isNull);
    }, variant: TargetPlatformVariant({platform}));

    testWidgets('$platform locked icon auto hides and taps toggle it even while paused', (tester) async {
      final engine = await mountPlayer(tester);
      await tester.tapAt(const Offset(196, 400));
      await tester.pump(const Duration(milliseconds: 50));
      await tester.tapAt(const Offset(196, 400));
      await tester.pump(const Duration(milliseconds: 350));
      expect(engine.paused, isTrue);
      expect(controlsVisible(tester), isTrue);
      await tester.tap(find.byTooltip('锁定'));
      await tester.pump(const Duration(milliseconds: 200));
      expect(controlsVisible(tester), isFalse);
      expect(find.byTooltip('解锁'), findsOneWidget);
      await tester.pump(const Duration(milliseconds: 3600));
      expect(find.byTooltip('解锁'), findsNothing);
      engine.notifyListeners();
      await tester.pump();
      expect(find.byTooltip('解锁'), findsNothing);
      await tapScreen(tester);
      expect(find.byTooltip('解锁'), findsOneWidget);
      expect(controlsVisible(tester), isFalse);
      await tapScreen(tester);
      expect(find.byTooltip('解锁'), findsNothing);
      await tapScreen(tester);
      await tester.tap(find.byTooltip('解锁'));
      await tester.pump(const Duration(milliseconds: 200));
      expect(controlsVisible(tester), isTrue);
      expect(engine.nativeTaps, 0);
      expect(tester.takeException(), isNull);
    }, variant: TargetPlatformVariant({platform}));

    testWidgets('$platform stale error closes on recovery and the same new failure is shown', (tester) async {
      final engine = await mountPlayer(tester);
      engine.failure = "avformat can't open input";
      engine.paused = true;
      engine.notifyListeners();
      await tester.pump();
      expect(tester.widget<MessageCard>(find.byType(MessageCard)).visible, isTrue);
      engine.failure = null;
      engine.paused = false;
      engine.buffering = true;
      engine.notifyListeners();
      await tester.pump();
      expect(tester.widget<MessageCard>(find.byType(MessageCard)).visible, isTrue);
      engine.buffering = false;
      engine.notifyListeners();
      await tester.pump();
      expect(tester.widget<MessageCard>(find.byType(MessageCard)).visible, isFalse);
      engine.failure = "avformat can't open input";
      engine.paused = true;
      engine.notifyListeners();
      await tester.pump();
      expect(tester.widget<MessageCard>(find.byType(MessageCard)).visible, isTrue);
      expect(tester.takeException(), isNull);
    }, variant: TargetPlatformVariant({platform}));

    testWidgets('$platform error can be dismissed without retrying or stopping video', (tester) async {
      final engine = await mountPlayer(tester);
      engine.failure = "avformat can't open input";
      engine.notifyListeners();
      await tester.pump(const Duration(milliseconds: 200));
      await tester.tap(find.byTooltip('关闭提示'));
      await tester.pump(const Duration(milliseconds: 200));
      expect(tester.widget<MessageCard>(find.byType(MessageCard)).visible, isFalse);
      expect(engine.loadCalls, 1);
      expect(engine.paused, isFalse);
      engine.notifyListeners();
      await tester.pump();
      expect(tester.widget<MessageCard>(find.byType(MessageCard)).visible, isFalse);
      expect(tester.takeException(), isNull);
    }, variant: TargetPlatformVariant({platform}));
  }
}
