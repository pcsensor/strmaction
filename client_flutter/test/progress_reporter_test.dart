import 'dart:convert';
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:strmaction_desktop/services/progress_reporter.dart';

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
}
