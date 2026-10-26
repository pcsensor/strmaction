import 'dart:async';
import 'dart:io';
import 'dart:math';

import '../core/trust.dart';
import 'download_policy.dart';

/// A playback cache with exactly one sequential origin stream.
///
/// The decoder reads through a loopback HTTP server. Cached blocks are served
/// from disk immediately. A miss near the playhead restarts the single origin
/// stream at the missing byte; a miss far away (header, tail moov, format
/// probe) uses one short probe request instead. The stream pauses when it is
/// far enough ahead of the playhead, keeping the origin connection open and
/// letting TCP apply backpressure instead of opening more connections.
///
/// This replaces the previous parallel segment scheduler: connections to a
/// cloud-drive CDN are expensive (5-15s) and cannot be aborted once queued in
/// Dart's HttpClient. Serialising them removes both the holes left by timed
/// out segments and the connection-pool starvation those retries caused.
class SequentialMediaCache {
  static const blockSize = 1024 * 1024;
  static const probeBytes = 4 * 1024 * 1024;
  static const probeDistance = 8 * 1024 * 1024;

  final HttpClient _client;
  final Uri _origin;
  final Map<String, String> _headers;
  final Directory _directory;
  final int budgetBytes;
  int prefetchBytes;
  final NetworkRate _rate = NetworkRate();
  final void Function(String)? onDiagnostic;
  final Duration connectTimeout;
  final Duration bodyStallTimeout;

  final Map<int, File> _blocks = {};
  final Map<int, int> _blockLengths = {};
  final Set<int> _reading = {};
  late final HttpServer _server;
  late final String _token;
  late final int length;
  late final String contentType;
  Uri? _resolved;
  String? _validator;
  int _linkVersion = 0;
  Future<void>? _resolving;
  int _bytes = 0;
  int _consumed = 0;
  int _demand = 0;
  int _generation = 0;
  bool _pendingSeek = false;
  int _connecting = 0;
  final List<Completer<void>> _connectQueue = [];
  bool _closed = false;
  bool _urgent = false;
  _Transfer? _stream;
  final List<_Transfer> _probes = [];

  SequentialMediaCache._(this._client, this._origin, this._headers,
      this._directory, this.budgetBytes, this.prefetchBytes,
      this.connectTimeout, this.bodyStallTimeout, this.onDiagnostic);

  Uri get localUrl => Uri.parse('http://127.0.0.1:${_server.port}/$_token');
  int get storedBytes => _bytes;
  int get activeDownloads =>
      ((_stream != null && !_stream!.cancelled && _stream!.phase != 'done')
          ? 1
          : 0) +
      _probes
          .where((probe) => !probe.cancelled && probe.phase != 'done')
          .length;
  bool get cacheReady =>
      _blocks.containsKey(_consumed ~/ blockSize) && activeDownloads == 0;
  double get networkSpeed => _rate.bytesPerSecond;
  List<(int, int)> get ranges => _blocks.keys
      .map((n) => (n * blockSize, n * blockSize + _blockLengths[n]!))
      .toList();

  /// True when the byte at [byteOffset] is already stored, so the playhead can
  /// be served from disk without waiting for the origin.
  bool covers(int byteOffset) {
    if (byteOffset < 0 || byteOffset >= length) return false;
    return (_blockLengths[byteOffset ~/ blockSize] ?? 0) > byteOffset % blockSize;
  }
  String get diagnosticState {
    String describe(_Transfer? t, String name) => t == null
        ? '$name=none'
        : '$name=[${t.start}-${t.end}:${t.phase}:${t.received}:'
            '${t.idle.elapsedMilliseconds}ms${t.paused ? ':paused' : ''}]';
    return 'consumed=$_consumed stored=$_bytes '
        '${describe(_stream, 'stream')} '
        'probes=[${_probes.map((probe) => describe(probe, 'probe')).join(', ')}]';
  }

