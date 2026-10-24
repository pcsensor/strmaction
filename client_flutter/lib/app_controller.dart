import 'dart:async';
import 'dart:io';

import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart';

import 'core/app_logger.dart';
import 'core/app_paths.dart';
import 'core/cli_options.dart';
import 'core/config.dart';
import 'core/version.dart';
import 'services/progress_reporter.dart';
import 'services/progress_outbox.dart';

class AppController {
  String? accountKey;
  final AppPaths paths;
  final ConfigStore configStore;
  final AppLogger logger;
  final CliOptions options;
  final ValueNotifier<AppConfig> configNotifier;
  final ValueNotifier<String> lastErrorNotifier;

  ProgressReporter? activeProgress;
  Future<void> Function()? _playbackShutdown;
  bool _shutDown = false;

  AppController({
    required this.paths,
    required this.configStore,
    required this.logger,
    required this.options,
    required AppConfig initialConfig,
  })  : configNotifier = ValueNotifier(initialConfig),
        lastErrorNotifier = ValueNotifier('');

  AppConfig get config => configNotifier.value;

  String get lastError => lastErrorNotifier.value;

  static Future<AppController> create(CliOptions options) async {
    final paths = await AppPaths.forPlatform();
    paths.ensureDirectories();
    final logger = AppLogger(paths, debugEnabled: options.debug);
    await logger.initialize();
    final store = ConfigStore(paths);
    AppConfig config;
    try {
      config = await store.load();
      if (Platform.isAndroid && !await File(paths.configFile).exists()) { config = config.copyWith(cacheLimitMb: 512); }
      if (!config.isConfigured && (Platform.isAndroid || Platform.isIOS)) {
        final legacy = await const MethodChannel('strmaction/native')
            .invokeMapMethod<String, dynamic>('legacySettings');
        if (legacy != null && '${legacy['server_url'] ?? ''}'.isNotEmpty) {
          config = AppConfig.fromJson(Map<String, dynamic>.from(legacy));
          await store.save(config);
        }
      }
    } on Object catch (error) {
      logger.warning('配置读取失败，使用默认配置：$error');
      config = const AppConfig();
    }
    try { await ProgressOutbox('${paths.baseDir}/progress-outbox.json').replay(config.trustedCaPem); }
    on Object catch (error) { logger.warning('进度队列恢复失败：$error'); }
    return AppController(
      paths: paths,
      configStore: store,
      logger: logger,
      options: options,
      initialConfig: config,
    );
  }

  Future<bool> saveSettings(AppConfig next) async {
    final previousServer = config.serverUrl;
    final normalized = next.normalized();
    await configStore.save(normalized);
    configNotifier.value = normalized;
    logger.info('客户端设置已保存，服务器=${normalized.serverUrl}');
    return normalized.serverUrl != previousServer;
  }

  Future<void> persistWindowSize(int width, int height) async {
    final next = config.copyWith(windowWidth: width, windowHeight: height);
    if (next.windowWidth == config.windowWidth &&
        next.windowHeight == config.windowHeight) {
      return;
    }
    await saveSettings(next);
  }

  void setLastError(String message) {
    lastErrorNotifier.value = message;
  }

  void setPlaybackShutdown(Future<void> Function()? callback) {
    _playbackShutdown = callback;
  }

  Future<void> shutdown() async {
    if (_shutDown) return;
    _shutDown = true;
    try {
      if (_playbackShutdown != null) { await _playbackShutdown!(); }
      else { await activeProgress?.stop(flush: true); }
    } on Object {
      // best effort
    }
    activeProgress = null;
    try {
      await _playbackShutdown?.call();
    } on Object {
      // best effort
    }
    _playbackShutdown = null;
    await logger.close();
  }

  void dispose() {
    configNotifier.dispose();
    lastErrorNotifier.dispose();
  }

  String get version => appVersion;
}
