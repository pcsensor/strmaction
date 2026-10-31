import 'dart:async';
import 'dart:io';
import 'dart:math';

import '../core/trust.dart';
import 'download_policy.dart';
import 'media_redirect.dart';

/// A per-playback Range cache. Transport segments are 4–8 MiB; disk blocks stay
/// small. Reservations include in-flight segments, so parallel reads cannot
/// exceed the budget. A single resolver is shared by all segment workers.
class BoundedMediaCache {
  static const blockSize = 1024 * 1024;
  final HttpClient _client;
  final Uri _origin;
  final Map<String, String> _headers;
  final Directory _directory;
  final int budgetBytes;
  int prefetchBytes;
  final policy = DownloadPolicy();
  final _rate = NetworkRate();
  final Map<int, File> _blocks = {};
  final Map<int, int> _blockLengths = {};
  final Map<int, int> _readers = {};
  final Set<_Download> _jobs = {};
  Future<void>? _resolving;
  Uri? _resolved;
  int _linkVersion = 0;
  String? _validator;
  late final HttpServer _server;
  late final String _token;
  late final int length;
  late final String contentType;
  var _bytes = 0;
  var _generation = 0;
  var _focus = 0;
  int? _consumedBlock;
  var _closed = false;
  var _urgent = false;
  final Duration demandStallTimeout;
  final Duration requestTimeout;
  final void Function(String)? onDiagnostic;

  BoundedMediaCache._(this._client, this._origin, this._headers,
      this._directory, this.budgetBytes, this.prefetchBytes, this.demandStallTimeout,
      this.requestTimeout, this.onDiagnostic);

  Uri get localUrl => Uri.parse('http://127.0.0.1:${_server.port}/$_token');
  int get storedBytes => _bytes;
  int get reservedBytes => _jobs.fold(0, (sum, job) => sum + job.size - job.received);
  int get activeDownloads => _jobs.length;
  bool get cacheReady => _jobs.isEmpty && _blocks.containsKey(_focus);
  double get networkSpeed => _rate.bytesPerSecond;
  String get diagnosticState => 'focus=$_focus consumed=$_consumedBlock '
      'stored=$_bytes reserved=$reservedBytes generation=$_generation '
      'jobs=[${_jobs.map((job) => '${job.start}-${job.end}:${job.phase}:${job.received}:${job.idle.elapsedMilliseconds}ms').join(', ')}]';
  List<(int, int)> get ranges => _blocks.keys
      .map((n) => (n * blockSize, n * blockSize + _blockLengths[n]!)).toList();

  static Future<BoundedMediaCache?> open({required String url,
      required Map<String, String> headers, required String trustedCaPem,
      required String directory, required int budgetBytes, int? prefetchBytes,
      Duration demandStallTimeout = const Duration(seconds: 3),
      Duration requestTimeout = const Duration(seconds: 15),
      void Function(String)? onDiagnostic}) async {
    if (budgetBytes <= 0 || RegExp(r'\.(m3u8|mpd)$', caseSensitive: false).hasMatch(Uri.parse(url).path)) return null;
    final client = HttpClient(context: trustContext(trustedCaPem))
      ..connectionTimeout = const Duration(seconds: 10)
      ..maxConnectionsPerHost = 4;
    final cache = BoundedMediaCache._(client, Uri.parse(url), headers,
        Directory(directory), budgetBytes, prefetchBytes ?? budgetBytes, demandStallTimeout,
        requestTimeout, onDiagnostic);
    try {
      if (!await cache._resolve()) { client.close(force: true); return null; }
      if (budgetBytes < min(blockSize, cache.length)) { client.close(force: true); return null; }
      await cache._directory.create(recursive: true);
      cache._token = List.generate(24, (_) => Random.secure().nextInt(256)
          .toRadixString(16).padLeft(2, '0')).join();
      cache._server = await HttpServer.bind(InternetAddress.loopbackIPv4, 0);
      cache._server.listen((request) => unawaited(cache._serve(request)), onError: (Object _) {});
      return cache;
    } on Object { client.close(force: true); rethrow; }
  }