  static Future<SequentialMediaCache?> open({
    required String url,
    required Map<String, String> headers,
    required String trustedCaPem,
    required String directory,
    required int budgetBytes,
    int? prefetchBytes,
    Duration connectTimeout = const Duration(seconds: 25),
    Duration bodyStallTimeout = const Duration(seconds: 12),
    void Function(String)? onDiagnostic,
  }) async {
    if (budgetBytes <= 0 ||
        RegExp(r'\.(m3u8|mpd)$', caseSensitive: false)
            .hasMatch(Uri.parse(url).path)) {
      return null;
    }
    final client = HttpClient(context: trustContext(trustedCaPem))
      ..connectionTimeout = const Duration(seconds: 10)
      ..maxConnectionsPerHost = 4;
    final cache = SequentialMediaCache._(client, Uri.parse(url), headers,
        Directory(directory), budgetBytes, prefetchBytes ?? budgetBytes,
        connectTimeout, bodyStallTimeout, onDiagnostic);
    try {
      if (!await cache._resolve()) {
        client.close(force: true);
        return null;
      }
      if (budgetBytes < min(blockSize, cache.length)) {
        client.close(force: true);
        return null;
      }
      await cache._directory.create(recursive: true);
      cache._token = List.generate(
          24, (_) => Random.secure().nextInt(256).toRadixString(16).padLeft(2, '0')).join();
      cache._server = await HttpServer.bind(InternetAddress.loopbackIPv4, 0);
      cache._server.listen((request) => unawaited(cache._serve(request)),
          onError: (Object _) {});
      return cache;
    } on Object {
      client.close(force: true);
      rethrow;
    }
  }

  // ---------------------------------------------------------------- origin

  /// Bound connection attempts independently of the HttpClient pool. Repeated
  /// seeks abandon transfers whose getUrl is already queued; without this cap
  /// those abandoned attempts can still fill maxConnectionsPerHost.
  Future<void> _acquireConnect(_Transfer? transfer) async {
    while (_connecting >= 2) {
      if (_closed || transfer?.cancelled == true) throw const _Cancelled();
      final gate = Completer<void>();
      _connectQueue.add(gate);
      try {
        await gate.future.timeout(const Duration(seconds: 1));
      } on TimeoutException {
        _connectQueue.remove(gate);
      }
    }
    if (_closed || transfer?.cancelled == true) throw const _Cancelled();
    _connecting++;
  }

  void _releaseConnect() {
    if (_connecting > 0) _connecting--;
    while (_connectQueue.isNotEmpty) {
      final gate = _connectQueue.removeAt(0);
      if (!gate.isCompleted) {
        gate.complete();
        break;
      }
    }
  }

  Future<(HttpClientResponse, Uri)> _follow(
      _Transfer? transfer, Uri uri, int start, int end,
      {required bool openEnded}) async {
    for (var redirects = 0; redirects <= 5; redirects++) {
      transfer?.phase = 'connect';
      transfer?.touch();
      transfer?.notify();
      await _acquireConnect(transfer);
      var abandoned = false;
      final HttpClientRequest request;
      try {
        final opening = _client.getUrl(uri).then((request) {
          if (abandoned || _closed || transfer?.cancelled == true) {
            request.abort(const _Cancelled());
            throw const _Cancelled();
          }
          return request;
        });
        request = await opening.timeout(connectTimeout, onTimeout: () {
          abandoned = true;
          throw TimeoutException('媒体连接等待超时', connectTimeout);
        });
      } finally {
        _releaseConnect();
      }
      if (_closed || transfer?.cancelled == true) {
        request.abort();
        throw const _Cancelled();
      }
      transfer?.request = request;
      request.followRedirects = false;
      _headers.forEach((key, value) {
        if (!['host', 'range', 'connection', 'accept-encoding']
            .contains(key.toLowerCase())) {
          request.headers.set(key, value);
        }
      });
      request.headers.set(HttpHeaders.rangeHeader,
          openEnded ? 'bytes=$start-' : 'bytes=$start-${end - 1}');
      request.headers.set(HttpHeaders.acceptEncodingHeader, 'identity');
      if (_validator != null && transfer != null) {
        request.headers.set(HttpHeaders.ifRangeHeader, _validator!);
      }
      transfer?.phase = 'headers';
      transfer?.touch();
      transfer?.notify();
      final responding = request.close().then((response) async {
        if (abandoned || _closed || transfer?.cancelled == true) {
          await response.listen((_) {}).cancel();
          throw const _Cancelled();
        }
        return response;
      });
      final response = await responding.timeout(connectTimeout, onTimeout: () {
        abandoned = true;
        final error = TimeoutException('媒体响应头等待超时', connectTimeout);
        request.abort(error);
        throw error;
      });
      onDiagnostic?.call(
          '媒体响应 ${uri.host} HTTP ${response.statusCode} bytes=$start-$end');
      if (![301, 302, 303, 307, 308].contains(response.statusCode)) {
        return (response, uri);
      }
      final location = response.headers.value(HttpHeaders.locationHeader);
      await response.listen((_) {}).cancel();
      if (location == null) throw const HttpException('片源重定向缺少地址');
      uri = uri.resolve(location);
      if (!['http', 'https'].contains(uri.scheme)) {
        throw const HttpException('片源重定向协议无效');
      }
    }
    throw const HttpException('片源重定向次数过多');
  }

