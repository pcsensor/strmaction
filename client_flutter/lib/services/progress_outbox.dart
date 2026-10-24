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
  Future<List<Map<String, dynamic>>> _read() async {
    final file = File(path);
    if (!await file.exists()) return [];
    final decoded = jsonDecode(await file.readAsString()) as List;
    final cutoff = DateTime.now().subtract(const Duration(days: 3)).millisecondsSinceEpoch;
    return decoded.whereType<Map>().map((e) => Map<String, dynamic>.from(e))
        .where((e) => (e['saved_at'] as int? ?? 0) >= cutoff).toList();
  }
  Future<void> _write(List<Map<String, dynamic>> entries) async {
    final file = File(path);
    await file.parent.create(recursive: true);
    final temp = File('$path.tmp');
    await temp.writeAsString(jsonEncode(entries), flush: true);
    if (await file.exists()) await file.delete();
    await temp.rename(path);
  }
  Future<void> save(String url, String token, Map<String, dynamic> body) => _locked(() async {
    final entries = await _read();
    entries.removeWhere((entry) => entry['url'] == url);
    entries.add({'url': url, 'token': token, 'body': body, 'saved_at': DateTime.now().millisecondsSinceEpoch});
    await _write(entries.length > 1000 ? entries.sublist(entries.length - 1000) : entries);
  });
  Future<void> acknowledge(String url, String key) => _locked(() async {
    final entries = await _read();
    entries.removeWhere((entry) => entry['url'] == url && (entry['body'] as Map)['client_key'] == key);
    await _write(entries);
  });
  Future<void> replay(String trustedCaPem) => _locked(() async {
    final entries = await _read();
    if (entries.isEmpty) return;
    final client = HttpClient(context: trustContext(trustedCaPem))..connectionTimeout = const Duration(seconds: 3);
    try {
      for (final entry in [...entries]) {
        try {
          final request = await client.postUrl(Uri.parse(entry['url'] as String)).timeout(const Duration(seconds: 3));
          request.headers.contentType = ContentType.json;
          request.headers.set(HttpHeaders.authorizationHeader, 'Bearer ${entry['token']}');
          request.write(jsonEncode(entry['body']));
          final response = await request.close().timeout(const Duration(seconds: 3));
          await response.drain<void>().timeout(const Duration(seconds: 3));
          if (response.statusCode < 400 || response.statusCode == 401 || response.statusCode == 403 || response.statusCode == 404) {
            entries.remove(entry);
            await _write(entries);
          } else { break; }
        } on Object { break; }
      }
    } finally { client.close(force: true); }
  });
}
