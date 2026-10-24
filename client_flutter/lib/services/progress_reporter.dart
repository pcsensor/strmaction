import 'dart:async';
import 'dart:convert';
import 'dart:io';

import '../core/app_logger.dart';
import '../core/version.dart';
import '../core/trust.dart';
import 'progress_outbox.dart';

const double finishedRatio = 0.9;

/// Port of the old Python `ProgressReporter`.
///
/// Uploads are single-flight and coalesced: only the latest position is sent,
/// and the high-frequency player position stream never drives the network.
class ProgressReporter {
  final String serverUrl;
  final int itemId;
  final String playToken;
  final int intervalMs;
  final bool verifySsl;
  final String trustedCaPem;
  final void Function()? onAuthError;
  final AppLogger? logger;
  final String? outboxPath;

  HttpClient? _client;
  Timer? _timer;
  bool _stopped = false;
  bool _closing = false;
  Future<bool>? _inFlight;
  bool _sending = false;
  bool _dirty = false;
  bool _finished = false;
  bool _authFailed = false;
  int _positionMs = 0;
  int? _durationMs;
  int _sequence = 0;
  final String _session;

  ProgressReporter({
    required this.serverUrl,
    required this.itemId,
    required this.playToken,
    required int intervalMs,
    required this.verifySsl,
    this.trustedCaPem = '',
    this.onAuthError,
    this.logger,
    this.outboxPath,
    String? sessionId,
  })  : _session = sessionId ?? _randomSession(),
        intervalMs = intervalMs.clamp(2000, 60000);

  String get url => '${serverUrl.replaceAll(RegExp(r'/+$'), '')}'
      '/api/items/$itemId/progress';

  void start() {
    if (_client != null) return;
    final client = HttpClient(context: trustContext(trustedCaPem))
      ..connectionTimeout = const Duration(seconds: 3);
    _client = client;
    _timer = Timer.periodic(
      Duration(milliseconds: intervalMs),
      (_) => unawaited(_send(force: false)),
    );
  }

  void update(int positionMs, {int? durationMs}) {
    if (_stopped || _closing) return;
    _positionMs = positionMs < 0 ? 0 : positionMs;
    if (durationMs != null) {
      _durationMs = durationMs < 0 ? 0 : durationMs;
    }
    _dirty = true;
  }

  void finish() {
    _finished = true;
    _dirty = true;
    unawaited(_send(force: true));
  }

  void requestFlush() {
    unawaited(_send(force: true));
  }

  Future<bool> flushOnce({bool force = false}) async {
    final pending = _inFlight;
    if (pending != null) await pending;
    return _send(force: force);
  }

  Future<bool> _send({required bool force}) {
    if (_inFlight != null) return _inFlight!;
    final sending = _sendSnapshot(force: force);
    _inFlight = sending.whenComplete(() => _inFlight = null);
    return _inFlight!;
  }

  Future<bool> _sendSnapshot({required bool force}) async {
    if (_stopped || _authFailed || _sending) return false;
    if (!_dirty && !force) return false;
    final client = _client;
    if (client == null) return false;

    _sending = true;
    _dirty = false;
    final payload = _payload();
    try {
      if (outboxPath != null) await ProgressOutbox(outboxPath!).save(url, playToken, payload);
      final request = await client.postUrl(Uri.parse(url)).timeout(
            const Duration(seconds: 5),
          );
      request.headers.contentType = ContentType.json;
      request.headers.set(
        HttpHeaders.authorizationHeader,
        'Bearer $playToken',
      );
      request.headers.set(
        HttpHeaders.userAgentHeader,
        'StrmActionDesktop/$appVersion',
      );
      final body = utf8.encode(jsonEncode(payload));
      request.contentLength = body.length;
      request.add(body);
      final response = await request.close().timeout(
            const Duration(seconds: 5),
          );
      await response.drain<void>().timeout(const Duration(seconds: 5));
      if (response.statusCode == 401 || response.statusCode == 403) {
        _authFailed = true;
        _timer?.cancel();
        logger?.warning('进度上报鉴权失败（${response.statusCode}），停止上报');
        if (outboxPath != null) await ProgressOutbox(outboxPath!).acknowledge(url, payload['client_key'] as String);
        onAuthError?.call();
        return false;
      }
      if (response.statusCode >= 400) {
        logger?.warning('进度上报失败：HTTP ${response.statusCode}');
        _dirty = true;
        return false;
      }
      if (outboxPath != null) await ProgressOutbox(outboxPath!).acknowledge(url, payload['client_key'] as String);
      return true;
    } on TimeoutException {
      logger?.warning('进度上报超时');
      _dirty = true;
      return false;
    } on Object catch (error) {
      logger?.warning('进度上报网络错误：$error');
      _dirty = true;
      return false;
    } finally {
      _sending = false;
    }
  }

  Map<String, dynamic> _payload() {
    var position = _positionMs;
    var finished = _finished;
    final duration = _durationMs;
    if (duration != null && duration > 0) {
      if (position > duration) position = duration;
      if (position / duration >= finishedRatio) finished = true;
    }
    if (finished) position = 0;
    _sequence += 1;
    return {
      'position_ms': position,
      'duration_ms': duration,
      'finished': finished,
      'client_key': 'desktop-$_session-$_sequence',
    };
  }

  Future<void> stop({bool flush = true}) async {
    if (_closing) return;
    _closing = true;
    _timer?.cancel();
    _timer = null;
    if (flush && !_authFailed) {
      try {
        await flushOnce(force: true).timeout(const Duration(seconds: 12));
      } on Object {
        // Best effort on shutdown.
      }
    }
    _stopped = true;
    _client?.close(force: true);
    _client = null;
  }

  static String _randomSession() {
    final now = DateTime.now().microsecondsSinceEpoch;
    return now.toRadixString(16).padLeft(12, '0').substring(0, 12);
  }
}