  Future<bool> _resolve({bool refresh = false}) async {
    final (probe, uri) = await _follow(null, _origin, 0, 1, openEnded: false);
    final match = RegExp(r'^bytes 0-0/(\d+)$')
        .firstMatch(probe.headers.value(HttpHeaders.contentRangeHeader) ?? '');
    final mime = probe.headers.contentType?.mimeType ?? '';
    final valid = probe.statusCode == 206 &&
        match != null &&
        int.parse(match[1]!) > 0 &&
        !mime.contains('mpegurl') &&
        !mime.contains('dash') &&
        !mime.startsWith('text/') &&
        !mime.contains('xml');
    if (!valid) {
      await probe.listen((_) {}).cancel();
      return false;
    }
    final total = int.parse(match[1]!);
    final etag = probe.headers.value(HttpHeaders.etagHeader);
    final validator = etag != null && !etag.startsWith('W/')
        ? etag
        : probe.headers.value(HttpHeaders.lastModifiedHeader);
    if (refresh &&
        (total != length || (_validator != null && validator != _validator))) {
      await probe.listen((_) {}).cancel();
      throw const HttpException('片源文件已变化，请重新播放');
    }
    var received = 0;
    await for (final bytes in probe.timeout(const Duration(seconds: 10))) {
      received += bytes.length;
      _rate.add(bytes.length);
      if (received > 1) throw const HttpException('片源范围读取不一致');
    }
    if (received != 1) throw const HttpException('片源范围读取不完整');
    if (!refresh) {
      length = total;
      contentType = mime.isEmpty ? 'application/octet-stream' : mime;
      _validator = validator;
    }
    _resolved = uri;
    _linkVersion++;
    return true;
  }

  Future<void> _refresh(int failedVersion) async {
    if (_resolving != null) {
      await _resolving;
      return;
    }
    if (_linkVersion != failedVersion) return;
    final future = () async {
      if (!await _resolve(refresh: true)) {
        throw const HttpException('直链已失效，重新取链失败');
      }
    }();
    _resolving = future;
    try {
      await future;
    } finally {
      _resolving = null;
    }
  }

