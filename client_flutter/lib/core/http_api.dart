import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'config.dart';
import 'trust.dart';

class HealthCheckResult {
  final bool ok;
  final String message;

  const HealthCheckResult(this.ok, this.message);
}

class ApiClient {
  final AppConfig config;
  HttpClient? _client;

  ApiClient(this.config);

  /// 复用同一个 HttpClient，避免每次请求都重新建立 TCP/TLS 连接。
  /// 播放前会连续请求多个接口，握手时间会直接叠加到“点击后多久进播放器”。
  HttpClient _httpClient() {
    final existing = _client;
    if (existing != null) return existing;
    final client = trustedClient(config)
      ..connectionTimeout = const Duration(seconds: 5)
      ..idleTimeout = const Duration(seconds: 30);
    _client = client;
    return client;
  }

  void close() {
    _client?.close(force: true);
    _client = null;
  }

  Future<Map<String, dynamic>> request(String path, {String cookie = '', Map<String, dynamic>? body}) async {
    final client = _httpClient();
    final request = await client.openUrl(body == null ? 'GET' : 'POST', Uri.parse('${config.serverUrl}$path')).timeout(const Duration(seconds: 10));
    request.headers.set('X-StrmAction-Companion', '1');
    request.headers.set('User-Agent', 'StrmActionCompanion/2.0');
    if (cookie.isNotEmpty) request.headers.set(HttpHeaders.cookieHeader, cookie);
    if (body != null) {
      request.headers.contentType = ContentType.json;
      request.add(utf8.encode(jsonEncode(body)));
    }
    final response = await request.close().timeout(const Duration(seconds: 15));
    final text = await response.transform(utf8.decoder).join().timeout(const Duration(seconds: 15));
    final data = jsonDecode(text) as Map<String, dynamic>;
    if (response.statusCode < 200 || response.statusCode >= 300) {
      throw ConfigException((data['error'] is Map ? data['error']['message'] : null)?.toString() ?? '服务器返回 HTTP ${response.statusCode}');
    }
    return data;
  }

  Future<HealthCheckResult> checkHealth() async {
    if (!config.isConfigured) {
      return const HealthCheckResult(false, '尚未配置服务器地址');
    }
    final uri = Uri.parse('${config.serverUrl}/api/health');
    final client = _httpClient();
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
        'HTTPS 证书校验失败。请在设置中导入私有根 CA，并检查主机名。',
      );
    } on SocketException {
      return const HealthCheckResult(false, '无法连接服务器，请检查地址、端口和服务器状态。');
    } on FormatException {
      return const HealthCheckResult(false, '服务器响应不是合法 JSON');
    } on Object catch (error) {
      return HealthCheckResult(false, '连接服务器失败：$error');
    }
  }
}
