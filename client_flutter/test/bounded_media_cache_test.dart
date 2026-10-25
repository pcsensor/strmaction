import 'dart:io';
import 'dart:math';

import 'package:flutter_test/flutter_test.dart';
import 'package:strmaction_desktop/services/bounded_media_cache.dart';

void main() {
  test('media headers survive cross-origin redirects and subsequent cached range reads', () async {
    final root = await Directory.systemTemp.createTemp('media-headers-');
    final entry = await HttpServer.bind(InternetAddress.loopbackIPv4, 0);
    final origin = await HttpServer.bind(InternetAddress.loopbackIPv4, 0);
    const headers = {
      'uSeR-aGeNt': 'pan.baidu.com',
      'rEfErEr': 'https://pan.example/',
      'Authorization': 'Bearer media-fixture',
      'Cookie': 'media=fixture; option=a,b',
      'X-Media-Option': 'first,second',
    };
    var entries = 0;
    var reads = 0;
    void checkHeaders(HttpRequest request) {
      for (final header in headers.entries) {
        expect(request.headers.value(header.key), header.value);
      }
      expect(request.headers.value(HttpHeaders.acceptEncodingHeader), 'identity');
    }
    entry.listen((request) async {
      checkHeaders(request);
      entries++;
      request.response.statusCode = 302;
      request.response.headers.set(HttpHeaders.locationHeader, 'http://localhost:${origin.port}/media');
      await request.response.close();
    });
    origin.listen((request) async {
      checkHeaders(request);
      reads++;
      final match = RegExp(r'^bytes=(\d+)-(\d+)$')
          .firstMatch(request.headers.value(HttpHeaders.rangeHeader)!)!;
      final start = int.parse(match[1]!);
      final end = min(4095, int.parse(match[2]!));
      request.response.statusCode = 206;
      request.response.headers.set(HttpHeaders.contentRangeHeader, 'bytes $start-$end/4096');
      request.response.contentLength = end - start + 1;
      request.response.add(List.generate(end - start + 1, (index) => (start + index) % 251));
      await request.response.close();
    });
    final client = HttpClient();
    final cache = (await BoundedMediaCache.open(
      url: 'http://127.0.0.1:${entry.port}/entry', headers: headers, trustedCaPem: '',
      directory: '${root.path}/cache', budgetBytes: BoundedMediaCache.blockSize))!;
    addTearDown(() async {
      await cache.close();
      client.close(force: true);
      await entry.close(force: true);
      await origin.close(force: true);
      await root.delete(recursive: true);
    });
    final request = await client.getUrl(cache.localUrl);
    request.headers.set(HttpHeaders.rangeHeader, 'bytes=100-199');
    final response = await request.close();
    final bytes = await response.fold<List<int>>([], (all, part) => all..addAll(part));
    expect(bytes, List.generate(100, (index) => 100 + index));
    expect(entries, 1);
    expect(reads, 2, reason: 'the resolved URL is reused with the same media headers');
  });

  test('Range cache reuses blocks, enforces capacity, preserves headers and clears', () async {
    final bytes = List<int>.generate(3 * BoundedMediaCache.blockSize, (index) => index % 251);
    final root = await Directory.systemTemp.createTemp('strmaction-media-');
    final origin = await HttpServer.bind(InternetAddress.loopbackIPv4, 0);
    var requests = 0;
    final subscription = origin.listen((request) async {
      requests++;
      expect(request.headers.value('User-Agent'), 'custom-pan');
      expect(request.headers.value('Referer'), 'https://pan.example/');
      final match = RegExp(r'^bytes=(\d+)-(\d+)$').firstMatch(request.headers.value('Range')!)!;
      final start = int.parse(match[1]!);
      final end = min(bytes.length - 1, int.parse(match[2]!));
      request.response.statusCode = 206;
      request.response.headers.set('Content-Range', 'bytes $start-$end/${bytes.length}');
      request.response.headers.set('Content-Type', 'video/mp4');
      request.response.contentLength = end - start + 1;
      request.response.add(bytes.sublist(start, end + 1));
      await request.response.close();
    });
    final cache = (await BoundedMediaCache.open(url: 'http://127.0.0.1:${origin.port}/video',
      headers: {'User-Agent': 'custom-pan', 'Referer': 'https://pan.example/'}, trustedCaPem: '',
      directory: '${root.path}/cache', budgetBytes: BoundedMediaCache.blockSize))!;
    final client = HttpClient();
    Future<List<int>> read(int start, int end) async {
      final request = await client.getUrl(cache.localUrl);
      request.headers.set('Range', 'bytes=$start-$end');
      final response = await request.close();
      expect(response.statusCode, 206);
      return response.fold<List<int>>([], (all, part) => all..addAll(part));
    }
    expect(await read(0, 99), bytes.sublist(0, 100));
    final afterFirst = requests;
    expect(await read(30, 70), bytes.sublist(30, 71)); expect(requests, afterFirst);
    final seek = BoundedMediaCache.blockSize * 2;
    expect(await read(seek, seek + 9), bytes.sublist(seek, seek + 10));
    expect(cache.storedBytes, lessThanOrEqualTo(BoundedMediaCache.blockSize));
    final files = Directory('${root.path}/cache').listSync().whereType<File>();
    expect(files.fold<int>(0, (sum, file) => sum + file.lengthSync()), lessThanOrEqualTo(BoundedMediaCache.blockSize));
    final unauthorized = await client.getUrl(cache.localUrl.replace(path: '/wrong-token'));
    final denied = await unauthorized.close(); expect(denied.statusCode, 404); await denied.drain<void>();
    await cache.close(); expect(await Directory('${root.path}/cache').exists(), isFalse);
    client.close(force: true);
    await subscription.cancel(); await origin.close(force: true); await root.delete(recursive: true);
  });
  test('does not proxy origins without range support', () async {
    final origin = await HttpServer.bind(InternetAddress.loopbackIPv4, 0);
    final subscription = origin.listen((request) async { request.response.write('non-range origin'); await request.response.close(); });
    final cache = await BoundedMediaCache.open(url: 'http://127.0.0.1:${origin.port}/video', headers: {}, trustedCaPem: '', directory: '/unused', budgetBytes: 1024);
    expect(cache, isNull);
    await subscription.cancel(); await origin.close(force: true);
  });
}