  Future<HttpClientResponse> _request(
      _Transfer transfer, int start, int end) async {
    for (var attempt = 0; attempt < 2; attempt++) {
      final version = _linkVersion;
      final (response, finalUri) =
          await _follow(transfer, _resolved!, start, end, openEnded: !transfer.probe);
      if ([401, 403, 410].contains(response.statusCode) && attempt == 0) {
        await response.listen((_) {}).cancel();
        await _refresh(version);
        continue;
      }
      final match = RegExp(r'^bytes (\d+)-(\d+)/(\d+)$')
          .firstMatch(response.headers.value(HttpHeaders.contentRangeHeader) ?? '');
      final responseEnd = match == null ? -1 : int.parse(match[2]!);
      final valid = response.statusCode == 206 &&
          match != null &&
          int.parse(match[1]!) == start &&
          int.parse(match[3]!) == length &&
          responseEnd >= start &&
          (response.contentLength < 0 ||
              response.contentLength == responseEnd - start + 1);
      if (!valid) {
        await response.listen((_) {}).cancel();
        throw const HttpException('片源范围或文件身份不一致');
      }
      // The server may return a shorter range than open-ended EOF (edge
      // limits). Keep the response boundary so the next read resumes there.
      transfer.end = min(transfer.end, responseEnd + 1);
      if (_linkVersion == version) _resolved = finalUri;
      return response;
    }
    throw const HttpException('直链刷新失败');
  }

  // --------------------------------------------------------------- transfer

  _Transfer _startStream(int offset) {
    final current = _stream;
    if (current != null &&
        !current.cancelled &&
        current.phase != 'done' &&
        current.error == null &&
        current.coversOffset(offset)) {
      current.resume();
      return current;
    }
    current?.cancel();
    // The byte offset that triggered this stream is the best local estimate of
    // the playhead, even when the time-to-byte hint from the UI was off (VBR).
    if (offset > _consumed) _consumed = offset;
    final transfer = _Transfer(offset, length, false);
    _stream = transfer;
    unawaited(_run(transfer));
    return transfer;
  }

  _Transfer _startProbe(int number) {
    final start = number * blockSize + (_blockLengths[number] ?? 0);
    for (final probe in _probes) {
      if (!probe.cancelled &&
          probe.phase != 'done' &&
          probe.error == null &&
          probe.coversBlock(number)) {
        return probe;
      }
    }
    // The head and tail moov can be requested around the same time. Keep at
    // most two probes so they cannot cancel each other in a loop; beyond that,
    // drop the one farthest from the requested block.
    if (_probes.length >= 2) {
      final victim = _probes.reduce((a, b) =>
          (a.start - number * blockSize).abs() >
                  (b.start - number * blockSize).abs()
              ? a
              : b);
      victim.cancel();
      _probes.remove(victim);
    }
    final end = min(length, start + probeBytes);
    final transfer = _Transfer(start, end, true);
    _probes.add(transfer);
    unawaited(_run(transfer));
    return transfer;
  }

  Future<void> _run(_Transfer transfer) async {
    try {
      final response = await _request(transfer, transfer.start, transfer.end);
      transfer.phase = 'body';
      transfer.touch();
      transfer.notify();
      if (!transfer.probe) {
        _rate.reset();
      }
      transfer.body = StreamIterator(response.timeout(const Duration(seconds: 20)));
      while (await transfer.body!.moveNext()) {
        if (_closed || transfer.cancelled) throw const _Cancelled();
        final chunk = transfer.body!.current;
        _rate.add(chunk.length);
        transfer.touch();
        _publish(transfer, chunk);
        transfer.notify();
        if (!transfer.probe) await _pace(transfer);
      }
      if (_closed || transfer.cancelled) throw const _Cancelled();
      if (transfer.start + transfer.received < transfer.end) {
        onDiagnostic?.call('回源提前结束 '
            '${transfer.start + transfer.received}/${transfer.end}');
      }
    } on _Cancelled {
      // Expected on seek/close.
    } on Object catch (error) {
      transfer.error = error;
      if (!_closed && !transfer.cancelled) {
        onDiagnostic?.call('回源失败 ${transfer.start}-${transfer.end} '
            'phase=${transfer.phase} received=${transfer.received} '
            'error=${error.runtimeType}');
      }
    } finally {
      transfer.body = null;
      transfer.request = null;
      transfer.phase = 'done';
      if (transfer.probe) _probes.remove(transfer);
      transfer.notify();
    }
  }

