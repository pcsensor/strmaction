import 'dart:convert';
import 'dart:io';

import '../core/trust.dart';

/// Save before sending and remove only after acknowledgement. A later snapshot
/// for the same item supersedes its queued position. Playback waits for recovery
/// before a new session, so an old queue entry cannot overwrite a newer session.
class ProgressOutbox {
  final String path;
  static final Map<String, Future<void>> _tails = {};
  ProgressOutbox(this.path);

  Future<T> _locked<T>(Future<T> Function() operation) {
    final before = _tails[path] ?? Future<void>.value();
    final result = before.then((_) => operation());
    _tails[path] = result.then<void>((_) {}, onError: (Object _, StackTrace _) {});
    return result;
  }
  /// 位置为 0 且未完成的快照没有观看价值，重放它会清空服务端进度。
  static bool _hasProgress(Map<String, dynamic> body) {
    final position = body['position_ms'];
    return body['finished'] == true || (position is num && position > 0);
  }
  Future<List<Map<String, dynamic>>> _read() async {
    final file = File(path);
    if (!await file.exists()) return [];
    final decoded = jsonDecode(await file.readAsString()) as List;
    return decoded.whereType<Map>().map((e) => Map<String, dynamic>.from(e)).toList();
  }
  Future<void> _write(List<Map<String, dynamic>> entries) async {
    final file = File(path);
    await file.parent.create(recursive: true);
    final temp = File('$path.tmp');
    await temp.writeAsString(jsonEncode(entries), flush: true);
    await temp.rename(path);
  }
  Future<void> save(String url, String token, Map<String, dynamic> body, {String? accountKey}) => _locked(() async {
    if (!_hasProgress(body)) return;
    final entries = await _read();
    // Unknown legacy owners are never overwritten by a different session.
    entries.removeWhere((entry) => accountKey != null && entry['url'] == url &&
      entry['account_key'] == accountKey && (entry['body'] as Map?)?['client_session'] == body['client_session'] &&
      body['client_session'] != null);
    entries.add({'url': url, 'token': token, 'body': body, 'account_key': accountKey, 'saved_at': DateTime.now().millisecondsSinceEpoch});
    await _write(entries);
  });
  Future<void> acknowledge(String url, String key) => _locked(() async {
    final entries = await _read();
    entries.removeWhere((entry) => entry['url'] == url && (entry['body'] as Map)['client_key'] == key);
    await _write(entries);
  });
  /// Returns the number of records needing user attention; records for other
  /// accounts stay private and are not counted.
  Future<int> replay(String trustedCaPem, {String? accountKey, String? cookie}) => _locked(() async {
    final entries = await _read();
    if (entries.isEmpty) return 0;
    var unresolved = 0;
    final client = HttpClient(context: trustContext(trustedCaPem))..connectionTimeout = const Duration(seconds: 3);
    try {
      for (final entry in [...entries]) {
        try {
          final owner = entry['account_key'];
          if (owner != null && owner != accountKey) continue;
          if (owner != null) {
            final separator = owner.toString().lastIndexOf('|');
            if (separator < 0) continue;
            final server = Uri.tryParse(owner.toString().substring(0, separator));
            final destination = Uri.tryParse(entry['url'] as String? ?? '');
            if (server == null || destination == null || server.scheme != destination.scheme ||
                server.host != destination.host || server.port != destination.port) {
              continue;
            }
          }
          final rawBody = entry['body'];
          if (rawBody is! Map ||
              !_hasProgress(Map<String, dynamic>.from(rawBody))) {
            // 旧版本可能在出错时排入一条 0 进度；重放它会把服务端刚刚
            // 更新的续播点清掉，直接丢弃。
            entries.remove(entry);
            await _write(entries);
            continue;
          }
          final request = await client.postUrl(Uri.parse(entry['url'] as String)).timeout(const Duration(seconds: 3));
          request.followRedirects = false;
          request.headers.contentType = ContentType.json;
          if (owner != null && cookie != null && cookie.isNotEmpty) {
            request.headers.set(HttpHeaders.cookieHeader, cookie);
          } else {
            request.headers.set(HttpHeaders.authorizationHeader, 'Bearer ${entry['token']}');
          }
          request.write(jsonEncode(entry['body']));
          final response = await request.close().timeout(const Duration(seconds: 3));
          await response.drain<void>().timeout(const Duration(seconds: 3));
          if (response.statusCode >= 200 && response.statusCode < 300) {
            entries.remove(entry);
            await _write(entries);
          } else if (response.statusCode >= 500) { break; }
          else { unresolved++; }
        } on Object { break; }
      }
    } finally { client.close(force: true); }
    return unresolved;
  });
}
