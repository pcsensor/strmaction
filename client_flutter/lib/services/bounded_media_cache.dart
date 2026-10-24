import 'dart:async';
import 'dart:io';
import 'dart:math';

import '../core/trust.dart';

/// Ephemeral, bounded LRU byte blocks for seekable progressive media. MPV's
/// append-only packet cache cannot enforce a disk byte budget. Manifests and
/// origins without valid Range support keep their normal native transport.
class BoundedMediaCache {
  static const blockSize = 1024 * 1024;
  final HttpClient _client;
  final Uri _origin;
  final Map<String, String> _headers;
  final Directory _directory;
  final int budgetBytes;
  final Map<int, File> _blocks = {}; // insertion order is LRU
  final Map<int, Future<List<int>>> _pending = {};
  late final HttpServer _server;
  late final String _token;
  late final int length;
  late final String contentType;
  var _bytes = 0;
  var _networkBytes = 0;
  var _lastSampleBytes = 0;
  var _lastSampleTime = DateTime.now();
  var _closed = false;
  double _speed = 0;

  BoundedMediaCache._(this._client, this._origin, this._headers, this._directory, this.budgetBytes);

  Uri get localUrl => Uri.parse('http://127.0.0.1:${_server.port}/$_token');
  int get storedBytes => _bytes;
  List<(int, int)> get ranges => _blocks.keys.map((n) => (n * blockSize, min(length, (n + 1) * blockSize))).toList();
  double get networkSpeed {
    final now = DateTime.now();
    final elapsed = now.difference(_lastSampleTime).inMilliseconds;
    if (elapsed >= 200) {
      _speed = (_networkBytes - _lastSampleBytes) * 1000 / elapsed;
      _lastSampleBytes = _networkBytes; _lastSampleTime = now;
    }
    return _speed;
  }
  static Future<BoundedMediaCache?> open({required String url, required Map<String, String> headers,
    required String trustedCaPem, required String directory, required int budgetBytes}) async {
    if (budgetBytes <= 0 || RegExp(r'\.(m3u8|mpd)$', caseSensitive: false).hasMatch(Uri.parse(url).path)) return null;
    final client = HttpClient(context: trustContext(trustedCaPem))..connectionTimeout = const Duration(seconds: 10);
    final cache = BoundedMediaCache._(client, Uri.parse(url), headers, Directory(directory), budgetBytes);
    try {
      final probe = await cache._request(0, 0);
      final match = RegExp(r'^bytes 0-0/(\d+)$').firstMatch(probe.headers.value(HttpHeaders.contentRangeHeader) ?? '');
      final mime = probe.headers.contentType?.mimeType ?? '';
      final supported = probe.statusCode == 206 && match != null &&
        !mime.contains('mpegurl') && !mime.contains('dash') && !mime.startsWith('text/') && !mime.contains('xml');
      if (!supported) { await probe.listen((_) {}).cancel(); client.close(force: true); return null; }
      cache.length = int.parse(match[1]!);
      cache.contentType = mime.isEmpty ? 'application/octet-stream' : mime;
      await probe.drain<void>().timeout(const Duration(seconds: 10));
      await cache._directory.create(recursive: true);
      cache._token = List.generate(24, (_) => Random.secure().nextInt(256).toRadixString(16).padLeft(2, '0')).join();
      cache._server = await HttpServer.bind(InternetAddress.loopbackIPv4, 0);
      cache._server.listen((request) => unawaited(cache._serve(request)), onError: (Object _) {});
      return cache;
    } on Object { client.close(force: true); rethrow; }
  }
  Future<HttpClientResponse> _request(int start, int end) async {
    var uri = _origin;
    for (var redirect = 0; redirect <= 5; redirect++) {
      final request = await _client.getUrl(uri).timeout(const Duration(seconds: 15));
      request.followRedirects = false;
      _headers.forEach((key, value) => request.headers.set(key, value));
      request.headers.set(HttpHeaders.rangeHeader, 'bytes=$start-$end');
      request.headers.set(HttpHeaders.acceptEncodingHeader, 'identity');
      final response = await request.close().timeout(const Duration(seconds: 15));
      if ([301, 302, 303, 307, 308].contains(response.statusCode)) {
        final location = response.headers.value(HttpHeaders.locationHeader);
        await response.listen((_) {}).cancel();
        if (location == null) throw const HttpException('片源重定向缺少地址');
        final next = uri.resolve(location);
        if (next.scheme != 'http' && next.scheme != 'https') throw const HttpException('片源重定向协议无效');
        uri = next;
      } else { return response; }
    }
    throw const HttpException('片源重定向次数过多');
  }
  Future<List<int>> _block(int number) async {
    final file = _blocks.remove(number);
    if (file != null) {
      _blocks[number] = file;
      return file.readAsBytesSync();
    }
    return _pending.putIfAbsent(number, () => _download(number).whenComplete(() => _pending.remove(number)));
  }
  Future<List<int>> _download(int number) async {
    final start = number * blockSize;
    final end = min(length - 1, start + blockSize - 1);
    final response = await _request(start, end);
    if (response.statusCode != 206 || response.headers.value(HttpHeaders.contentRangeHeader) != 'bytes $start-$end/$length') {
      await response.listen((_) {}).cancel();
      throw const HttpException('片源范围读取不一致');
    }
    final data = <int>[];
    await for (final chunk in response.timeout(const Duration(seconds: 20))) {
      _networkBytes += chunk.length;
      data.addAll(chunk);
      if (data.length > blockSize) throw const HttpException('片源返回范围过大');
    }
    if (data.length != end - start + 1) throw const HttpException('片源范围读取不完整');
    if (!_closed && data.length <= budgetBytes) {
      // No awaits between the capacity check/reservation: concurrent requests
      // cannot reserve the same bytes or overshoot the configured disk budget.
      while (_bytes + data.length > budgetBytes && _blocks.isNotEmpty) {
        final key = _blocks.keys.first;
        final stale = _blocks.remove(key)!;
        _bytes -= min(blockSize, length - key * blockSize);
        if (stale.existsSync()) stale.deleteSync();
      }
      final file = File('${_directory.path}/$number.block');
      file.writeAsBytesSync(data, flush: false);
      _blocks[number] = file;
      _bytes += data.length;
    }
    return data;
  }
  Future<void> _serve(HttpRequest request) async {
    final response = request.response;
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
        for (var offset = start; offset <= end && !_closed;) {
          final block = await _block(offset ~/ blockSize);
          final begin = offset % blockSize;
          final take = min(block.length - begin, end - offset + 1);
          response.add(block.sublist(begin, begin + take));
          await response.flush(); // Backpressure follows the native demuxer.
          offset += take;
        }
      }
      await response.close();
    } on FormatException {
      response.statusCode = 416;
      response.headers.set(HttpHeaders.contentRangeHeader, 'bytes */$length');
      await response.close();
    } on Object { response.detachSocket().then((socket) => socket.destroy()).catchError((Object _) {}); }
  }
  Future<void> close() async {
    if (_closed) return;
    _closed = true;
    _client.close(force: true);
    await _server.close(force: true);
    try { await Future.wait(_pending.values.toList()).timeout(const Duration(seconds: 2)); } on Object { /* canceled */ }
    _blocks.clear(); _bytes = 0;
    if (await _directory.exists()) await _directory.delete(recursive: true);
  }
}
