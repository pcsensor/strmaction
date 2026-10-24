import 'dart:convert';
import 'dart:io';

import 'package:basic_utils/basic_utils.dart';

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
    final roots = X509Utils.parseChainStringAsString(pem);
    if (roots.isEmpty) throw const FormatException('empty CA bundle');
    for (final root in roots) {
      final certificate = X509Utils.x509CertificateFromPem(root).tbsCertificate!;
      final now = DateTime.now();
      final issuer = certificate.issuer;
      final subject = certificate.subject;
      if (certificate.extensions?.cA != true || issuer.length != subject.length ||
          !issuer.entries.every((e) => subject[e.key] == e.value) ||
          !X509Utils.checkX509Signature(root)) {
        throw const ConfigException('请导入自签名的根 CA 证书，不能使用叶子或中间证书。');
      }
      if (now.isBefore(certificate.validity.notBefore) || now.isAfter(certificate.validity.notAfter)) {
        throw const ConfigException('根 CA 证书尚未生效或已经过期。');
      }
    }
    trustContext(pem);
  } on ConfigException {
    rethrow;
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
