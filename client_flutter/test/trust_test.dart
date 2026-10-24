import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:strmaction_desktop/core/config.dart';
import 'package:strmaction_desktop/core/trust.dart';

void main() {
  test('accepts CA roots and rejects leaf certificates and private keys', () {
    final root = File('test/fixtures/ca.pem').readAsStringSync();
    final leaf = File('test/fixtures/server.pem').readAsStringSync();
    final key = File('test/fixtures/server.key').readAsStringSync();
    expect(() => validateCaBundle(root), returnsNormally);
    expect(() => validateCaBundle(leaf), throwsA(isA<ConfigException>()));
    expect(() => validateCaBundle(key), throwsA(isA<ConfigException>()));
  });
  test('private CA keeps certificate and hostname validation for API and WebView probe', () async {
    final root = File('test/fixtures/ca.pem').readAsStringSync();
    final context = SecurityContext()
      ..useCertificateChain('test/fixtures/server.pem')
      ..usePrivateKey('test/fixtures/server.key');
    final server = await HttpServer.bindSecure(InternetAddress.loopbackIPv4, 0, context);
    final subscription = server.listen((request) async {
      request.response.write('ok'); await request.response.close();
    }, onError: (Object _) {});
    final port = server.port;
    final config = AppConfig(serverUrl: 'https://localhost:$port', trustedCaPem: root);
    expect(await verifyWebViewHost(const AppConfig(), 'localhost', port), isFalse);
    expect(await verifyWebViewHost(config, 'localhost', port), isTrue);
    expect(await verifyWebViewHost(config, '127.0.0.1', port), isFalse);
    final client = trustedClient(config);
    final request = await client.getUrl(Uri.parse(config.serverUrl));
    final response = await request.close();
    expect(response.statusCode, 200); await response.drain<void>();
    client.close(force: true);
    await subscription.cancel(); await server.close(force: true);
  });
}
