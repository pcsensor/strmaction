/// Log-safe URL: keep scheme and host, drop path, query and credentials.
String redactUrl(String? url) {
  if (url == null || url.isEmpty) return '';
  final uri = Uri.tryParse(url);
  if (uri == null || !uri.hasScheme || uri.host.isEmpty) {
    return '<invalid-url>';
  }
  return '${uri.scheme}://${uri.host}/***';
}

Map<String, String> redactHeaders(Map<String, String>? headers) {
  if (headers == null) return const {};
  return {for (final key in headers.keys) key: '***'};
}