  void _publish(_Transfer transfer, List<int> chunk) {
    var cursor = transfer.start + transfer.received;
    var offset = 0;
    while (offset < chunk.length) {
      final number = cursor ~/ blockSize;
      final local = cursor % blockSize;
      final count = min(chunk.length - offset, blockSize - local);
      final existing = _blockLengths[number] ?? 0;
      if (existing >= local + count) {
        // A probe already wrote this span; keep the stream moving.
      } else if (existing < local) {
        throw const HttpException('缓存区间不连续');
      } else {
        final from = offset + (existing - local);
        final add = local + count - existing;
        final file = _blocks[number] ?? File('${_directory.path}/$number.block');
        final handle = file.openSync(mode: FileMode.append);
        try {
          handle.writeFromSync(chunk, from, from + add);
        } finally {
          handle.closeSync();
        }
        _blocks[number] = file;
        _blockLengths[number] = local + count;
        _bytes += add;
      }
      cursor += count;
      offset += count;
    }
    transfer.received += chunk.length;
    _evict();
  }

  Future<void> _pace(_Transfer transfer) async {
    final window = prefetchBytes > 0 ? prefetchBytes : blockSize;
    var wasPaused = false;
    while (!_closed &&
        !transfer.cancelled &&
        !_urgent &&
        transfer.start + transfer.received - _consumed > window &&
        transfer.start + transfer.received >= _demand) {
      transfer.pause();
      wasPaused = true;
      await transfer.waitResume();
    }
    if (wasPaused && !transfer.cancelled) {
      _rate.reset();
    }
  }

  void _evict() {
    if (_bytes <= budgetBytes) return;
    final streamBlock = _stream == null
        ? _consumed ~/ blockSize
        : (_stream!.start + _stream!.received) ~/ blockSize;
    final candidates = _blocks.keys
        .where((n) => !_reading.contains(n))
        .toList()
      ..sort((a, b) => (b - streamBlock).abs().compareTo((a - streamBlock).abs()));
    for (final number in candidates) {
      if (_bytes <= budgetBytes) break;
      final removed = _blockLengths.remove(number);
      final file = _blocks.remove(number);
      if (removed != null) _bytes -= removed;
      try {
        if (file != null && file.existsSync()) file.deleteSync();
      } on FileSystemException {
        // Another reader may still hold the file; the block is already
        // unreachable from the index.
      }
    }
  }

  // ---------------------------------------------------------------- demand

  Future<List<int>> _block(int number, int begin, int generation) async {
    _reading.add(number);
    var attempts = 0;
    try {
      while (!_closed) {
        if (generation != _generation) throw const _Cancelled();
        final file = _blocks[number];
        if (file != null && (_blockLengths[number] ?? 0) > begin) {
          return file.readAsBytesSync();
        }
        _demand = max(_demand, (number + 1) * blockSize);
        final stream = _stream;
        if (stream != null &&
            !stream.cancelled &&
            stream.phase != 'done' &&
            stream.error == null &&
            stream.coversBlock(number)) {
          stream.resume();
          final window =
              stream.phase == 'body' ? bodyStallTimeout : connectTimeout;
          try {
            await stream.changed.timeout(window);
          } on TimeoutException {
            if (_closed) break;
            if ((_blockLengths[number] ?? 0) > begin) continue;
            onDiagnostic?.call(
                '主回源流停滞 offset=${number * blockSize + begin} '
                '$diagnosticState');
            stream.cancel();
            if (identical(_stream, stream)) _stream = null;
            if (++attempts > 2) {
              throw const HttpException('片源长时间无数据');
            }
          }
          continue;
        }
        _Transfer? probe;
        for (final candidate in _probes) {
          if (!candidate.cancelled &&
              candidate.phase != 'done' &&
              candidate.error == null &&
              candidate.coversBlock(number)) {
            probe = candidate;
            break;
          }
        }
        if (probe != null) {
          try {
            await probe.changed.timeout(connectTimeout);
          } on TimeoutException {
            if (_closed) break;
            if ((_blockLengths[number] ?? 0) > begin) continue;
            onDiagnostic?.call(
                '短探针停滞 offset=${number * blockSize + begin} '
                '$diagnosticState');
            probe.cancel();
            _probes.remove(probe);
            if (++attempts > 2) {
              throw const HttpException('片源长时间无数据');
            }
          }
          continue;
        }
        if (++attempts > 3) {
          throw const HttpException('当前播放分段持续无数据');
        }
        if (generation != _generation) throw const _Cancelled();
        final target = number * blockSize + (_blockLengths[number] ?? 0);
        final offset = number * blockSize;
        // The head and the tail moov are the only reads that justify a probe:
        // they are one-off, unrelated to the playhead, and must not disturb the
        // main stream. Everything else is a sequential read; using a probe
        // there costs one new CDN connection per 4 MiB and leaves the decoder
        // waiting for it. The byte hint can be far off on VBR files, so a
        // distance check alone cannot classify a playhead read.
        final edge = offset < probeBytes || offset >= length - probeBytes;
        if (_pendingSeek) {
          // The byte hint from seek() can be off on VBR files. The first
          // demand after an explicit seek is authoritative: stream from it.
          _pendingSeek = false;
          _startStream(target);
        } else if (!edge || (target - _consumed).abs() <= probeDistance) {
          _startStream(target);
        } else {
          _startProbe(number);
        }
      }
      throw const _Cancelled();
    } finally {
      _reading.remove(number);
    }
  }

