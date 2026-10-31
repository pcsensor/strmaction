import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:strmaction_desktop/services/progress_reporter.dart';
import 'package:strmaction_desktop/services/progress_outbox.dart';

void main() {
  test('sends bearer token, UA and JSON body', () async {
    final requests = <Map<String, dynamic>>[];
    final server = await HttpServer.bind(InternetAddress.loopbackIPv4, 0);
    final subscription = server.listen((request) async {
      final body = await utf8.decoder.bind(request).join();
      requests.add({
        'path': request.uri.path,
        'authorization': request.headers.value(HttpHeaders.authorizationHeader),
        'user-agent': request.headers.value(HttpHeaders.userAgentHeader),
        'body': jsonDecode(body),
      });
      request.response.statusCode = 200;
      await request.response.close();
    });

    final reporter = ProgressReporter(
      serverUrl: 'http://127.0.0.1:${server.port}',
      itemId: 42,
      playToken: 'pt_12345678',
      intervalMs: 5000,
      verifySsl: true,
      sessionId: 'test-session',
    );
    reporter.start();
    reporter.update(12000, durationMs: 60000);
    expect(await reporter.flushOnce(force: true), isTrue);
    await reporter.stop(flush: false);

    expect(requests, hasLength(1));
    final sent = requests.single;
    expect(sent['path'], '/api/items/42/progress');
    expect(sent['authorization'], 'Bearer pt_12345678');
    expect(sent['user-agent'], startsWith('StrmActionDesktop/'));
    expect(sent['body']['position_ms'], 12000);
    expect(sent['body']['duration_ms'], 60000);
    expect(sent['body']['finished'], isFalse);
    expect(sent['body']['client_key'], startsWith('desktop-test-session-'));

    await subscription.cancel();
    await server.close(force: true);
  });

  test('marks 90 percent as finished and resets position', () async {
    Map<String, dynamic>? sentBody;
    final server = await HttpServer.bind(InternetAddress.loopbackIPv4, 0);
    final subscription = server.listen((request) async {
      sentBody = jsonDecode(await utf8.decoder.bind(request).join())
          as Map<String, dynamic>;
      request.response.statusCode = 200;
      await request.response.close();
    });

    final reporter = ProgressReporter(
      serverUrl: 'http://127.0.0.1:${server.port}',
      itemId: 7,
      playToken: 'pt_12345678',
      intervalMs: 5000,
      verifySsl: true,
      sessionId: 'test-session',
    );
    reporter.start();
    reporter.update(95000, durationMs: 100000);
    await reporter.flushOnce(force: true);
    await reporter.stop(flush: false);

    expect(sentBody?['finished'], isTrue);
    expect(sentBody?['position_ms'], 0);

    await subscription.cancel();
    await server.close(force: true);
  });

  test('a transient zero position never replaces the saved progress', () async {
    final bodies = <Map<String, dynamic>>[];
    final server = await HttpServer.bind(InternetAddress.loopbackIPv4, 0);
    final subscription = server.listen((request) async {
      bodies.add(jsonDecode(await utf8.decoder.bind(request).join())
          as Map<String, dynamic>);
      request.response.statusCode = 200;
      await request.response.close();
    });
    final reporter = ProgressReporter(
      serverUrl: 'http://127.0.0.1:${server.port}',
      itemId: 8,
      playToken: 'pt_12345678',
      intervalMs: 5000,
      verifySsl: true,
      sessionId: 'test-session',
    );
    reporter.start();
    reporter.update(60000, durationMs: 120000);
    await reporter.flushOnce(force: true);
    expect(bodies.single['position_ms'], 60000);

    // 引擎重新装载或报错时会先把位置归零，随后的退出 / 心跳不能把它当成
    // 用户进度写回服务端。
    reporter.update(0, durationMs: 120000);
    await reporter.stop();

    expect(bodies, hasLength(2));
    expect(bodies.last['position_ms'], 60000);
    expect(bodies.every((body) => body['position_ms'] > 0), isTrue);

    await subscription.cancel();
    await server.close(force: true);
  });

  test('zero before the first positive position is not uploaded', () async {
    final bodies = <Map<String, dynamic>>[];
    final server = await HttpServer.bind(InternetAddress.loopbackIPv4, 0);
    final subscription = server.listen((request) async {
      bodies.add(jsonDecode(await utf8.decoder.bind(request).join())
          as Map<String, dynamic>);
      request.response.statusCode = 200;
      await request.response.close();
    });
    final reporter = ProgressReporter(
      serverUrl: 'http://127.0.0.1:${server.port}',
      itemId: 10,
      playToken: 'pt_12345678',
      intervalMs: 5000,
      verifySsl: true,
      sessionId: 'test-session',
    );
    reporter.start();
    reporter.update(0, durationMs: 120000);
    expect(await reporter.flushOnce(force: true), isTrue);
    await reporter.stop();
    expect(bodies, isEmpty);

    await subscription.cancel();
    await server.close(force: true);
  });

  test('a queued zero snapshot is discarded instead of clearing progress', () async {
    final directory = await Directory.systemTemp.createTemp('strmaction-outbox-');
    final path = '${directory.path}/outbox.json';
    await File(path).writeAsString(jsonEncode([
      {
        'url': 'http://127.0.0.1:1/api/items/1/progress',
        'token': 'pt_12345678',
        'body': {
          'position_ms': 0,
          'duration_ms': 120000,
          'finished': false,
          'client_key': 'old-zero',
        },
        'saved_at': DateTime.now().millisecondsSinceEpoch,
      },
    ]));
    await ProgressOutbox(path).replay('');
    expect(jsonDecode(await File(path).readAsString()), isEmpty);
    await directory.delete(recursive: true);
  });
  test('stop waits for the in-flight request and sends the final position', () async {
    final firstArrived = Completer<void>();
    final releaseFirst = Completer<void>();
    final bodies = <Map<String, dynamic>>[];
    final server = await HttpServer.bind(InternetAddress.loopbackIPv4, 0);
    final subscription = server.listen((request) async {
      bodies.add(jsonDecode(await utf8.decoder.bind(request).join()) as Map<String, dynamic>);
      if (bodies.length == 1) { firstArrived.complete(); await releaseFirst.future; }
      request.response.statusCode = 200;
      await request.response.close();
    });
    final reporter = ProgressReporter(serverUrl: 'http://127.0.0.1:${server.port}', itemId: 7,
      playToken: 'pt_12345678', intervalMs: 5000, verifySsl: true);
    reporter.start();
    reporter.update(10000, durationMs: 100000);
    final first = reporter.flushOnce();
    await firstArrived.future;
    reporter.update(25000, durationMs: 100000);
    final stopped = reporter.stop();
    releaseFirst.complete();
    await first;
    await stopped;
    expect(bodies.map((b) => b['position_ms']), [10000, 25000]);
    await subscription.cancel(); await server.close(force: true);
  });

  test('failed exit report remains queued until acknowledged after restart', () async {
    final directory = await Directory.systemTemp.createTemp('strmaction-progress-');
    final path = '${directory.path}/outbox.json';
    var fail = true;
    final bodies = <Map<String, dynamic>>[];
    final server = await HttpServer.bind(InternetAddress.loopbackIPv4, 0);
    final subscription = server.listen((request) async {
      bodies.add(jsonDecode(await utf8.decoder.bind(request).join()) as Map<String, dynamic>);
      expect(await File(path).exists(), isTrue); // Persisted before the request.
      request.response.statusCode = fail ? 503 : 200;
      await request.response.close();
    });
    final reporter = ProgressReporter(serverUrl: 'http://127.0.0.1:${server.port}', itemId: 9,
      playToken: 'pt_12345678', intervalMs: 5000, verifySsl: true, outboxPath: path);
    reporter.start(); reporter.update(42000, durationMs: 100000);
    await reporter.stop();
    expect(jsonDecode(await File(path).readAsString()), hasLength(1));
    fail = false;
    await ProgressOutbox(path).replay('');
    expect(bodies, hasLength(2));
    expect(bodies[1], bodies[0]);
    expect(jsonDecode(await File(path).readAsString()), isEmpty);
    await subscription.cancel(); await server.close(force: true);
    await directory.delete(recursive: true);
  });

  test('completion during an in-flight report sends the completion promptly', () async {
    final firstArrived = Completer<void>();
    final releaseFirst = Completer<void>();
    final finishedArrived = Completer<void>();
    final server = await HttpServer.bind(InternetAddress.loopbackIPv4, 0);
    final subscription = server.listen((request) async {
      final body = jsonDecode(await utf8.decoder.bind(request).join()) as Map<String, dynamic>;
      if (!firstArrived.isCompleted) {
        firstArrived.complete();
        await releaseFirst.future;
      } else if (body['finished'] == true && !finishedArrived.isCompleted) {
        finishedArrived.complete();
      }
      await request.response.close();
    });
    final reporter = ProgressReporter(serverUrl: 'http://127.0.0.1:${server.port}', itemId: 7,
      playToken: 'pt_12345678', intervalMs: 60000, verifySsl: true);
    reporter.start();
    reporter.update(20000, durationMs: 100000);
    final first = reporter.flushOnce();
    await firstArrived.future;
    reporter.finish();
    releaseFirst.complete();
    await first;
    await finishedArrived.future.timeout(const Duration(seconds: 3));
    await reporter.stop();
    await subscription.cancel();
    await server.close(force: true);
  });

  test('outbox isolates accounts and uses a renewed session for recovery', () async {
    final root = await Directory.systemTemp.createTemp('progress-accounts-');
    final path = '${root.path}/queue.json';
    final server = await HttpServer.bind(InternetAddress.loopbackIPv4, 0);
    final received = <String?>[];
    final subscription = server.listen((request) async {
      received.add(request.headers.value(HttpHeaders.cookieHeader));
      await request.drain<void>();
      await request.response.close();
    });
    final base = 'http://127.0.0.1:${server.port}';
    final url = '$base/api/items/1/progress';
    final outbox = ProgressOutbox(path);
    await outbox.save(url, 'expired-a', {'position_ms': 1, 'client_key': 'a', 'client_session': 'a'}, accountKey: '$base|1');
    await outbox.save(url, 'expired-b', {'position_ms': 2, 'client_key': 'b', 'client_session': 'b'}, accountKey: '$base|2');
    await outbox.replay('', accountKey: '$base|2', cookie: 'st_sess=b');
    expect(received, ['st_sess=b']);
    final remaining = jsonDecode(await File(path).readAsString()) as List;
    expect(remaining, hasLength(1));
    expect(remaining.single['account_key'], '$base|1');
    await subscription.cancel();
    await server.close(force: true);
    await root.delete(recursive: true);
  });

  test('expired credentials do not discard pending progress', () async {
    final root = await Directory.systemTemp.createTemp('progress-expired-');
    final path = '${root.path}/queue.json';
    final server = await HttpServer.bind(InternetAddress.loopbackIPv4, 0);
    final subscription = server.listen((request) async {
      await request.drain<void>();
      request.response.statusCode = request.headers.value(HttpHeaders.cookieHeader) == 'st_sess=new' ? 200 : 401;
      await request.response.close();
    });
    final base = 'http://127.0.0.1:${server.port}';
    final outbox = ProgressOutbox(path);
    await outbox.save('$base/api/items/1/progress', 'expired',
      {'position_ms': 1, 'client_key': 'a', 'client_session': 'a'}, accountKey: '$base|1');
    expect(await outbox.replay('', accountKey: '$base|1'), 1);
    expect(jsonDecode(await File(path).readAsString()), hasLength(1));
    expect(await outbox.replay('', accountKey: '$base|1', cookie: 'st_sess=new'), 0);
    expect(jsonDecode(await File(path).readAsString()), isEmpty);
    await subscription.cancel();
    await server.close(force: true);
    await root.delete(recursive: true);
  });
}
