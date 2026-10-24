import 'dart:async';
import 'dart:io';
import 'dart:math';
import 'dart:typed_data';

import '../core/trust.dart';
import 'download_policy.dart';

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
  var _closed = false;

  BoundedMediaCache._(this._client, this._origin, this._headers,
      this._directory, this.budgetBytes, this.prefetchBytes);

  Uri get localUrl => Uri.parse('http://127.0.0.1:${_server.port}/$_token');
  int get storedBytes => _bytes;
  int get reservedBytes => _jobs.fold(0, (sum, job) => sum + job.size);
  int get activeDownloads => _jobs.length;
  bool get cacheReady => _jobs.isEmpty && _blocks.containsKey(_focus);
  double get networkSpeed => _rate.bytesPerSecond;
  List<(int, int)> get ranges => _blocks.keys
      .map((n) => (n * blockSize, min(length, (n + 1) * blockSize))).toList();

  static Future<BoundedMediaCache?> open({required String url,
      required Map<String, String> headers, required String trustedCaPem,
      required String directory, required int budgetBytes, int? prefetchBytes}) async {
    if (budgetBytes <= 0 || RegExp(r'\.(m3u8|mpd)$', caseSensitive: false).hasMatch(Uri.parse(url).path)) return null;
    final client = HttpClient(context: trustContext(trustedCaPem))
      ..connectionTimeout = const Duration(seconds: 10)
      ..maxConnectionsPerHost = 4;
    final cache = BoundedMediaCache._(client, Uri.parse(url), headers,
        Directory(directory), budgetBytes, prefetchBytes ?? budgetBytes);
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
      final request = await _client.getUrl(uri).timeout(const Duration(seconds: 15));
      if (_closed || job?.cancelled == true) { request.abort(); throw const _Cancelled(); }
      job?.request = request;
      request.followRedirects = false;
      _headers.forEach((key, value) {
        if (!['host', 'range', 'connection', 'accept-encoding'].contains(key.toLowerCase())) {
          request.headers.set(key, value);
        }
      });
      request.headers.set(HttpHeaders.rangeHeader, 'bytes=$start-$end');
      request.headers.set(HttpHeaders.acceptEncodingHeader, 'identity');
      if (_validator != null && job != null) request.headers.set(HttpHeaders.ifRangeHeader, _validator!);
      final response = await request.close().timeout(const Duration(seconds: 15));
      if (![301, 302, 303, 307, 308].contains(response.statusCode)) return (response, uri);
      final location = response.headers.value(HttpHeaders.locationHeader);
      await response.listen((_) {}).cancel();
      if (location == null) throw const HttpException('片源重定向缺少地址');
      uri = uri.resolve(location);
      if (!['http', 'https'].contains(uri.scheme)) throw const HttpException('片源重定向协议无效');
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
          (response.headers.value(HttpHeaders.etagHeader) != null && _validator?.startsWith('"') == true &&
              response.headers.value(HttpHeaders.etagHeader) != _validator)) {
        await response.listen((_) {}).cancel();
        throw const HttpException('片源范围或文件身份不一致');
      }
      if (_linkVersion == version) _resolved = finalUri;
      return response;
    }
    throw const HttpException('直链刷新失败');
  }

  bool _covered(int block) => _blocks.containsKey(block) || _jobs.any((job) => job.contains(block));
  int _size(int block) => min(blockSize, length - block * blockSize);

  bool _reserve(int bytes, {required bool demand}) {
    while (_bytes + reservedBytes + bytes > budgetBytes && _blocks.isNotEmpty) {
      final key = _blocks.keys.where((n) => demand || n < _focus).firstOrNull;
      if (key == null) break;
      final file = _blocks.remove(key)!;
      _bytes -= _size(key);
      if (file.existsSync()) file.deleteSync();
    }
    return _bytes + reservedBytes + bytes <= budgetBytes;
  }

  _Download? _schedule(int first, int endBlock, {bool demand = false}) {
    if (_closed || _jobs.length >= policy.concurrency) return null;
    var last = min(endBlock, first + max(1, min(policy.segmentBytes, budgetBytes) ~/ blockSize));
    for (var next = first + 1; next < last; next++) {
      if (_covered(next)) { last = next; break; }
    }
    while (last > first && !_reserve(min(length, last * blockSize) - first * blockSize, demand: demand)) { last--; }
    if (last <= first) return null;
    final job = _Download(first * blockSize, min(length, last * blockSize));
    _jobs.add(job);
    job.result = _download(job);
    // Speculation may fail without an awaiting decoder. The demand path still
    // receives the original error; this listener prevents an unhandled future.
    unawaited(job.result.then<void>((_) {}, onError: (Object _) {}));
    return job;
  }

  void _prefetch(int first) {
    final window = min(budgetBytes, max(blockSize, prefetchBytes));
    final upper = min((length + blockSize - 1) ~/ blockSize,
        first + max(1, window ~/ blockSize));
    for (var block = first; block < upper && _jobs.length < policy.concurrency;) {
      if (_covered(block)) { block++; continue; }
      var end = min(upper, block + policy.segmentBytes ~/ blockSize);
      for (var next = block + 1; next < end; next++) {
        if (_covered(next)) { end = next; break; }
      }
      final job = _schedule(block, end);
      if (job == null) break;
      block = (job.end + blockSize - 1) ~/ blockSize;
    }
  }

  Future<Uint8List> _download(_Download job) async {
    final clock = Stopwatch()..start();
    try {
      final response = await _request(job);
      final data = BytesBuilder(copy: false);
      await for (final chunk in response.timeout(const Duration(seconds: 20))) {
        if (_closed || job.cancelled) throw const _Cancelled();
        _rate.add(chunk.length);
        data.add(chunk);
        if (data.length > job.size) throw const HttpException('片源返回范围过大');
      }
      if (data.length != job.size) throw const HttpException('片源范围读取不完整');
      final bytes = data.takeBytes();
      if (_closed || job.cancelled) throw const _Cancelled();
      // The segment reservation becomes disk blocks without changing usage.
      _jobs.remove(job);
      for (var offset = 0; offset < bytes.length; offset += blockSize) {
        final number = (job.start + offset) ~/ blockSize;
        final file = File('${_directory.path}/$number.block');
        file.writeAsBytesSync(Uint8List.sublistView(bytes, offset, min(bytes.length, offset + blockSize)));
        _blocks[number] = file;
        _bytes += _size(number);
      }
      policy.completed(bytes.length, clock.elapsed);
      scheduleMicrotask(() => _prefetch(_focus));
      return bytes;
    } on Object {
      if (!job.cancelled && !_closed) policy.failed();
      rethrow;
    } finally { _jobs.remove(job); }
  }

  Future<List<int>> _block(int number, int generation) async {
    while (!_closed && generation == _generation) {
      _focus = number;
      final file = _blocks.remove(number);
      if (file != null) {
        _blocks[number] = file;
        final bytes = file.readAsBytesSync();
        _prefetch(number);
        return bytes;
      }
      // Demand always wins over speculative work left behind by a seek/probe.
      if (!_jobs.any((job) => job.contains(number)) && _jobs.length >= policy.concurrency) {
        final distant = _jobs.last;
        distant.cancel();
        _jobs.remove(distant);
      }
      var job = _jobs.where((job) => job.contains(number)).firstOrNull;
      job ??= _schedule(number, min((length + blockSize - 1) ~/ blockSize,
          number + max(1, min(policy.segmentBytes, max(blockSize, prefetchBytes)) ~/ blockSize)), demand: true);
      _prefetch(number);
      if (job == null) {
        if (_jobs.isEmpty) throw const HttpException('缓存容量不足');
        await _jobs.first.result;
        continue;
      }
      final bytes = await job.result;
      if (_closed || generation != _generation) throw const _Cancelled();
      final offset = number * blockSize - job.start;
      return Uint8List.sublistView(bytes, offset, min(bytes.length, offset + blockSize));
    }
    throw const _Cancelled();
  }

  /// Called for explicit seeks, not format probes (which can read the tail).
  void seek(int byteOffset) {
    _generation++;
    _focus = (byteOffset.clamp(0, length - 1) / blockSize).floor();
    for (final job in _jobs.toList()) { job.cancel(); }
    _jobs.clear();
  }

  Future<void> _serve(HttpRequest request) async {
    final response = request.response;
    final generation = _generation;
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
          final block = await _block(offset ~/ blockSize, generation);
          final begin = offset % blockSize;
          final take = min(block.length - begin, end - offset + 1);
          response.add(block.sublist(begin, begin + take));
          await response.flush();
          offset += take;
        }
      }
      await response.close();
    } on FormatException {
      response.statusCode = 416;
      response.headers.set(HttpHeaders.contentRangeHeader, 'bytes */$length');
      await response.close();
    } on Object {
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
    _blocks.clear(); _bytes = 0;
    if (await _directory.exists()) await _directory.delete(recursive: true);
  }
}

class _Download {
  final int start;
  final int end;
  bool cancelled = false;
  HttpClientRequest? request;
  late Future<Uint8List> result;
  _Download(this.start, this.end);
  int get size => end - start;
  bool contains(int block) => block * BoundedMediaCache.blockSize >= start && block * BoundedMediaCache.blockSize < end;
  void cancel() { cancelled = true; request?.abort(const _Cancelled()); }
}
class _Cancelled implements Exception { const _Cancelled(); }
