import 'dart:async';
import 'dart:io';
import 'dart:math';
import 'dart:typed_data';

import 'package:flutter_test/flutter_test.dart';

import 'package:strmaction_desktop/services/sequential_media_cache.dart';

const mib = 1024 * 1024;

class OriginFixture {
  late final HttpServer server;
  int length = 40 * mib;
  int entries = 0;
  int ticket = 0;
  int active = 0;
  int peak = 0;
  bool expire = false;
  Duration headerDelay = Duration.zero;
  int truncateAt = -1;
  bool truncated = false;
  final starts = <int>[];
  final ranges = <String>[];

  Future<void> start() async {
    server = await HttpServer.bind(InternetAddress.loopbackIPv4, 0);
    server.listen((request) async {
      var counted = false;
      try {
        expect(request.headers.value('User-Agent'), 'pan-fixture');
        expect(request.headers.value('Referer'), 'https://pan.example/');
        if (request.uri.path == '/entry') {
          entries++;
          ticket++;
          expire = false;
          request.response.statusCode = 302;
          request.response.headers.set('Location', '/media?ticket=$ticket');
          await request.response.close();
          return;
        }
        if (expire || request.uri.queryParameters['ticket'] != '$ticket') {
          request.response.statusCode = 403;
          await request.response.close();
          return;
        }
        final match =
            RegExp(r'bytes=(\d+)-(\d*)').firstMatch(request.headers.value('Range')!)!;
        final start = int.parse(match[1]!);
        final end = min(length - 1,
            match[2]!.isEmpty ? length - 1 : int.parse(match[2]!));
        final probe = start == 0 && end == 0;
        if (!probe) {
          active++;
          peak = max(peak, active);
          starts.add(start);
          ranges.add('$start-$end');
          counted = true;
          await Future<void>.delayed(const Duration(milliseconds: 20));
          if (headerDelay > Duration.zero) await Future<void>.delayed(headerDelay);
        }
        request.response.statusCode = 206;
        request.response.headers.set('Content-Type', 'video/mp4');
        request.response.headers.set('ETag', '"original"');
        request.response.headers
            .set('Content-Range', 'bytes $start-$end/$length');
        request.response.contentLength = end - start + 1;
        var cursor = start;
        var written = 0;
        while (cursor <= end) {
          final count = min(128 * 1024, end - cursor + 1);
          if (!probe && truncateAt > 0 && !truncated && start == 0 &&
              written + count > truncateAt) {
            final partial = truncateAt - written;
            if (partial > 0) {
              request.response.add(Uint8List.fromList(List<int>.generate(
                  partial, (index) => (cursor + index) % 251)));
              await request.response.flush();
            }
            truncated = true;
            await request.response.close();
            return;
          }
          request.response.add(Uint8List.fromList(List<int>.generate(
              count, (index) => (cursor + index) % 251)));
          await request.response.flush();
          cursor += count;
          written += count;
        }
        await request.response.close();
      } on Object {
        try {
          await request.response.close();
        } on Object {}
      } finally {
        if (counted) active--;
      }
    });
  }

  String get url => 'http://127.0.0.1:${server.port}/entry';
  Future<void> close() => server.close(force: true);
}

Future<List<int>> read(
    HttpClient client, SequentialMediaCache cache, int start, int end) async {
  final request = await client.getUrl(cache.localUrl);
  request.headers.set('Range', 'bytes=$start-$end');
  final response = await request.close();
  if (response.statusCode != 206) {
    await response.drain<void>();
    throw HttpException('本地缓存返回 HTTP ${response.statusCode}');
  }
  return response.fold<List<int>>([], (all, bytes) => all..addAll(bytes))
      .timeout(const Duration(seconds: 15));
}

Future<void> waitIdle(SequentialMediaCache cache) async {
  for (var i = 0; i < 400 && cache.activeDownloads > 0; i++) {
    await Future<void>.delayed(const Duration(milliseconds: 10));
  }
}

