import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart';

import 'core/app_logger.dart';
import 'core/app_paths.dart';
import 'core/cli_options.dart';
import 'core/config.dart';
import 'core/version.dart';
import 'services/progress_reporter.dart';

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
  Future<void> _configTail = Future<void>.value();

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
    return AppController(
      paths: paths,
      configStore: store,
      logger: logger,
      options: options,
      initialConfig: config,
    );
  }

  Future<bool> saveSettings(AppConfig next) {
    final before = config.toJson();
    final desired = next.normalized().toJson();
    final changed = {...before.keys, ...desired.keys}.where(
      (key) => jsonEncode(before[key]) != jsonEncode(desired[key]),
    ).toList();
    return updateSettings((current) {
      final merged = current.toJson();
      for (final key in changed) {
        if (desired.containsKey(key)) { merged[key] = desired[key]; }
        else { merged.remove(key); }
      }
      return AppConfig.fromJson(merged);
    });
  }

  Future<bool> updateSettings(AppConfig Function(AppConfig) update) {
    final result = _configTail.then((_) async {
      final previousServer = config.serverUrl;
      final normalized = update(config).normalized();
      await configStore.save(normalized);
      configNotifier.value = normalized;
      logger.info('客户端设置已保存，服务器=${normalized.serverUrl}');
      return normalized.serverUrl != previousServer;
    });
    _configTail = result.then<void>((_) {}, onError: (Object _, StackTrace stack) {});
    return result;
  }

  Future<void> persistWindowSize(int width, int height) async {
    await updateSettings((current) => current.copyWith(windowWidth: width, windowHeight: height));
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
    await _configTail;
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