  Future<(HttpClientResponse, Uri)> _follow(Uri uri, int start, int end,
      {_Download? job}) async {
    for (var redirects = 0; redirects <= 5; redirects++) {
      job?.phase = 'connect';
      job?.touch();
      job?.notify();
      var abandoned = false;
      final opening = _client.getUrl(uri).then((request) {
        if (abandoned || _closed || job?.cancelled == true) {
          request.abort(const _Cancelled());
          throw const _Cancelled();
        }
        return request;
      });
      final request = await opening.timeout(requestTimeout, onTimeout: () {
        abandoned = true;
        throw TimeoutException('媒体连接等待超时', requestTimeout);
      });
      if (_closed || job?.cancelled == true) { request.abort(); throw const _Cancelled(); }
      job?.request = request;
      request.followRedirects = false;
      _headers.forEach((key, value) {
        if (!['host', 'range', 'connection', 'accept-encoding'].contains(key.toLowerCase()) && forwardMediaHeader(_origin, uri, key)) {
          request.headers.set(key, value);
        }
      });
      request.headers.set(HttpHeaders.rangeHeader, 'bytes=$start-$end');
      request.headers.set(HttpHeaders.acceptEncodingHeader, 'identity');
      if (_validator != null && job != null) request.headers.set(HttpHeaders.ifRangeHeader, _validator!);
      job?.phase = 'headers';
      job?.touch();
      job?.notify();
      final responding = request.close().then((response) async {
        if (abandoned || _closed || job?.cancelled == true) {
          await response.listen((_) {}).cancel();
          throw const _Cancelled();
        }
        return response;
      });
      final response = await responding.timeout(requestTimeout, onTimeout: () {
        abandoned = true;
        final error = TimeoutException('媒体响应头等待超时', requestTimeout);
        request.abort(error);
        throw error;
      });
      onDiagnostic?.call('媒体响应 ${uri.host} HTTP ${response.statusCode} bytes=$start-$end');
      if (![301, 302, 303, 307, 308].contains(response.statusCode)) return (response, uri);
      final location = response.headers.value(HttpHeaders.locationHeader);
      await response.listen((_) {}).cancel();
      if (location == null) throw const HttpException('片源重定向缺少地址');
      uri = checkedMediaRedirect(uri, location);
    }
    throw const HttpException('片源重定向次数过多');
  }

