import 'dart:async';
import 'dart:io';

import 'package:flutter/foundation.dart';
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
import 'package:strmaction_desktop/player/widgets/player_drawer.dart';

class FakeEngine extends PlaybackEngine {
  bool paused = false;
  int nativeTaps = 0;
  final loading = Completer<void>();
  @override VideoController? get videoController => null;
  @override double get position => 10;
  @override double get duration => 100;
  @override bool get isPaused => paused;
  @override double get speed => 1;
  @override double get volume => 100;
  @override bool get isLoading => false;
  @override bool get isBuffering => false;
  @override bool get completed => false;
  @override String? get errorMessage => null;
  @override double? get networkSpeed => null;
  @override List<BufferedRange> get bufferedRanges => const [];
  @override List<TrackInfo> get audioTracks => const [];
  @override List<TrackInfo> get subtitleTracks => const [];
  @override String? get currentAudioId => null;
  @override String? get currentSubtitleId => null;
  @override Future<void> load(PlaybackPayload payload, {required int cacheLimitMb, required bool tlsVerify}) {
    notifyListeners();
    // Keep networking out of the input tests; player state still arrives normally.
    return loading.future;
  }
  @override Future<void> setPaused(bool value) async { paused = value; notifyListeners(); }
  @override Future<void> play() => setPaused(false);
  @override Future<void> pause() => setPaused(true);
  @override Future<void> shutdown() async {}
  @override Widget buildVideo() => GestureDetector(
    behavior: HitTestBehavior.opaque, onTap: () => nativeTaps++,
    child: const ColoredBox(color: Colors.black),
  );
  @override dynamic noSuchMethod(Invocation invocation) => super.noSuchMethod(invocation);
}

Future<FakeEngine> mountPlayer(WidgetTester tester, TargetPlatform platform) async {
  debugDefaultTargetPlatformOverride = platform;
  addTearDown(() => debugDefaultTargetPlatformOverride = null);
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
    testWidgets('$platform taps show and hide controls without reaching native video', (tester) async {
      final engine = await mountPlayer(tester, platform);
      expect(controlsVisible(tester), isTrue);
      expect(tester.getRect(find.byKey(const ValueKey('player-viewport'))), const Rect.fromLTWH(0, 0, 393, 852));
      await tapScreen(tester);
      expect(controlsVisible(tester), isFalse);
      await tapScreen(tester);
      expect(controlsVisible(tester), isTrue);
      expect(engine.nativeTaps, 0);
      expect(tester.takeException(), isNull);
    });

    testWidgets('$platform auto hides after starting and allows hiding while paused', (tester) async {
      final engine = await mountPlayer(tester, platform);
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
    });

    testWidgets('$platform control buttons and drawer taps do not toggle the screen', (tester) async {
      await mountPlayer(tester, platform);
      await tester.tap(find.text('1x'));
      await tester.pump(const Duration(milliseconds: 300));
      expect(tester.widget<PlayerDrawer>(find.byType(PlayerDrawer)).visible, isTrue);
      expect(controlsVisible(tester), isTrue);
      await tester.tapAt(const Offset(20, 400));
      await tester.pump(const Duration(milliseconds: 350));
      expect(tester.widget<PlayerDrawer>(find.byType(PlayerDrawer)).visible, isFalse);
      expect(controlsVisible(tester), isTrue);
      expect(tester.takeException(), isNull);
    });

    testWidgets('$platform double tap pauses and lock keeps unlock accessible', (tester) async {
      final engine = await mountPlayer(tester, platform);
      await tester.tapAt(const Offset(196, 400));
      await tester.pump(const Duration(milliseconds: 50));
      await tester.tapAt(const Offset(196, 400));
      await tester.pump(const Duration(milliseconds: 350));
      expect(engine.paused, isTrue);
      expect(controlsVisible(tester), isTrue);
      await tester.tap(find.byTooltip('锁定'));
      await tester.pump(const Duration(milliseconds: 200));
      expect(controlsVisible(tester), isFalse);
      await tapScreen(tester);
      expect(controlsVisible(tester), isFalse);
      await tester.tap(find.byTooltip('解锁'));
      await tester.pump(const Duration(milliseconds: 200));
      expect(controlsVisible(tester), isTrue);
      expect(engine.nativeTaps, 0);
      expect(tester.takeException(), isNull);
    });
  }
}