  /// Called by the player as the playhead moves. Bytes are a hint for the
  /// prefetch window; they never cancel or restart an active stream.
  void setConsumed(int byteOffset) {
    _consumed = byteOffset.clamp(0, length - 1);
    _demand = max(_demand, _consumed + blockSize);
    final stream = _stream;
    if (stream != null &&
        stream.paused &&
        stream.start + stream.received - _consumed <= prefetchBytes) {
      stream.resume();
    }
  }

  /// Explicit user seeks only update the playhead. Cached targets are served
  /// without touching the origin; an uncached target restarts the single
  /// stream once, from the first missing byte.
  void seek(int byteOffset) {
    _consumed = byteOffset.clamp(0, length - 1);
    _demand = _consumed + blockSize;
    _pendingSeek = true;
    _generation++;
    // Wake stale local responses so they stop before starting a transfer for
    // the old position. The origin stream itself is not cancelled here; the
    // next demand restarts it only if the target is not cached.
    _stream?.notify();
    for (final probe in _probes) {
      probe.notify();
    }
  }

  void setPlaybackUrgent(bool value) {
    _urgent = value;
    if (value) _stream?.resume();
  }

  // ------------------------------------------------------------- local HTTP

  Future<void> _serve(HttpRequest request) async {
    final response = request.response;
    final generation = _generation;
    var sent = false;
    try {
      if (_closed || request.uri.path != '/$_token') {
        response.statusCode = 404;
        await response.close();
        return;
      }
      if (request.method != 'GET' && request.method != 'HEAD') {
        response.statusCode = 405;
        await response.close();
        return;
      }
      final raw = request.headers.value(HttpHeaders.rangeHeader);
      var start = 0;
      var end = length - 1;
      if (raw != null) {
        final match = RegExp(r'^bytes=(\d*)-(\d*)$').firstMatch(raw);
        if (match == null || (match[1]!.isEmpty && match[2]!.isEmpty)) {
          throw const FormatException('range');
        }
        if (match[1]!.isEmpty) {
          start = max(0, length - int.parse(match[2]!));
        } else {
          start = int.parse(match[1]!);
          if (match[2]!.isNotEmpty) end = min(end, int.parse(match[2]!));
        }
        if (start > end || start >= length) throw const FormatException('range');
      }
      response.statusCode = raw == null ? 200 : 206;
      response.headers.set(HttpHeaders.acceptRangesHeader, 'bytes');
      response.headers.set(HttpHeaders.contentTypeHeader, contentType);
      response.contentLength = end - start + 1;
      if (raw != null) {
        response.headers
            .set(HttpHeaders.contentRangeHeader, 'bytes $start-$end/$length');
      }
      if (request.method != 'HEAD') {
        for (var offset = start; offset <= end && !_closed;) {
          if (generation != _generation) throw const _Cancelled();
          final block =
              await _block(offset ~/ blockSize, offset % blockSize, generation);
          final begin = offset % blockSize;
          final take = min(block.length - begin, end - offset + 1);
          response.add(block.sublist(begin, begin + take));
          await response.flush();
          sent = true;
          offset += take;
        }
      }
      await response.close();
    } on FormatException {
      response.statusCode = 416;
      response.headers.set(HttpHeaders.contentRangeHeader, 'bytes */$length');
      await response.close();
    } on Object catch (error) {
      if (error is _Cancelled) {
        // The player seeked and this local response is stale. The new request
        // owns the next transfer; close without fabricating a media error.
        await _abort(response);
        return;
      }
      onDiagnostic?.call('本地响应中止 '
          'offset=${request.headers.value(HttpHeaders.rangeHeader)} '
          'sent=$sent error=${error.runtimeType}');
      if (!sent) {
        try {
          response.statusCode = 502;
          response.headers.removeAll(HttpHeaders.contentRangeHeader);
          response.headers.removeAll(HttpHeaders.acceptRangesHeader);
          response.contentLength = 0;
          await response.close();
          return;
        } on Object {
          // Headers already committed.
        }
      }
      await _abort(response);
    }
  }

