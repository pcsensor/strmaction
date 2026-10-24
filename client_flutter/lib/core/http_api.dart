import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'config.dart';

class HealthCheckResult {
  final bool ok;
  final String message;

  const HealthCheckResult(this.ok, this.message);
}

class ApiClient {
  final AppConfig config;

  const ApiClient(this.config);

  HttpClient _createClient() {
    final client = HttpClient()
      ..connectionTimeout = const Duration(seconds: 3);
    if (config.allowSelfSignedHttps) {
      client.badCertificateCallback = (cert, host, port) => true;
    }
    return client;
  }

  Future<HealthCheckResult> checkHealth() async {
    if (!config.isConfigured) {
      return const HealthCheckResult(false, '尚未配置服务器地址');
    }
    final uri = Uri.parse('${config.serverUrl}/api/health');
    final client = _createClient();
    try {
      final request = await client
          .getUrl(uri)
          .timeout(const Duration(seconds: 5));
      request.headers.set('X-StrmAction-Companion', '1');
      final response =
          await request.close().timeout(const Duration(seconds: 5));
      final body = await response
          .transform(utf8.decoder)
          .join()
          .timeout(const Duration(seconds: 5));
      if (response.statusCode < 200 || response.statusCode >= 300) {
        return HealthCheckResult(
          false,
          '服务器返回 HTTP ${response.statusCode}',
        );
      }
      final decoded = jsonDecode(body);
      if (decoded is! Map<String, dynamic> || decoded['ok'] != true) {
        return const HealthCheckResult(false, '服务未就绪');
      }
      return const HealthCheckResult(true, '');
    } on TimeoutException {
      return const HealthCheckResult(false, '连接服务器超时，请检查服务器是否启动。');
    } on HandshakeException {
      return const HealthCheckResult(
        false,
        'HTTPS 证书校验失败。请在桌面端设置中开启“允许自签名 HTTPS 证书”。',
      );
    } on SocketException {
      return const HealthCheckResult(false, '无法连接服务器，请检查地址、端口和服务器状态。');
    } on FormatException {
      return const HealthCheckResult(false, '服务器响应不是合法 JSON');
    } on Object catch (error) {
      return HealthCheckResult(false, '连接服务器失败：$error');
    } finally {
      client.close(force: true);
    }
  }
}
