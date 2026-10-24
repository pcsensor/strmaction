import 'dart:convert';
import 'dart:io';

import 'app_paths.dart';

const int defaultWidth = 1280;
const int defaultHeight = 820;
const int minWidth = 900;
const int minHeight = 640;
const int defaultCacheLimitMb = 128;
const int minActiveCacheLimitMb = 16;
const int maxCacheLimitMb = 2048;
const double defaultBoostSpeed = 2.0;
const double minPlaybackSpeed = 0.25;
const double maxPlaybackSpeed = 4.0;

class ConfigException implements Exception {
  final String message;
  const ConfigException(this.message);

  @override
  String toString() => message;
}

class AppConfig {
  final String serverUrl;
  final int cacheLimitMb;
  final bool allowSelfSignedHttps;
  final int windowWidth;
  final int windowHeight;
  final String logLevel;

  /// Whether media_kit should render through ANGLE/DXGI (GPU surface texture).
  ///
  /// The GPU path shares ANGLE with the Flutter engine inside the same process
  /// and registers/unregisters external textures from media_kit's worker
  /// thread; on some driver/GPU combinations that races the engine's raster
  /// thread and kills the process with an access violation in
  /// `GrDirectContext::flush`. Software rendering avoids that path entirely
  /// (it is capped at 1080p), so it is the default.
  final bool playerHardwareAcceleration;

  /// Speed multiplier applied during long-press boost (right arrow key hold).
  final double boostSpeed;

  /// User-configured custom playback speed (if set).
  final double? customSpeed;

  const AppConfig({
    this.serverUrl = '',
    this.cacheLimitMb = defaultCacheLimitMb,
    this.allowSelfSignedHttps = false,
    this.windowWidth = defaultWidth,
    this.windowHeight = defaultHeight,
    this.logLevel = 'INFO',
    this.playerHardwareAcceleration = false,
    this.boostSpeed = defaultBoostSpeed,
    this.customSpeed,
  });

  bool get isConfigured => serverUrl.isNotEmpty;

  AppConfig copyWith({
    String? serverUrl,
    int? cacheLimitMb,
    bool? allowSelfSignedHttps,
    int? windowWidth,
    int? windowHeight,
    String? logLevel,
    bool? playerHardwareAcceleration,
    double? boostSpeed,
    double? customSpeed,
  }) {
    return AppConfig(
      serverUrl: serverUrl ?? this.serverUrl,
      cacheLimitMb: cacheLimitMb ?? this.cacheLimitMb,
      allowSelfSignedHttps:
          allowSelfSignedHttps ?? this.allowSelfSignedHttps,
      windowWidth: windowWidth ?? this.windowWidth,
      windowHeight: windowHeight ?? this.windowHeight,
      logLevel: logLevel ?? this.logLevel,
      playerHardwareAcceleration:
          playerHardwareAcceleration ?? this.playerHardwareAcceleration,
      boostSpeed: boostSpeed ?? this.boostSpeed,
      customSpeed: customSpeed ?? this.customSpeed,
    );
  }

  AppConfig normalized() {
    return AppConfig(
      serverUrl:
          serverUrl.trim().isEmpty ? '' : normalizeServerUrl(serverUrl),
      cacheLimitMb: normalizeCacheLimit(cacheLimitMb),
      allowSelfSignedHttps: allowSelfSignedHttps,
      windowWidth: _clamp(windowWidth, minWidth, 3840, defaultWidth),
      windowHeight: _clamp(windowHeight, minHeight, 2160, defaultHeight),
      logLevel: (logLevel.isEmpty ? 'INFO' : logLevel).toUpperCase(),
      playerHardwareAcceleration: playerHardwareAcceleration,
      boostSpeed: _clampDouble(boostSpeed, minPlaybackSpeed, maxPlaybackSpeed, defaultBoostSpeed),
      customSpeed: customSpeed == null
          ? null
          : _clampDouble(customSpeed!, minPlaybackSpeed, maxPlaybackSpeed, 1.0),
    );
  }

