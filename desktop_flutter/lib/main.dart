import 'dart:async';
import 'dart:io';

import 'package:flutter/material.dart';
import 'package:media_kit/media_kit.dart';
import 'package:screen_retriever/screen_retriever.dart';
import 'package:window_manager/window_manager.dart';

import 'app_controller.dart';
import 'core/cli_options.dart';
import 'core/config.dart';
import 'core/version.dart';
import 'web/web_shell_page.dart';

Future<void> main(List<String> args) async {
  WidgetsFlutterBinding.ensureInitialized();
  final options = CliOptions.parse(args);
  if (options.version) {
    stdout.writeln('StrmAction Desktop $appVersion');
    exit(0);
  }

  final app = await AppController.create(options);
  if (options.server != null && options.server!.trim().isNotEmpty) {
    try {
      final next = app.config.copyWith(
        serverUrl: normalizeServerUrl(options.server!),
      );
      await app.saveSettings(next);
    } on ConfigException catch (error) {
      stderr.writeln('服务器地址无效：${error.message}');
      await app.shutdown();
      exit(2);
    }
  }

  MediaKit.ensureInitialized();

  await windowManager.ensureInitialized();
  final config = app.config;
  // Never create a window taller/wider than the visible desktop, otherwise
  // the bottom playback controls can end up below the screen (especially on
  // Windows with display scaling).
  final display = await ScreenRetriever.instance.getPrimaryDisplay();
  final visible = display.visibleSize ?? display.size;
  final dpr = windowManager.getDevicePixelRatio();
  final reportedScale = display.scaleFactor?.toDouble() ?? 1.0;
  // On Windows the screen_retriever plugin can report physical pixels while
  // Flutter reports the real DPR. Normalize to logical pixels before clamping.
  final divide = Platform.isWindows && reportedScale < dpr ? dpr : 1.0;
  final availableWidth = visible.width / divide;
  final availableHeight = visible.height / divide;
  final width = config.windowWidth
      .clamp(900, (availableWidth - 40).clamp(900, 3840))
      .toDouble();
  final height = config.windowHeight
      .clamp(640, (availableHeight - 40).clamp(640, 2160))
      .toDouble();
  app.logger.info(
    '窗口初始化：display=${display.size.width}x${display.size.height} '
    'visible=${visible.width}x${visible.height} '
    'scale=$reportedScale dpr=$dpr target=${width}x$height',
  );
  final windowOptions = WindowOptions(
    size: Size(width, height),
    minimumSize: const Size(900, 640),
    center: true,
    title: 'StrmAction',
    backgroundColor: Colors.black,
    titleBarStyle: TitleBarStyle.normal,
    windowButtonVisibility: true,
  );

  await windowManager.setPreventClose(true);
  windowManager.addListener(_WindowListener(app));
  await windowManager.waitUntilReadyToShow(windowOptions, () async {
    // Apply the clamped size explicitly after the native window exists. Some
    // Windows/DPR combinations otherwise keep the pre-clamp size and put the
    // bottom playback controls below the visible client area.
    await windowManager.setSize(Size(width, height));
    await windowManager.center();
    await windowManager.show();
    await windowManager.focus();
  });

  runApp(StrmActionApp(app: app));
}

class StrmActionApp extends StatelessWidget {
  final AppController app;

  const StrmActionApp({super.key, required this.app});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      debugShowCheckedModeBanner: false,
      title: 'StrmAction',
      theme: ThemeData(
        brightness: Brightness.dark,
        colorScheme: const ColorScheme.dark(
          primary: Color(0xFFF0A94D),
          secondary: Color(0xFFE8B06A),
          surface: Color(0xFF0B0E13),
        ),
        scaffoldBackgroundColor: const Color(0xFF0B0E13),
        useMaterial3: true,
      ),
      home: WebShellPage(app: app),
    );
  }
}

class _WindowListener extends WindowListener {
  final AppController app;
  bool _closing = false;

  _WindowListener(this.app);

  @override
  void onWindowClose() {
    if (_closing) return;
    _closing = true;
    unawaited(_close());
  }

  Future<void> _close() async {
    try {
      final views = WidgetsBinding.instance.platformDispatcher.views;
      if (views.isNotEmpty) {
        final view = views.first;
        final size = view.physicalSize / view.devicePixelRatio;
        await app.persistWindowSize(size.width.round(), size.height.round());
      } else {
        final size = await windowManager.getSize();
        await app.persistWindowSize(size.width.round(), size.height.round());
      }
    } on Object {
      // ignore geometry errors during shutdown
    }
    await app.shutdown();
    app.dispose();
    await windowManager.destroy();
  }
}
