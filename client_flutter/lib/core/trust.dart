import 'dart:convert';
import 'dart:io';

import 'config.dart';

/// Every API connection uses system roots plus the user's imported CA bundle.
/// No badCertificateCallback or hostname exception is installed.
SecurityContext trustContext(String pem) {
  final context = SecurityContext(withTrustedRoots: true);
  if (pem.trim().isNotEmpty) {
    context.setTrustedCertificatesBytes(utf8.encode(pem));
  }
  return context;
}

HttpClient trustedClient(AppConfig config) => HttpClient(
      context: trustContext(config.trustedCaPem),
    )..connectionTimeout = const Duration(seconds: 5);

void validateCaBundle(String pem) {
  if (pem.trim().isEmpty) return;
  if (pem.contains('PRIVATE KEY') || !pem.contains('-----BEGIN CERTIFICATE-----')) {
    throw const ConfigException('请导入 PEM 格式的根 CA 证书，不要导入私钥。');
  }
  try {
    trustContext(pem);
  } on Object {
    throw const ConfigException('CA 证书无法解析，请检查 PEM 内容。');
  }
}

Future<bool> verifyWebViewHost(AppConfig config, String host, int port) async {
  try {
    final socket = await SecureSocket.connect(
      host, port, context: trustContext(config.trustedCaPem),
      timeout: const Duration(seconds: 5),
    );
    socket.destroy();
    return true;
  } on Object {
    return false;
  }
}
