import 'dart:async';
import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
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

class ExitEngine extends PlaybackEngine {
  String? failedStep;
  String? pendingStep;
  int pauseCalls = 0;
  int shutdownCalls = 0;
  final loading = Completer<void>();
  final pending = Completer<void>();

  @override
  VideoController? get videoController => null;
  @override
  Widget buildSurface() => const SizedBox.shrink();
  @override
  double get position => 42;
  @override
  double get duration => 100;
  @override
  bool get isPaused => false;
  @override
  double get speed => 1;
  @override
  double get volume => 100;
  @override
  bool get isLoading => false;
  @override
  bool get isBuffering => false;
  @override
  bool get completed => false;
  @override
  String? get errorMessage => null;
  @override
  double? get networkSpeed => null;
  @override
  List<BufferedRange> get bufferedRanges => const [];
  @override
  List<TrackInfo> get audioTracks => const [];
  @override
  List<TrackInfo> get subtitleTracks => const [];
  @override
  String? get currentAudioId => null;
  @override
  String? get currentSubtitleId => null;
  @override
  Future<void> load(
    PlaybackPayload payload, {
    required int cacheLimitMb,
    required bool tlsVerify,
  }) => loading.future;
  Future<void> _step(String name) async {
    if (failedStep == name) throw PlatformException(code: name);
    if (pendingStep == name) await pending.future;
  }

  @override
  Future<void> pause() {
    pauseCalls++;
    return _step('pause');
  }

  @override
  Future<void> shutdown() {
    shutdownCalls++;
    return _step('shutdown');
  }

  @override
  dynamic noSuchMethod(Invocation invocation) => super.noSuchMethod(invocation);
}

const payload = PlaybackPayload(
  itemId: 1,
  playUrl: 'https://media.invalid/video.mp4',
  headers: {},
  playToken: 'test',
  resumeMs: 0,
  progressIntervalMs: 60000,
  subtitles: [],
  title: 'Video',
  seriesTitle: '',
  playlist: [],
  nextItemId: 2,
  nextTitle: 'Next',
  currentIndex: 0,
  durationMs: 100000,
);

Future<AppController> openPlayer(
  WidgetTester tester,
  ExitEngine engine, {
  ValueChanged<int>? onRequestItem,
  bool failWindow = false,
  bool pendingWindow = false,
}) async {
  final directory = Directory.systemTemp.createTempSync('strmaction-exit-');
  final paths = AppPaths(directory.path);
  final app = AppController(
    paths: paths,
    configStore: ConfigStore(paths),
    logger: AppLogger(paths),
    options: const CliOptions(),
    initialConfig: const AppConfig(),
  );
  final messenger =
      TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger;
  const native = MethodChannel('strmaction/native');
  const window = MethodChannel('window_manager');
  final windowPending = Completer<void>();
  Future<dynamic> handleWindow(MethodCall call) async {
    if (failWindow) throw PlatformException(code: 'window');
    if (pendingWindow) await windowPending.future;
    return null;
  }

  messenger.setMockMethodCallHandler(native, handleWindow);
  messenger.setMockMethodCallHandler(window, (call) async {
    if (call.method == 'isFullScreen') return true;
    return handleWindow(call);
  });
  messenger.setMockMethodCallHandler(SystemChannels.platform, (call) async {
    if (call.method == 'SystemChrome.setEnabledSystemUIMode') {
      return handleWindow(call);
    }
    return null;
  });
  addTearDown(() async {
    if (!engine.pending.isCompleted) engine.pending.complete();
    if (!windowPending.isCompleted) windowPending.complete();
    await tester.pumpWidget(const SizedBox.shrink());
    await tester.pump();
    await app.shutdown();
    app.dispose();
    messenger.setMockMethodCallHandler(native, null);
    messenger.setMockMethodCallHandler(window, null);
    messenger.setMockMethodCallHandler(SystemChannels.platform, null);
    directory.deleteSync(recursive: true);
  });
  await tester.pumpWidget(
    MaterialApp(
      home: Builder(
        builder: (context) => Scaffold(
          body: TextButton(
            onPressed: () => Navigator.of(context).push(
              PageRouteBuilder<void>(
                transitionDuration: Duration.zero,
                reverseTransitionDuration: Duration.zero,
                pageBuilder: (_, animation, secondaryAnimation) => PlayerPage(
                  app: app,
                  engine: engine,
                  payload: payload,
                  onRequestItem: onRequestItem,
                ),
              ),
            ),
            child: const Text('Library'),
          ),
        ),
      ),
    ),
  );
  await tester.tap(find.text('Library'));
  await tester.pump();
  await tester.pump();
  return app;
}

Future<void> tapBack(WidgetTester tester) async {
  // Exercise the actual top-left hit target, not just its callback.
  final topBar = find.byKey(const ValueKey('player-top-bar'));
  await tester.tap(
    find.descendant(of: topBar, matching: find.byType(InkWell)).first,
  );
  await tester.pump();
}

void expectLibrary(WidgetTester tester, ExitEngine engine) {
  expect(find.byType(PlayerPage), findsNothing);
  expect(find.text('Library'), findsOneWidget);
  expect(engine.pauseCalls, 1);
  expect(engine.shutdownCalls, 1);
  expect(tester.takeException(), isNull);
}

void main() {
  for (final platform in [
    TargetPlatform.android,
    TargetPlatform.iOS,
    TargetPlatform.windows,
    TargetPlatform.macOS,
  ]) {
    final variant = TargetPlatformVariant({platform});
    testWidgets('$platform top-left exits and ignores a late load completion', (
      tester,
    ) async {
      final engine = ExitEngine();
      final app = await openPlayer(tester, engine);
      await tapBack(tester);
      await tester.pumpAndSettle();
      expectLibrary(tester, engine);
      engine.loading.complete();
      await tester.pump();
      expect(app.activeProgress, isNull);
      expect(tester.takeException(), isNull);
    }, variant: variant);

    for (final step in ['pause', 'shutdown', 'window']) {
      testWidgets('$platform exits when $step throws', (tester) async {
        final engine = ExitEngine()..failedStep = step;
        await openPlayer(tester, engine, failWindow: step == 'window');
        await tapBack(tester);
        await tester.pumpAndSettle();
        expectLibrary(tester, engine);
      }, variant: variant);

      testWidgets('$platform bounds a stuck $step and ignores repeated exits', (
        tester,
      ) async {
        final engine = ExitEngine()..pendingStep = step;
        await openPlayer(tester, engine, pendingWindow: step == 'window');
        await tapBack(tester);
        await tapBack(tester);
        await tester.pump(const Duration(seconds: 4));
        await tester.pumpAndSettle();
        expectLibrary(tester, engine);
      }, variant: variant);
    }

    testWidgets('$platform episode changes still close after cleanup failure', (
      tester,
    ) async {
      final engine = ExitEngine()..failedStep = 'shutdown';
      final requested = <int>[];
      await openPlayer(tester, engine, onRequestItem: requested.add);
      tester.widget<ControlsOverlay>(find.byType(ControlsOverlay)).onNext();
      await tester.pumpAndSettle();
      expectLibrary(tester, engine);
      expect(requested, [2]);
    }, variant: variant);

    testWidgets('$platform system back uses the same exit cleanup', (
      tester,
    ) async {
      final engine = ExitEngine()..failedStep = 'pause';
      await openPlayer(tester, engine);
      await tester.binding.handlePopRoute();
      await tester.pumpAndSettle();
      expectLibrary(tester, engine);
    }, variant: variant);
  }
}
