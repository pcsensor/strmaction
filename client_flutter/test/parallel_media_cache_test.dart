import 'dart:async';
import 'dart:io';
import 'dart:math';
import 'dart:typed_data';

import 'package:flutter_test/flutter_test.dart';
import 'package:strmaction_desktop/services/bounded_media_cache.dart';
import 'package:strmaction_desktop/services/download_policy.dart';

const mib = 1024 * 1024;

class OriginFixture {
  late final HttpServer server;
  int entries = 0;
  int ticket = 0;
  int active = 0;
  int peak = 0;
  int length = 40 * mib;
  bool expire = false;
  bool wrongRange = false;
  bool changed = false;
  bool holdFirst = false;
  bool holdEveryHead = false;
  int firstPrefixBytes = 64 * 1024;
  int firstRequests = 0;
  final releaseFirst = Completer<void>();
  final firstHeld = Completer<void>();
  final laterCompleted = Completer<void>();
  final sizes = <int>[];
  final starts = <int>[];
  Future<void> start() async {
    server = await HttpServer.bind(InternetAddress.loopbackIPv4, 0);
    server.listen((request) async {
      var counted = false;
      try {
        expect(request.headers.value('User-Agent'), 'pan-fixture');
        expect(request.headers.value('Referer'), 'https://pan.example/');
        if (request.uri.path == '/entry') {
          entries++; ticket++; expire = false;
          request.response.statusCode = 302;
          request.response.headers.set('Location', '/media?ticket=$ticket');
          await request.response.close(); return;
        }
        if (expire || request.uri.queryParameters['ticket'] != '$ticket') {
          request.response.statusCode = 403; await request.response.close(); return;
        }
        final range = RegExp(r'bytes=(\d+)-(\d+)').firstMatch(request.headers.value('Range')!)!;
        final start = int.parse(range[1]!);
        final end = min(length - 1, int.parse(range[2]!));
        final probe = start == 0 && end == 0;
        if (!probe) {
          active++; peak = max(peak, active); sizes.add(end - start + 1); starts.add(start);
          counted = true;
          await Future<void>.delayed(const Duration(milliseconds: 30));
        }
        request.response.statusCode = 206;
        request.response.headers.set('Content-Type', 'video/mp4');
        request.response.headers.set('ETag', changed ? '"changed"' : '"original"');
        request.response.headers.set('Content-Range', 'bytes ${wrongRange && !probe ? start + 1 : start}-$end/$length');
        request.response.contentLength = end - start + 1;
        var cursor = start;
        if (!probe && start == 0 && holdFirst && (firstRequests++ == 0 || holdEveryHead)) {
          final count = min(firstPrefixBytes, end - start + 1);
          request.response.add(Uint8List.fromList(List.generate(count, (index) => index % 251)));
          await request.response.flush();
          if (!firstHeld.isCompleted) firstHeld.complete();
          await releaseFirst.future;
          cursor += count;
        }
        for (; cursor <= end; cursor += 256 * 1024) {
          request.response.add(Uint8List.fromList(List<int>.generate(
            min(256 * 1024, end - cursor + 1), (index) => (cursor + index) % 251)));
        }
        await request.response.close();
        if (!probe && start >= 4 * mib && !laterCompleted.isCompleted) laterCompleted.complete();
      } on Object { unawaited(request.response.close().then<void>((_) {}, onError: (Object _) {})); }
      finally { if (counted) active--; }
    });
  }
  String get url => 'http://127.0.0.1:${server.port}/entry';
  Future<void> close() async {
    if (!releaseFirst.isCompleted) releaseFirst.complete();
    await server.close(force: true);
  }
}

Future<List<int>> read(HttpClient client, BoundedMediaCache cache, int start, int end) async {
  final request = await client.getUrl(cache.localUrl);
  request.headers.set('Range', 'bytes=$start-$end');
  final response = await request.close();
  expect(response.statusCode, 206);
  return response.fold<List<int>>([], (all, bytes) => all..addAll(bytes))
      .timeout(const Duration(seconds: 10));
}