  /// Ends a local response whose body is already partly written. Detaching is
  /// only legal before the headers are committed; after that the socket can
  /// only be released by closing, and an unhandled StateError here used to
  /// leave the client waiting on a response that never completed.
  Future<void> _abort(HttpResponse response) async {
    try {
      final socket = await response.detachSocket();
      socket.destroy();
      return;
    } on Object {
      // Headers were already sent.
    }
    try {
      await response.close();
    } on Object {
      // The client closed the connection first.
    }
  }

  Future<void> close() async {
    if (_closed) return;
    _closed = true;
    _stream?.cancel();
    for (final probe in _probes.toList()) {
      probe.cancel();
    }
    _probes.clear();
    _client.close(force: true);
    await _server.close(force: true);
    _blocks.clear();
    _blockLengths.clear();
    _bytes = 0;
    try {
      if (await _directory.exists()) await _directory.delete(recursive: true);
    } on FileSystemException {
      // A late writer may still own a file; the session directory is removed
      // by the next playback's load path.
    }
  }
}

class _Transfer {
  final int start;
  int end;
  final bool probe;
  int received = 0;
  bool cancelled = false;
  bool paused = false;
  String phase = 'queued';
  Object? error;
  HttpClientRequest? request;
  StreamIterator<List<int>>? body;
  final Stopwatch idle = Stopwatch()..start();
  Completer<void> _changed = Completer<void>();
  Completer<void>? _resume;

  _Transfer(this.start, this.end, this.probe);

  Future<void> get changed => _changed.future;

  void notify() {
    final before = _changed;
    _changed = Completer<void>();
    if (!before.isCompleted) before.complete();
  }

  void touch() => idle.reset();

  bool coversOffset(int offset) =>
      start <= offset && offset <= start + received + SequentialMediaCache.blockSize;

  bool coversBlock(int number) {
    final upper = probe
        ? end
        : start + received + SequentialMediaCache.blockSize;
    return (number + 1) * SequentialMediaCache.blockSize > start &&
        number * SequentialMediaCache.blockSize < upper;
  }

  void pause() => paused = true;

  void resume() {
    if (!paused) return;
    paused = false;
    final gate = _resume;
    _resume = null;
    if (gate != null && !gate.isCompleted) gate.complete();
  }

  Future<void> waitResume() {
    if (!paused) return Future.value();
    return (_resume ??= Completer<void>()).future;
  }

  void cancel() {
    if (cancelled) return;
    cancelled = true;
    request?.abort(const _Cancelled());
    final stream = body;
    if (stream != null) {
      unawaited(stream.cancel().then<void>((_) {}, onError: (Object _) {}));
    }
    resume();
    notify();
  }
}

class _Cancelled implements Exception {
  const _Cancelled();
}