  Map<String, dynamic> toJson() => {
        'server_url': serverUrl,
        'cache_limit_mb': cacheLimitMb,
        'allow_self_signed_https': allowSelfSignedHttps,
        'window_width': windowWidth,
        'window_height': windowHeight,
        'log_level': logLevel,
        'player_hardware_acceleration': playerHardwareAcceleration,
        'boost_speed': boostSpeed,
        if (customSpeed != null) 'custom_speed': customSpeed,
      };

  factory AppConfig.fromJson(Map<String, dynamic> json) {
    return AppConfig(
      serverUrl: (json['server_url'] ?? '').toString(),
      cacheLimitMb: _asInt(json['cache_limit_mb'], defaultCacheLimitMb),
      allowSelfSignedHttps: json['allow_self_signed_https'] == true,
      windowWidth: _asInt(json['window_width'], defaultWidth),
      windowHeight: _asInt(json['window_height'], defaultHeight),
      logLevel: (json['log_level'] ?? 'INFO').toString(),
      playerHardwareAcceleration: json['player_hardware_acceleration'] == true,
      boostSpeed: _asDouble(json['boost_speed'], defaultBoostSpeed),
      customSpeed: _asDoubleNullable(json['custom_speed']),
    ).normalized();
  }

  static double _asDouble(dynamic value, double fallback) {
    if (value is double) return value;
    if (value is num) return value.toDouble();
    return double.tryParse('$value') ?? fallback;
  }

  static double? _asDoubleNullable(dynamic value) {
    if (value == null) return null;
    if (value is double) return value;
    if (value is num) return value.toDouble();
    return double.tryParse('$value');
  }

  static double _clampDouble(double value, double low, double high, double fallback) {
    if (value.isNaN || value.isInfinite) return fallback;
    if (value < low) return low;
    if (value > high) return high;
    return value;
  }

  static int _asInt(dynamic value, int fallback) {
    if (value is int) return value;
    if (value is num) return value.toInt();
    return int.tryParse('$value') ?? fallback;
  }

  static int _clamp(int value, int low, int high, int fallback) {
    if (value < low) return low;
    if (value > high) return high;
    return value == 0 ? fallback : value;
  }
}

String normalizeServerUrl(String raw) {
  final value = raw.trim().replaceAll(RegExp(r'/+$'), '');
  if (value.isEmpty) {
    throw const ConfigException('服务器地址不能为空');
  }
  final uri = Uri.tryParse(value);
  if (uri == null ||
      !uri.hasScheme ||
      !(uri.scheme == 'http' || uri.scheme == 'https') ||
      uri.host.isEmpty) {
    throw const ConfigException('服务器地址必须以 http:// 或 https:// 开头');
  }
  if (uri.userInfo.isNotEmpty) {
    throw const ConfigException('服务器地址不能包含用户名或密码');
  }
  return value;
}

int normalizeCacheLimit(int value) {
  if (value <= 0) return 0;
  return value.clamp(minActiveCacheLimitMb, maxCacheLimitMb);
}

class ConfigStore {
  final AppPaths paths;

  const ConfigStore(this.paths);

  Future<AppConfig> load() async {
    final file = File(paths.configFile);
    if (!await file.exists()) {
      return const AppConfig();
    }
    try {
      final raw = await file.readAsString();
      final decoded = jsonDecode(raw);
      if (decoded is! Map<String, dynamic>) {
        throw const ConfigException('配置文件格式不正确');
      }
      return AppConfig.fromJson(decoded);
    } on ConfigException {
      rethrow;
    } on Object catch (error) {
      throw ConfigException('配置文件无法读取：$error');
    }
  }

  Future<void> save(AppConfig config) async {
    final normalized = config.normalized();
    final file = File(paths.configFile);
    await file.parent.create(recursive: true);
    final tmp = File('${file.path}.tmp');
    await tmp.writeAsString(
      const JsonEncoder.withIndent('  ').convert(normalized.toJson()),
      flush: true,
    );
    if (await file.exists()) {
      await file.delete();
    }
    await tmp.rename(file.path);
  }
}
