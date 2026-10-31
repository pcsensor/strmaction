import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:strmaction_desktop/app_controller.dart';
import 'package:strmaction_desktop/core/app_logger.dart';
import 'package:strmaction_desktop/core/app_paths.dart';
import 'package:strmaction_desktop/core/cli_options.dart';
import 'package:strmaction_desktop/core/config.dart';
import 'package:strmaction_desktop/models/playback_payload.dart';
import 'package:strmaction_desktop/player/widgets/buffered_seekbar.dart';
import 'package:strmaction_desktop/player/widgets/controls_overlay.dart';

void main() {
  group('config', () {
    test('concurrent settings changes are serialized against the latest values', () async {
      final root = await Directory.systemTemp.createTemp('settings-race-');
      final paths = AppPaths(root.path);
      paths.ensureDirectories();
      final logger = AppLogger(paths);
      await logger.initialize();
      final store = ConfigStore(paths);
      final app = AppController(paths: paths, configStore: store, logger: logger,
        options: CliOptions.parse([]), initialConfig: const AppConfig());
      await Future.wait([
        app.updateSettings((c) => c.copyWith(boostSpeed: 3)),
        app.updateSettings((c) => c.copyWith(videoScale: 'crop')),
        app.updateSettings((c) => c.copyWith(boostSpeed: 2)),
      ]);
      final saved = await store.load();
      expect(saved.boostSpeed, 2);
      expect(saved.videoScale, 'crop');
      await app.shutdown();
      app.dispose();
      await root.delete(recursive: true);
    });
    test('normalizes server url', () {
      expect(normalizeServerUrl(' https://media.example.com/ '),
          'https://media.example.com');
      expect(() => normalizeServerUrl('media.example.com'),
          throwsA(isA<ConfigException>()));
      expect(() => normalizeServerUrl('ftp://media.example.com'),
          throwsA(isA<ConfigException>()));
    });

    test('clamps cache and window values', () {
      final config = const AppConfig(
        serverUrl: 'https://media.example.com/',
        cacheLimitMb: 4,
        windowWidth: 10,
        windowHeight: 99999,
      ).normalized();
      expect(config.serverUrl, 'https://media.example.com');
      expect(config.cacheLimitMb, 16);
      expect(config.windowWidth, 900);
      expect(config.windowHeight, 2160);
    });

    test('keeps old config keys', () {
      final config = AppConfig.fromJson({
        'server_url': 'https://media.example.com',
        'cache_limit_mb': 0,
        'allow_self_signed_https': true,
        'window_width': 1280,
        'window_height': 820,
        'log_level': 'debug',
      });
      expect(config.cacheLimitMb, 0);
      // 旧版本的 allow_self_signed_https 已下线，导入时被忽略。
      expect(config.logLevel, 'DEBUG');
      expect(config.boostSpeed, defaultBoostSpeed);
      expect(config.customSpeed, isNull);
    });

    test('handles boost_speed and custom_speed with clamps', () {
      final config = const AppConfig(
        serverUrl: 'https://media.example.com',
        boostSpeed: 0.1,
        customSpeed: 10.0,
      ).normalized();
      expect(config.boostSpeed, 0.25);
      expect(config.customSpeed, 4.0);

      final fromJson = AppConfig.fromJson({
        'server_url': 'https://media.example.com',
        'boost_speed': 3.5,
        'custom_speed': 1.75,
      });
      expect(fromJson.boostSpeed, 3.5);
      expect(fromJson.customSpeed, 1.75);

      final json = fromJson.toJson();
      expect(json['boost_speed'], 3.5);
      expect(json['custom_speed'], 1.75);
    });
  });

  group('playback payload', () {
    Map<String, dynamic> payload() => {
          'item_id': 42,
          'play_url': 'https://cdn.example.com/video.mkv',
          'headers': {
            'User-Agent': 'pan.baidu.com',
            'Referer': 'https://pan.baidu.com/',
          },
          'play_token': 'pt_12345678',
          'resume_ms': 12000,
          'progress_interval_ms': 5000,
          'title': '第一集',
          'series_title': '测试剧',
          'duration_ms': 100000,
          'subtitles': [
            {'label': '简体', 'url': '/api/items/42/subtitles/0?pt=x'},
          ],
          'next_item_id': 43,
          'playlist': [
            {'item_id': 42, 'title': '第一集', 'code': 'S01E01', 'current': true},
            {'item_id': 43, 'title': '第二集', 'code': 'S01E02'},
          ],
          'current_index': 0,
        };

    test('parses and joins subtitle urls', () {
      final parsed =
          PlaybackPayload.fromJson(payload(), 'https://media.example.com');
      expect(parsed.itemId, 42);
      expect(parsed.resumeMs, 12000);
      expect(parsed.headers['User-Agent'], 'pan.baidu.com');
      expect(parsed.httpHeaderFields,
          'User-Agent: pan.baidu.com,Referer: https://pan.baidu.com/');
      expect(parsed.subtitles.single.url,
          'https://media.example.com/api/items/42/subtitles/0?pt=x');
      expect(parsed.nextItemId, 43);
      expect(parsed.playlist, hasLength(2));
    });

    test('keeps the full playlist and selected index beyond episode 200', () {
      final raw = payload()
        ..['playlist'] = List.generate(350, (index) => {'id': index + 1, 'title': 'Episode $index'})
        ..['current_index'] = 301;
      final parsed = PlaybackPayload.fromJson(raw, 'https://media.example.com');
      expect(parsed.playlist.length, 350);
      expect(parsed.currentIndex, 301);
      expect(parsed.playlist[parsed.currentIndex - 1].itemId, 301);
    });

    test('preserves explicit zero and inherited null cache budgets', () {
      final zero = PlaybackPayload.fromJson((payload()..['buffer_limit_mb'] = 0..['disk_cache_limit_mb'] = 0), 'https://media.example.com');
      expect(zero.bufferLimitMb, 0); expect(zero.diskCacheLimitMb, 0);
      final inherited = PlaybackPayload.fromJson(payload(), 'https://media.example.com');
      expect(inherited.bufferLimitMb, isNull); expect(inherited.diskCacheLimitMb, isNull);
    });

    test('rejects bad token and non-http url', () {
      final badToken = payload()..['play_token'] = 'bad token';
      expect(
        () => PlaybackPayload.fromJson(badToken, 'https://media.example.com'),
        throwsA(isA<PlaybackPayloadException>()),
      );
      final badUrl = payload()..['play_url'] = 'file:///tmp/a.mkv';
      expect(
        () => PlaybackPayload.fromJson(badUrl, 'https://media.example.com'),
        throwsA(isA<PlaybackPayloadException>()),
      );
    });

    test('drops header names that break mpv grammar', () {
      final parsed = PlaybackPayload.fromJson(
        payload()..['headers'] = {'Bad,Key': 'x', 'Good': 'y'},
        'https://media.example.com',
      );
      expect(parsed.httpHeaderFields, 'Good: y');
    });
  });

  test('formats playback times', () {
    expect(formatTime(0), '00:00');
    expect(formatTime(65), '01:05');
    expect(formatTime(3661), '01:01:01');
  });

  test('formats network speed', () {
    expect(formatNetworkSpeed(0), '↓ 0 B/s');
    expect(formatNetworkSpeed(1024), '↓ 1 KB/s');
    expect(formatNetworkSpeed(1024 * 1024), '↓ 1.0 MB/s');
  });
}