void main() {
  for (final headersArrived in [true, false]) {
    test('releases stalled connections when headersArrived=$headersArrived', () async {
      final root = await Directory.systemTemp.createTemp('cancelled-bodies-');
      final origin = await HttpServer.bind(InternetAddress.loopbackIPv4, 0);
      final release = Completer<void>();
      const prefix = 64 * 1024;
      const length = 40 * mib;
      final starts = <int>[];
      origin.listen((request) async {
        try {
          final match = RegExp(r'^bytes=(\d+)-(\d+)$')
              .firstMatch(request.headers.value(HttpHeaders.rangeHeader)!)!;
          final start = int.parse(match[1]!);
          final end = min(length - 1, int.parse(match[2]!));
          final probe = start == 0 && end == 0;
          request.response.statusCode = 206;
          request.response.headers.set(HttpHeaders.contentTypeHeader, 'video/mp4');
          request.response.headers.set(HttpHeaders.contentRangeHeader, 'bytes $start-$end/$length');
          request.response.contentLength = end - start + 1;
          if (!probe) starts.add(start);
          if (!probe && start < 16 * mib) {
            if (headersArrived) {
              request.response.add(Uint8List(prefix));
              await request.response.flush();
            }
            // Either the response body stalls, or headers arrive after timeout.
            await release.future;
            request.response.add(Uint8List(end - start + 1 - (headersArrived ? prefix : 0)));
          } else {
            request.response.add(Uint8List(end - start + 1));
          }
          await request.response.close();
        } on Object {
          unawaited(request.response.close().then<void>((_) {}, onError: (Object _) {}));
        }
      });
      final client = HttpClient();
      final cache = (await BoundedMediaCache.open(
        url: 'http://127.0.0.1:${origin.port}/video', headers: {}, trustedCaPem: '',
        directory: '${root.path}/cache', budgetBytes: 32 * mib, prefetchBytes: 16 * mib,
        requestTimeout: headersArrived ? const Duration(seconds: 15) : const Duration(milliseconds: 500),
        demandStallTimeout: const Duration(milliseconds: 250)))!;
      addTearDown(() async {
        await cache.close();
        client.close(force: true);
        if (!release.isCompleted) release.complete();
        await origin.close(force: true);
        await root.delete(recursive: true);
      });
      cache.policy.concurrency = 4;
      cache.setConsumed(0);
      for (var i = 0; i < 200 && (headersArrived ? cache.storedBytes < 4 * prefix : starts.length < 4); i++) {
        await Future<void>.delayed(const Duration(milliseconds: 10));
      }
      expect(starts, containsAll([0, 4 * mib, 8 * mib, 12 * mib]));
      if (headersArrived) {
        expect(cache.storedBytes, 4 * prefix);
        expect(cache.activeDownloads, 4);
      } else {
        for (var i = 0; i < 200 && cache.activeDownloads > 0; i++) {
          await Future<void>.delayed(const Duration(milliseconds: 10));
        }
        expect(cache.activeDownloads, 0);
        release.complete();
      }

      cache.seek(24 * mib);
      expect(await read(client, cache, 24 * mib, 24 * mib + 99)
          .timeout(const Duration(seconds: 2)), List.filled(100, 0));
      if (headersArrived) {
        expect(release.isCompleted, isFalse,
          reason: 'replacement reads must not wait for old origins to send more data');
      }
      expect(starts, contains(24 * mib));
      expect(cache.storedBytes + cache.reservedBytes, lessThanOrEqualTo(32 * mib));
    });
  }

  test('publishes a received prefix before its slow segment finishes, then rescues only the gap', () async {
    final origin = OriginFixture()..holdFirst = true; await origin.start();
    final root = await Directory.systemTemp.createTemp('prefix-cache-');
    final client = HttpClient();
    final cache = (await BoundedMediaCache.open(url: origin.url,
      headers: {'User-Agent': 'pan-fixture', 'Referer': 'https://pan.example/'},
      trustedCaPem: '', directory: '${root.path}/cache', budgetBytes: 16 * mib,
      demandStallTimeout: const Duration(milliseconds: 200)))!;
    addTearDown(() async { await cache.close(); client.close(force: true); await origin.close(); await root.delete(recursive: true); });
    expect(await read(client, cache, 0, 99).timeout(const Duration(seconds: 2)), List.generate(100, (i) => i % 251));
    expect(origin.releaseFirst.isCompleted, isFalse);
    await origin.laterCompleted.future.timeout(const Duration(seconds: 2));
    expect(cache.storedBytes + cache.reservedBytes, lessThanOrEqualTo(16 * mib));
    final offset = origin.firstPrefixBytes;
    expect(await read(client, cache, offset, offset + 99), List.generate(100, (i) => (offset + i) % 251));
    expect(origin.starts, contains(offset), reason: 'retry must retain the already delivered prefix');
    expect(origin.entries, 1);
    expect(cache.policy.concurrency, inInclusiveRange(2, 4));
  });

  test('a stalled head is replaced while later segments finish successfully', () async {
    final origin = OriginFixture()..holdFirst = true..firstPrefixBytes = 0; await origin.start();
    final root = await Directory.systemTemp.createTemp('head-cache-');
    final client = HttpClient();
    final cache = (await BoundedMediaCache.open(url: origin.url,
      headers: {'User-Agent': 'pan-fixture', 'Referer': 'https://pan.example/'},
      trustedCaPem: '', directory: '${root.path}/cache', budgetBytes: 16 * mib,
      demandStallTimeout: const Duration(milliseconds: 200)))!;
    addTearDown(() async { await cache.close(); client.close(force: true); await origin.close(); await root.delete(recursive: true); });
    expect(await read(client, cache, 0, 99), List.generate(100, (i) => i % 251));
    expect(origin.releaseFirst.isCompleted, isFalse);
    expect(origin.firstRequests, 2);
    expect(origin.starts.where((start) => start == 0), hasLength(2));
    expect(cache.storedBytes + cache.reservedBytes, lessThanOrEqualTo(16 * mib));
  });

  test('a permanently stalled head has a bounded recovery budget and keeps parallel policy', () async {
    final origin = OriginFixture()..holdFirst = true..holdEveryHead = true..firstPrefixBytes = 0; await origin.start();
    final root = await Directory.systemTemp.createTemp('bounded-recovery-');
    final client = HttpClient();
    final cache = (await BoundedMediaCache.open(url: origin.url,
      headers: {'User-Agent': 'pan-fixture', 'Referer': 'https://pan.example/'},
      trustedCaPem: '', directory: '${root.path}/cache', budgetBytes: 16 * mib,
      demandStallTimeout: const Duration(milliseconds: 200)))!;
    addTearDown(() async { await cache.close(); client.close(force: true); await origin.close(); await root.delete(recursive: true); });
    await expectLater(read(client, cache, 0, 99), throwsA(isA<HttpException>()));
    expect(origin.firstRequests, 3);
    expect(cache.policy.concurrency, inInclusiveRange(2, 4));
    expect(cache.storedBytes + cache.reservedBytes, lessThanOrEqualTo(16 * mib));
  });

  test('signed URL is reused; bounded workers coalesce Range reads and preserve data', () async {
    final origin = OriginFixture(); await origin.start();
    final root = await Directory.systemTemp.createTemp('parallel-cache-');
    final client = HttpClient();
    final cache = (await BoundedMediaCache.open(url: origin.url,
      headers: {'User-Agent': 'pan-fixture', 'Referer': 'https://pan.example/'},
      trustedCaPem: '', directory: '${root.path}/cache', budgetBytes: 16 * mib))!;
    addTearDown(() async { await cache.close(); client.close(force: true); await origin.close(); await root.delete(recursive: true); });
    expect(await read(client, cache, 0, 99), List.generate(100, (index) => index % 251));
    for (var i = 0; i < 300 && cache.activeDownloads > 0; i++) {
      expect(cache.storedBytes + cache.reservedBytes, lessThanOrEqualTo(16 * mib));
      await Future<void>.delayed(const Duration(milliseconds: 10));
    }
    expect(origin.entries, 1);
    expect(origin.peak, inInclusiveRange(2, 4));
    expect(origin.sizes.any((size) => size >= 4 * mib), isTrue);
    expect(origin.sizes.every((size) => size <= 8 * mib), isTrue);
    final requests = origin.sizes.length;
    expect(await read(client, cache, 10, 50), List.generate(41, (index) => (index + 10) % 251));
    expect(origin.sizes.length, requests);
    await read(client, cache, 4 * mib, 4 * mib + 99);
    for (var i = 0; i < 300 && cache.activeDownloads > 0; i++) {
      await Future<void>.delayed(const Duration(milliseconds: 10));
    }
    expect(origin.sizes.every((size) => size >= 4 * mib), isTrue,
      reason: 'a moving full window must not degrade to tiny requests');
    final diskBytes = Directory('${root.path}/cache').listSync().whereType<File>()
        .fold<int>(0, (sum, file) => sum + file.lengthSync());
    expect(diskBytes, lessThanOrEqualTo(16 * mib));
  });

  test('concurrent expired readers share one refresh and do not loop', () async {
    final origin = OriginFixture(); await origin.start();
    final root = await Directory.systemTemp.createTemp('expired-cache-');
    final client = HttpClient();
    final cache = (await BoundedMediaCache.open(url: origin.url,
      headers: {'User-Agent': 'pan-fixture', 'Referer': 'https://pan.example/'},
      trustedCaPem: '', directory: '${root.path}/cache', budgetBytes: 16 * mib))!;
    addTearDown(() async { await cache.close(); client.close(force: true); await origin.close(); await root.delete(recursive: true); });
    origin.expire = true;
    final bytes = await read(client, cache, 0, 199);
    expect(bytes, List.generate(200, (index) => index % 251));
    for (var i = 0; i < 300 && cache.activeDownloads > 0; i++) {
      await Future<void>.delayed(const Duration(milliseconds: 10));
    }
    expect(origin.entries, 2);
  });

  test('rejects a wrong Content-Range instead of corrupting the cached file', () async {
    final origin = OriginFixture(); await origin.start();
    final root = await Directory.systemTemp.createTemp('invalid-cache-');
    final client = HttpClient();
    final cache = (await BoundedMediaCache.open(url: origin.url,
      headers: {'User-Agent': 'pan-fixture', 'Referer': 'https://pan.example/'},
      trustedCaPem: '', directory: '${root.path}/cache', budgetBytes: 4 * mib))!;
    addTearDown(() async { await cache.close(); client.close(force: true); await origin.close(); await root.delete(recursive: true); });
    origin.wrongRange = true;
    await expectLater(read(client, cache, 0, 99), throwsA(isA<HttpException>()));
    expect(cache.storedBytes, 0);
  });

  test('seek cancels speculation; close removes files and all reservations', () async {
    final origin = OriginFixture(); await origin.start();
    final root = await Directory.systemTemp.createTemp('seek-cache-');
    final client = HttpClient();
    final cache = (await BoundedMediaCache.open(url: origin.url,
      headers: {'User-Agent': 'pan-fixture', 'Referer': 'https://pan.example/'},
      trustedCaPem: '', directory: '${root.path}/cache', budgetBytes: 8 * mib))!;
    addTearDown(() async { await cache.close(); client.close(force: true); await origin.close(); await root.delete(recursive: true); });
    await read(client, cache, 0, 10);
    cache.seek(30 * mib);
    final bytes = await read(client, cache, 30 * mib, 30 * mib + 20);
    expect(bytes, List.generate(21, (index) => (30 * mib + index) % 251));
    await cache.close();
    expect(cache.activeDownloads, 0); expect(cache.reservedBytes, 0);
    expect(Directory('${root.path}/cache').existsSync(), isFalse);
  });

  test('refresh rejects a different file identity', () async {
    final origin = OriginFixture(); await origin.start();
    final root = await Directory.systemTemp.createTemp('changed-cache-');
    final client = HttpClient();
    final cache = (await BoundedMediaCache.open(url: origin.url,
      headers: {'User-Agent': 'pan-fixture', 'Referer': 'https://pan.example/'},
      trustedCaPem: '', directory: '${root.path}/cache', budgetBytes: 4 * mib))!;
    addTearDown(() async { await cache.close(); client.close(force: true); await origin.close(); await root.delete(recursive: true); });
    origin.expire = true; origin.changed = true;
    await expectLater(read(client, cache, 0, 99), throwsA(isA<HttpException>()));
    expect(cache.storedBytes, 0); expect(origin.entries, 2);
  });

  test('format probes do not move speculation past the actual playhead window', () async {
    final origin = OriginFixture(); await origin.start();
    final root = await Directory.systemTemp.createTemp('playhead-cache-');
    final client = HttpClient();
    final cache = (await BoundedMediaCache.open(url: origin.url,
      headers: {'User-Agent': 'pan-fixture', 'Referer': 'https://pan.example/'},
      trustedCaPem: '', directory: '${root.path}/cache', budgetBytes: 32 * mib, prefetchBytes: 8 * mib))!;
    addTearDown(() async { await cache.close(); client.close(force: true); await origin.close(); await root.delete(recursive: true); });
    cache.setConsumed(0);
    await read(client, cache, 24 * mib, 24 * mib + 99);
    for (var i = 0; i < 300 && cache.activeDownloads > 0; i++) {
      await Future<void>.delayed(const Duration(milliseconds: 10));
    }
    expect(origin.starts.every((start) => start < 8 * mib || start == 24 * mib), isTrue,
      reason: 'tail probes must not start another prefetch window');
  });

  test('rolling rate spans burst gaps and becomes zero after a real stall', () {
    var time = Duration.zero;
    final rate = NetworkRate(now: () => time);
    time = const Duration(milliseconds: 500); rate.add(3 * mib);
    time = const Duration(seconds: 1); expect(rate.bytesPerSecond, 3 * mib);
    time = const Duration(seconds: 2); expect(rate.bytesPerSecond, 1.5 * mib);
    time = const Duration(milliseconds: 3500); expect(rate.bytesPerSecond, 0);
  });
  test('automatic policy increases gradually, backs off and never exceeds four', () {
    final policy = DownloadPolicy();
    expect(policy.concurrency, 2); expect(policy.segmentBytes, 4 * mib);
    for (var i = 0; i < 20; i++) { policy.completed(4 * mib, const Duration(seconds: 1)); }
    expect(policy.concurrency, 4); expect(policy.segmentBytes, 8 * mib);
    policy.failed(); expect(policy.concurrency, 3); expect(policy.segmentBytes, 4 * mib);
    for (var i = 0; i < 10; i++) { policy.failed(); }
    expect(policy.concurrency, 2);
  });
}