Future<SequentialMediaCache> openCache(OriginFixture origin, Directory root,
    {int prefetch = 16 * mib}) async {
  return (await SequentialMediaCache.open(
    url: origin.url,
    headers: {'User-Agent': 'pan-fixture', 'Referer': 'https://pan.example/'},
    trustedCaPem: '',
    directory: '${root.path}/cache',
    budgetBytes: 64 * mib,
    prefetchBytes: prefetch,
    connectTimeout: const Duration(seconds: 5),
    bodyStallTimeout: const Duration(seconds: 2),
  ))!;
}

void main() {
  test('sequential probe, cached reads and a single remote stream', () async {
    final origin = OriginFixture();
    await origin.start();
    final root = await Directory.systemTemp.createTemp('sequential-');
    final client = HttpClient();
    final cache = await openCache(origin, root);
    addTearDown(() async {
      await cache.close();
      client.close(force: true);
      await origin.close();
      await root.delete(recursive: true);
    });

    // A resume point away from the header: the 0-byte read is a probe, not a
    // second sequential stream.
    cache.setConsumed(20 * mib);
    expect(await read(client, cache, 0, 99), List.generate(100, (i) => i % 251));
    await waitIdle(cache);
    expect(origin.starts, hasLength(1), reason: 'the header read starts one probe');
    expect(origin.starts.single, 0);

    // A read inside the probe window must not touch the origin again.
    expect(await read(client, cache, 2 * mib, 2 * mib + 99),
        List.generate(100, (i) => (2 * mib + i) % 251));
    expect(origin.starts, hasLength(1), reason: 'cached bytes are served from disk');

    // A seek outside the cached window starts exactly one sequential stream.
    cache.seek(20 * mib);
    cache.setConsumed(20 * mib);
    expect(await read(client, cache, 20 * mib, 20 * mib + 99),
        List.generate(100, (i) => (20 * mib + i) % 251));
    expect(origin.starts, hasLength(2));
    expect(origin.starts.last, 20 * mib);
    await Future<void>.delayed(const Duration(milliseconds: 100));
    expect(origin.peak, lessThanOrEqualTo(2),
        reason: 'one probe plus one stream at most');
  });

  test('a slow response header is waited out, not retried', () async {
    final origin = OriginFixture()
      ..headerDelay = const Duration(milliseconds: 800);
    await origin.start();
    final root = await Directory.systemTemp.createTemp('slow-header-');
    final client = HttpClient();
    final cache = await openCache(origin, root);
    addTearDown(() async {
      await cache.close();
      client.close(force: true);
      await origin.close();
      await root.delete(recursive: true);
    });
    expect(await read(client, cache, 0, 99), List.generate(100, (i) => i % 251));
    await waitIdle(cache);
    expect(origin.starts, hasLength(1),
        reason: 'the 25s connect timeout must not become a retry loop');
  });

  test('a truncated response resumes after the received prefix', () async {
    final origin = OriginFixture()..truncateAt = 512 * 1024;
    await origin.start();
    final root = await Directory.systemTemp.createTemp('truncated-');
    final client = HttpClient();
    final cache = await openCache(origin, root);
    addTearDown(() async {
      await cache.close();
      client.close(force: true);
      await origin.close();
      await root.delete(recursive: true);
    });
    expect(await read(client, cache, 0, 99), List.generate(100, (i) => i % 251));
    await waitIdle(cache);
    expect(origin.truncated, isTrue);
    const offset = 700 * 1024;
    expect(await read(client, cache, offset, offset + 99),
        List.generate(100, (i) => (offset + i) % 251));
    expect(origin.starts, contains(512 * 1024),
        reason: 'the retry must continue after the received prefix');
    expect(origin.peak, lessThanOrEqualTo(2));
  });

  test('an expired link is refreshed and the stream resumes', () async {
    final origin = OriginFixture();
    await origin.start();
    final root = await Directory.systemTemp.createTemp('refresh-');
    final client = HttpClient();
    final cache = await openCache(origin, root);
    addTearDown(() async {
      await cache.close();
      client.close(force: true);
      await origin.close();
      await root.delete(recursive: true);
    });
    origin.expire = true;
    cache.seek(10 * mib);
    cache.setConsumed(10 * mib);
    expect(await read(client, cache, 10 * mib, 10 * mib + 99),
        List.generate(100, (i) => (10 * mib + i) % 251));
    expect(origin.entries, 2, reason: 'one initial resolve plus one refresh');
  });

  test('prefetch pauses at the window and resumes for the playhead', () async {
    final origin = OriginFixture();
    await origin.start();
    final root = await Directory.systemTemp.createTemp('pacing-');
    final client = HttpClient();
    final cache = await openCache(origin, root, prefetch: 4 * mib);
    addTearDown(() async {
      await cache.close();
      client.close(force: true);
      await origin.close();
      await root.delete(recursive: true);
    });
    cache.seek(10 * mib);
    cache.setConsumed(10 * mib);
    expect(await read(client, cache, 10 * mib, 10 * mib + 99),
        List.generate(100, (i) => (10 * mib + i) % 251));
    await Future<void>.delayed(const Duration(milliseconds: 700));
    final paused = cache.storedBytes;
    expect(paused, lessThan(12 * mib), reason: 'the window is 4 MiB');
    cache.setConsumed(14 * mib);
    await Future<void>.delayed(const Duration(milliseconds: 500));
    expect(cache.storedBytes, greaterThan(paused),
        reason: 'advancing the playhead resumes the same stream');
  });

  test('media headers survive a redirect', () async {
    final root = await Directory.systemTemp.createTemp('headers-');
    final server = await HttpServer.bind(InternetAddress.loopbackIPv4, 0);
    const headers = {
      'uSeR-aGeNt': 'pan.baidu.com',
      'rEfErEr': 'https://pan.example/',
      'Authorization': 'Bearer media-fixture',
      'Cookie': 'media=fixture; option=a,b',
      'X-Media-Option': 'first,second',
    };
    const length = 8192;
    var entries = 0;
    var reads = 0;
    void verify(HttpRequest request) {
      for (final header in headers.entries) {
        expect(request.headers.value(header.key), header.value);
      }
      expect(request.headers.value(HttpHeaders.acceptEncodingHeader), 'identity');
    }

    server.listen((request) async {
      if (request.uri.path == '/entry') {
        verify(request);
        entries++;
        request.response.statusCode = 302;
        request.response.headers.set(HttpHeaders.locationHeader, '/media');
        await request.response.close();
        return;
      }
      verify(request);
      reads++;
      final match =
          RegExp(r'bytes=(\d+)-(\d*)').firstMatch(request.headers.value('Range')!)!;
      final start = int.parse(match[1]!);
      final end = match[2]!.isEmpty
          ? length - 1
          : min(length - 1, int.parse(match[2]!));
      request.response.statusCode = 206;
      request.response.headers.set('Content-Type', 'video/mp4');
      request.response.headers
          .set('Content-Range', 'bytes $start-$end/$length');
      request.response.contentLength = end - start + 1;
      request.response.add(
          List<int>.generate(end - start + 1, (index) => (start + index) % 251));
      await request.response.close();
    });
    final client = HttpClient();
    final cache = (await SequentialMediaCache.open(
      url: 'http://127.0.0.1:${server.port}/entry',
      headers: headers,
      trustedCaPem: '',
      directory: '${root.path}/cache',
      budgetBytes: 4 * mib,
      prefetchBytes: 2 * mib,
      connectTimeout: const Duration(seconds: 5),
    ))!;
    addTearDown(() async {
      await cache.close();
      client.close(force: true);
      await server.close(force: true);
      await root.delete(recursive: true);
    });
    expect(await read(client, cache, 100, 199),
        List.generate(100, (index) => 100 + index));
    expect(entries, 1);
    expect(reads, 2, reason: 'one resolve probe and one sequential stream');
  });

  test('close removes the cache directory', () async {
    final origin = OriginFixture();
    await origin.start();
    final root = await Directory.systemTemp.createTemp('close-');
    final client = HttpClient();
    final cache = await openCache(origin, root);
    expect(await read(client, cache, 0, 99), List.generate(100, (i) => i % 251));
    final directory = Directory('${root.path}/cache');
    expect(directory.existsSync(), isTrue);
    await cache.close();
    client.close(force: true);
    await origin.close();
    await root.delete(recursive: true);
    expect(directory.existsSync(), isFalse);
    expect(cache.activeDownloads, 0);
  });
}