  Future<bool> _resolve({bool refresh = false}) async {
    final (probe, uri) = await _follow(_origin, 0, 0);
    final match = RegExp(r'^bytes 0-0/(\d+)$')
        .firstMatch(probe.headers.value(HttpHeaders.contentRangeHeader) ?? '');
    final mime = probe.headers.contentType?.mimeType ?? '';
    final valid = probe.statusCode == 206 && match != null && int.parse(match[1]!) > 0 &&
        !mime.contains('mpegurl') && !mime.contains('dash') &&
        !mime.startsWith('text/') && !mime.contains('xml');
    if (!valid) { await probe.listen((_) {}).cancel(); return false; }
    final total = int.parse(match[1]!);
    final etag = probe.headers.value(HttpHeaders.etagHeader);
    final validator = etag != null && !etag.startsWith('W/') ? etag :
        probe.headers.value(HttpHeaders.lastModifiedHeader);
    if (refresh && (total != length || (_validator != null && validator != _validator))) {
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
    if (_resolving != null) { await _resolving; return; }
    if (_linkVersion != failedVersion) return;
    final future = () async {
      if (!await _resolve(refresh: true)) throw const HttpException('直链已失效，重新取链失败');
    }();
    _resolving = future;
    try { await future; } finally { _resolving = null; }
  }

  Future<HttpClientResponse> _request(_Download job) async {
    // A failed signed URL is retried once, with a single shared refresh.
    for (var attempt = 0; attempt < 2; attempt++) {
      final uri = _resolved!;
      final version = _linkVersion;
      final (response, finalUri) = await _follow(uri, job.start, job.end - 1, job: job);
      if ([401, 403, 410].contains(response.statusCode) && attempt == 0) {
        await response.listen((_) {}).cancel();
        await _refresh(version);
        continue;
      }
      if (response.statusCode != 206 ||
          response.headers.value(HttpHeaders.contentRangeHeader) != 'bytes ${job.start}-${job.end - 1}/$length' ||
          (_validator != null && (response.headers.value(HttpHeaders.etagHeader)?.startsWith('W/') == false
              ? response.headers.value(HttpHeaders.etagHeader)
              : response.headers.value(HttpHeaders.lastModifiedHeader)) != _validator) ||
          (response.contentLength >= 0 && response.contentLength != job.size)) {
        await response.listen((_) {}).cancel();
        throw const HttpException('片源范围或文件身份不一致');
      }
      if (_linkVersion == version) _resolved = finalUri;
      return response;
    }
    throw const HttpException('直链刷新失败');
  }

  bool _covered(int block) => _blockLengths[block] == _size(block) || _jobs.any((job) => job.contains(block));
  int _size(int block) => min(blockSize, length - block * blockSize);

  bool _reserve(int bytes, {required bool demand}) {
    while (_bytes + reservedBytes + bytes > budgetBytes && _blocks.isNotEmpty) {
      final candidates = _blocks.keys.where((n) => !_readers.containsKey(n) &&
          !_jobs.any((job) => job.contains(n)) && (demand || n < _focus)).toList();
      if (demand) candidates.sort((a, b) => (b - _focus).abs().compareTo((a - _focus).abs()));
      final key = candidates.firstOrNull;
      if (key == null) break;
      final file = _blocks.remove(key)!;
      _bytes -= _blockLengths.remove(key)!;
      if (file.existsSync()) file.deleteSync();
    }
    return _bytes + reservedBytes + bytes <= budgetBytes;
  }

  _Download? _schedule(int first, int endBlock, {bool demand = false}) {
    if (_closed || _jobs.length >= policy.concurrency) return null;
    var last = min(endBlock, first + max(1, min(policy.segmentBytes, budgetBytes) ~/ blockSize)).toInt();
    for (var next = first + 1; next < last; next++) {
      if (_covered(next)) { last = next; break; }
    }
    final start = first * blockSize + (_blockLengths[first] ?? 0);
    while (last > first && !_reserve(min(length, last * blockSize) - start, demand: demand)) { last--; }
    if (last <= first) return null;
    // Wait for a useful amount of consumed space instead of falling back to
    // one HTTP request per 1 MiB as a full cache window moves forward.
    if (!demand && (last - first) * blockSize < min(4 * blockSize, budgetBytes) &&
        last * blockSize < length && !_covered(last)) {
      return null;
    }
    final job = _Download(start, min(length, last * blockSize))..demand = demand;
    _jobs.add(job);
    job.result = _download(job);
    // Speculation may fail without an awaiting decoder. The demand path still
    // receives the original error; this listener prevents an unhandled future.
    unawaited(job.result.then<void>((_) {}, onError: (Object _) {}));
    return job;
  }

  void _prefetch(int first) {
    final window = min(budgetBytes, max(blockSize, prefetchBytes));
    final base = _consumedBlock ?? first;
    final upper = min((length + blockSize - 1) ~/ blockSize,
        base + max(1, window ~/ blockSize));
    final limit = _urgent ? min(2, policy.concurrency) : policy.concurrency;
    for (var block = first; block < upper && _jobs.length < limit;) {
      if (_covered(block)) { block++; continue; }
      var end = min(upper, block + policy.segmentBytes ~/ blockSize).toInt();
      for (var next = block + 1; next < end; next++) {
        if (_covered(next)) { end = next; break; }
      }
      final job = _schedule(block, end);
      if (job == null) break;
      block = (job.end + blockSize - 1) ~/ blockSize;
    }
  }

  Future<void> _download(_Download job) async {
    final clock = Stopwatch()..start();
    StreamIterator<List<int>>? body;
    var completed = false;
    try {
      final response = await _request(job);
      body = StreamIterator(response.timeout(const Duration(seconds: 20)));
      job.body = body;
      job.phase = 'body';
      job.touch();
      job.notify();
      if (_closed || job.cancelled) throw const _Cancelled();
      while (await body.moveNext()) {
        if (_closed || job.cancelled) throw const _Cancelled();
        final chunk = body.current;
        _rate.add(chunk.length);
        job.touch();
        if (job.received + chunk.length > job.size) throw const HttpException('片源返回范围过大');
        // Publish each received prefix. Readers never wait for the 4–8 MiB tail.
        for (var offset = 0; offset < chunk.length;) {
          final absolute = job.start + job.received;
          final number = absolute ~/ blockSize;
          final local = absolute % blockSize;
          final count = min(chunk.length - offset, blockSize - local);
          if ((_blockLengths[number] ?? 0) != local) throw const HttpException('缓存区间不连续');
          final file = _blocks[number] ?? File('${_directory.path}/$number.block');
          final handle = file.openSync(mode: FileMode.append);
          try { handle.writeFromSync(chunk, offset, offset + count); } finally { handle.closeSync(); }
          _blocks[number] = file;
          _blockLengths[number] = local + count;
          _bytes += count;
          job.received += count;
          offset += count;
        }
        job.notify();
      }
      if (_closed || job.cancelled) throw const _Cancelled();
      if (job.received != job.size) throw const HttpException('片源范围读取不完整');
      policy.completed(job.received, clock.elapsed);
      completed = true;
    } on Object catch (error) {
      job.error = error;
      if (!job.cancelled && !_closed) {
        policy.failed();
        onDiagnostic?.call('媒体分段失败 ${job.start}-${job.end} '
            'phase=${job.phase} received=${job.received} error=${error.runtimeType}');
      }
      rethrow;
    } finally {
      try {
        await body?.cancel();
      } finally {
        job.body = null;
        _jobs.remove(job);
        job.notify();
        if (completed && !_closed) scheduleMicrotask(() => _prefetch(_focus));
      }
    }
  }

  void _makeDemandRoom(int number) {
    final candidates = _jobs.where((job) => !job.contains(number) &&
        !_readers.keys.any(job.contains)).toList()
      ..sort((a, b) => (b.start - number * blockSize).abs().compareTo((a.start - number * blockSize).abs()));
    for (final job in candidates) {
      if (_jobs.length < policy.concurrency) break;
      job.cancel(); _jobs.remove(job);
    }
  }

  Future<List<int>> _block(int number, int generation, int begin) async {
    _readers.update(number, (value) => value + 1, ifAbsent: () => 1);
    var rescues = 0;
    var capacityWaits = 0;
    try {
    while (!_closed && generation == _generation) {
      _focus = number;
      final file = _blocks.remove(number);
      if (file != null) {
        _blocks[number] = file;
        if (_blockLengths[number]! > begin) {
          final bytes = file.readAsBytesSync();
          _prefetch(number);
          return bytes;
        }
      }
      _makeDemandRoom(number);
      var job = _jobs.where((job) => job.contains(number)).firstOrNull;
      job ??= _schedule(number, min((length + blockSize - 1) ~/ blockSize,
          number + max(1, min(policy.segmentBytes, max(blockSize, prefetchBytes)) ~/ blockSize)), demand: true);
      _prefetch(number);
      if (job == null) {
        if (_jobs.isEmpty) throw const HttpException('缓存容量不足');
        // No slot or no evictable space: wait for any owner to publish data or
        // finish instead of waiting on an unrelated first job forever.
        try {
          await Future.any(_jobs.map((owner) => owner.changed))
              .timeout(demandStallTimeout);
        } on TimeoutException {
          if (++capacityWaits > 2) throw const HttpException('缓存容量不足');
        }
        continue;
      }
      job.demand = true;
      // A connection attempt queued inside HttpClient cannot be aborted: the
      // only handle is the request returned by getUrl. Replacing it would leave
      // the pending connect alive and queue another one against the per-host
      // limit, which is how a slow CDN becomes a permanent zero-byte stall.
      // Requests that already have a socket but no headers, and body transfers
      // that stopped delivering, are safe to replace.
      if (job.phase == 'queued' || job.phase == 'connect') {
        await job.changed;
        if (job.error != null && !job.cancelled) throw job.error!;
        continue;
      }
      // Headers or body: replace a transfer that has delivered nothing for the
      // whole stall budget. Header stalls get a growing budget (3s, 6s, 12s)
      // because cancelling a slow-but-working origin only multiplies connects;
      // body stalls keep the fixed watchdog. job.idle is reset by every
      // received chunk and by each phase change.
      try {
        final budget = job.phase == 'headers'
            ? demandStallTimeout * (1 << rescues) +
                const Duration(milliseconds: 500)
            : demandStallTimeout;
        final remaining = budget - job.idle.elapsed;
        await job.changed.timeout(remaining.isNegative ? Duration.zero : remaining);
      } on TimeoutException {
        onDiagnostic?.call('媒体读取停滞 offset=${number * blockSize + begin} '
            'retry=${rescues + 1} $diagnosticState');
        if (++rescues > 2) {
          job.cancel(); _jobs.remove(job);
          throw const HttpException('当前播放分段持续无数据');
        }
        // Replace only the stalled owner, retaining its published prefix and
        // all successful later segments. The replacement uses the same budget.
        job.cancel(); _jobs.remove(job); policy.failed();
        _makeDemandRoom(number);
        continue;
      }
      if (job.error != null && !job.cancelled) throw job.error!;
    }
    throw const _Cancelled();
    } finally {
      final readers = _readers[number]! - 1;
      if (readers == 0) { _readers.remove(number); } else { _readers[number] = readers; }
    }
  }

  void setPlaybackUrgent(bool value) {
    _urgent = value;
    if (value) {
      final distant = _jobs.where((job) => !job.demand && !_readers.keys.any(job.contains)).toList()
        ..sort((a, b) => b.start.compareTo(a.start));
      for (final job in distant) {
        if (_jobs.length <= 2) break;
        job.cancel(); _jobs.remove(job);
      }
    }
  }

  /// The decoder can read far ahead or probe the tail. The speculative window
  /// follows the actual playhead, keeping it within the user's prefetch budget.
  void setConsumed(int byteOffset) {
    _consumedBlock = byteOffset.clamp(0, length - 1) ~/ blockSize;
    _prefetch(_consumedBlock!);
  }

  /// Called for explicit seeks, not format probes (which can read the tail).
  void seek(int byteOffset) {
    _generation++;
    _focus = byteOffset.clamp(0, length - 1) ~/ blockSize;
    if (_consumedBlock != null) _consumedBlock = _focus;
    for (final job in _jobs.toList()) { job.cancel(); }
    _jobs.clear();
  }

  Future<void> _serve(HttpRequest request) async {
    final response = request.response;
    final generation = _generation;
    var sent = false;
    try {
      if (_closed || request.uri.path != '/$_token') { response.statusCode = 404; await response.close(); return; }
      if (request.method != 'GET' && request.method != 'HEAD') { response.statusCode = 405; await response.close(); return; }
      final raw = request.headers.value(HttpHeaders.rangeHeader);
      var start = 0;
      var end = length - 1;
      if (raw != null) {
        final match = RegExp(r'^bytes=(\d*)-(\d*)$').firstMatch(raw);
        if (match == null || (match[1]!.isEmpty && match[2]!.isEmpty)) throw const FormatException('range');
        if (match[1]!.isEmpty) { start = max(0, length - int.parse(match[2]!)); }
        else { start = int.parse(match[1]!); if (match[2]!.isNotEmpty) end = min(end, int.parse(match[2]!)); }
        if (start > end || start >= length) throw const FormatException('range');
      }
      response.statusCode = raw == null ? 200 : 206;
      response.headers.set(HttpHeaders.acceptRangesHeader, 'bytes');
      response.headers.set(HttpHeaders.contentTypeHeader, contentType);
      response.contentLength = end - start + 1;
      if (raw != null) response.headers.set(HttpHeaders.contentRangeHeader, 'bytes $start-$end/$length');
      if (request.method != 'HEAD') {
        for (var offset = start; offset <= end && !_closed && generation == _generation;) {
          final block = await _block(offset ~/ blockSize, generation, offset % blockSize);
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
      onDiagnostic?.call('本地响应中止 offset=${request.headers.value(HttpHeaders.rangeHeader)} '
          'sent=$sent error=${error.runtimeType}');
      if (!sent) {
        // Surface a startup failure as an HTTP error so the decoder reports it
        // instead of waiting on a truncated response that looks like zero speed.
        try {
          response.statusCode = 502;
          response.headers.removeAll(HttpHeaders.contentRangeHeader);
          response.headers.removeAll(HttpHeaders.acceptRangesHeader);
          response.contentLength = 0;
          await response.close();
          return;
        } on Object {
          // Fall through to a hard close when headers are already committed.
        }
      }
      await response.detachSocket().then((socket) => socket.destroy()).catchError((Object _) {});
    }
  }

  Future<void> close() async {
    if (_closed) return;
    _closed = true;
    _generation++;
    final pending = _jobs.toList();
    for (final job in pending) { job.cancel(); }
    _client.close(force: true);
    await _server.close(force: true);
    try { await Future.wait(pending.map((job) => job.result)).timeout(const Duration(seconds: 2)); } on Object { /* cancelled */ }
    _jobs.clear();
    _blocks.clear(); _blockLengths.clear(); _bytes = 0;
    if (await _directory.exists()) await _directory.delete(recursive: true);
  }
}

class _Download {
  final int start;
  final int end;
  bool cancelled = false;
  bool demand = false;
  String phase = 'queued';
  int received = 0;
  Object? error;
  /// Time since the last transport activity (connect, headers or body bytes).
  /// A request that is still establishing its connection must not be judged by
  /// the body stall budget; see the wait policy in `_block`.
  final Stopwatch idle = Stopwatch()..start();
  void touch() => idle.reset();
  Completer<void> _changed = Completer<void>();
  Future<void> get changed => _changed.future;
  void notify() { final before = _changed; _changed = Completer<void>(); before.complete(); }
  HttpClientRequest? request;
  StreamIterator<List<int>>? body;
  late Future<void> result;
  _Download(this.start, this.end);
  int get size => end - start;
  bool contains(int block) => (block + 1) * BoundedMediaCache.blockSize > start && block * BoundedMediaCache.blockSize < end;
  void cancel() {
    if (cancelled) return;
    cancelled = true;
    request?.abort(const _Cancelled());
    // abort() stops an outstanding request, but has no effect once response
    // headers have arrived. Cancel its body too, releasing the connection even
    // when a stalled origin never sends another chunk.
    final stream = body;
    if (stream != null) {
      unawaited(stream.cancel().then<void>((_) {}, onError: (Object _) {}));
    }
    notify();
  }
}
class _Cancelled implements Exception { const _Cancelled(); }
