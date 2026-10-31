class PlaybackPayloadException implements Exception {
  final String message;
  const PlaybackPayloadException(this.message);

  @override
  String toString() => message;
}

class SubtitleInfo {
  final String label;
  final String url;
  final String? format;
  final String? mime;
  final String? lang;

  const SubtitleInfo({required this.label, required this.url, this.format, this.mime, this.lang});

  Map<String, dynamic> toJson() => {'label': label, 'url': url, 'format': format, 'mime': mime, 'lang': lang};
}

class PlaylistEntry {
  final int? itemId;
  final String title;
  final String code;
  final int? episodeNo;
  final bool watched;
  final bool current;

  const PlaylistEntry({
    required this.itemId,
    required this.title,
    required this.code,
    required this.episodeNo,
    required this.watched,
    required this.current,
  });

  Map<String, dynamic> toJson() => {
        'item_id': itemId,
        'id': itemId,
        'title': title,
        'code': code,
        'episode_no': episodeNo,
        'watched': watched,
        'current': current,
      };
}

class PlaybackPayload {
  Map<String, dynamic> toNativeJson() => {
    'item_id': itemId, 'play_url': playUrl, 'headers': headers,
    'resume_ms': resumeMs, 'duration_ms': durationMs, 'title': title,
    'subtitles': subtitles.map((s) => s.toJson()).toList(),
  };

  final String mode;
  final int? bufferLimitMb;
  final int? diskCacheLimitMb;
  final int itemId;
  final String playUrl;
  final Map<String, String> headers;
  final String playToken;
  final int resumeMs;
  final int progressIntervalMs;
  final List<SubtitleInfo> subtitles;
  final String title;
  final String seriesTitle;
  final List<PlaylistEntry> playlist;
  final int? nextItemId;
  final String nextTitle;
  final int currentIndex;
  final int? durationMs;
  final int? progressRevision;

  const PlaybackPayload({
    this.mode = 'builtin',
    this.bufferLimitMb,
    this.diskCacheLimitMb,
    required this.itemId,
    required this.playUrl,
    required this.headers,
    required this.playToken,
    required this.resumeMs,
    required this.progressIntervalMs,
    required this.subtitles,
    required this.title,
    required this.seriesTitle,
    required this.playlist,
    required this.nextItemId,
    required this.nextTitle,
    required this.currentIndex,
    required this.durationMs,
    this.progressRevision,
  });

  /// 重试时从当前播放位置继续，而不是回到打开播放器时的续播点。
  PlaybackPayload withResumeMs(int value) {
    if (value <= 0 || value == resumeMs) return this;
    return PlaybackPayload(
      mode: mode,
      bufferLimitMb: bufferLimitMb,
      diskCacheLimitMb: diskCacheLimitMb,
      itemId: itemId,
      playUrl: playUrl,
      headers: headers,
      playToken: playToken,
      resumeMs: value,
      progressIntervalMs: progressIntervalMs,
      subtitles: subtitles,
      title: title,
      seriesTitle: seriesTitle,
      playlist: playlist,
      nextItemId: nextItemId,
      nextTitle: nextTitle,
      currentIndex: currentIndex,
      durationMs: durationMs,
      progressRevision: progressRevision,
    );
  }

  /// Header syntax understood by libmpv's `http-header-fields` option.
  ///
  /// A comma or colon in a header *name* would corrupt mpv's option grammar,
  /// so those entries are dropped instead of being allowed to break playback.
  String get httpHeaderFields {
    final parts = <String>[];
    for (final entry in headers.entries) {
      final key = entry.key.trim();
      final value = entry.value.trim();
      if (key.isEmpty || value.isEmpty || key.contains(',') || key.contains(':')) {
        continue;
      }
      parts.add('$key: $value');
    }
    return parts.join(',');
  }

  factory PlaybackPayload.fromJson(
    Map<String, dynamic> raw,
    String serverUrl,
  ) {
    final itemId = _requireInt(raw['item_id'], 'item_id', minimum: 1);
    final playUrl = _requireHttpUrl(raw['play_url'], 'play_url');
    final headers = _cleanHeaders(raw['headers']);
    final token = raw['play_token'];
    if (token is! String || !_tokenPattern.hasMatch(token.trim())) {
      throw const PlaybackPayloadException('play_token 无效');
    }
    final resumeMs = _optionalInt(raw['resume_ms'], 0);
    if (resumeMs < 0) {
      throw const PlaybackPayloadException('resume_ms 不能小于 0');
    }
    final interval = _optionalInt(raw['progress_interval_ms'], 5000)
        .clamp(2000, 60000);
    final subtitles = _cleanSubtitles(raw['subtitles'], serverUrl);
    final title = (raw['title'] ?? '').toString().trim();
    final seriesTitle = (raw['series_title'] ?? '').toString().trim();
    final duration = _positiveIntOrNull(raw['duration_ms']);
    final playlist = _cleanPlaylist(raw['playlist']);
    final nextItemId = _positiveIntOrNull(raw['next_item_id']);
    final nextTitle = (raw['next_title'] ?? '').toString().trim();
    final currentIndex = raw['current_index'] is int
        ? raw['current_index'] as int
        : -1;

    return PlaybackPayload(
      mode: raw['mode'] == 'copy' ? 'copy' : 'builtin',
      bufferLimitMb: raw['buffer_limit_mb'] is int ? (raw['buffer_limit_mb'] as int).clamp(0, 8192) : null,
      diskCacheLimitMb: raw['disk_cache_limit_mb'] is int ? (raw['disk_cache_limit_mb'] as int).clamp(0, 32768) : null,
      itemId: itemId,
      playUrl: playUrl,
      headers: headers,
      playToken: token.trim(),
      resumeMs: resumeMs,
      progressIntervalMs: interval,
      subtitles: subtitles,
      title: title,
      seriesTitle: seriesTitle,
      playlist: playlist,
      nextItemId: nextItemId,
      nextTitle: nextTitle,
      currentIndex: currentIndex,
      durationMs: duration,
      progressRevision: raw['progress_revision'] is int ? raw['progress_revision'] as int : null,
    );
  }

  static final RegExp _tokenPattern =
      RegExp(r'^[A-Za-z0-9._~+/=-]{8,512}$');

  static int _requireInt(dynamic value, String name, {int minimum = 0}) {
    if (value is bool) {
      throw PlaybackPayloadException('$name 必须是整数');
    }
    final parsed = value is int ? value : int.tryParse('$value');
    if (parsed == null) {
      throw PlaybackPayloadException('$name 必须是整数');
    }
    if (parsed < minimum) {
      throw PlaybackPayloadException('$name 不能小于 $minimum');
    }
    return parsed;
  }

  static int _optionalInt(dynamic value, int fallback) {
    if (value == null) return fallback;
    if (value is bool) return fallback;
    if (value is int) return value;
    return int.tryParse('$value') ?? fallback;
  }

  static int? _positiveIntOrNull(dynamic value) {
    if (value is bool || value == null) return null;
    final parsed = value is int ? value : int.tryParse('$value');
    return parsed != null && parsed > 0 ? parsed : null;
  }

  static String _requireHttpUrl(dynamic value, String name) {
    if (value is! String) {
      throw PlaybackPayloadException('$name 必须是 URL 字符串');
    }
    final url = value.trim();
    if (url.isEmpty || url.length > 16384) {
      throw PlaybackPayloadException('$name 长度不合法');
    }
    final uri = Uri.tryParse(url);
    if (uri == null ||
        !uri.hasScheme ||
        !(uri.scheme == 'http' || uri.scheme == 'https') ||
        uri.host.isEmpty) {
      throw PlaybackPayloadException('$name 必须是 http/https 地址');
    }
    return url;
  }

  static Map<String, String> _cleanHeaders(dynamic raw) {
    if (raw == null) return const {};
    if (raw is! Map) {
      throw const PlaybackPayloadException('headers 必须是对象');
    }
    if (raw.length > 32) {
      throw const PlaybackPayloadException('headers 数量过多');
    }
    final clean = <String, String>{};
    for (final entry in raw.entries) {
      if (entry.key is! String || entry.value is! String) {
        throw const PlaybackPayloadException('headers 的键和值都必须是字符串');
      }
      final key = (entry.key as String).trim();
      final value = (entry.value as String).trim();
      if (key.isEmpty ||
          key.length > 128 ||
          value.length > 4096) {
        throw const PlaybackPayloadException('headers 长度不合法');
      }
      if (key.contains('\r') ||
          key.contains('\n') ||
          value.contains('\r') ||
          value.contains('\n')) {
        throw const PlaybackPayloadException('headers 不能包含换行');
      }
      clean[key] = value;
    }
    return clean;
  }

  static List<SubtitleInfo> _cleanSubtitles(dynamic raw, String serverUrl) {
    if (raw == null) return const [];
    if (raw is! List) {
      throw const PlaybackPayloadException('subtitles 必须是数组');
    }
    if (raw.length > 32) {
      throw const PlaybackPayloadException('subtitles 数量过多');
    }
    final base = Uri.tryParse(serverUrl.endsWith('/') ? serverUrl : '$serverUrl/');
    final result = <SubtitleInfo>[];
    for (final entry in raw) {
      if (entry is! Map) continue;
      final urlValue = entry['url'];
      if (urlValue is! String || urlValue.trim().isEmpty) continue;
      final absolute = base?.resolve(urlValue.trim()).toString() ?? urlValue.trim();
      final uri = Uri.tryParse(absolute);
      if (uri == null ||
          !uri.hasScheme ||
          !(uri.scheme == 'http' || uri.scheme == 'https') ||
          uri.host.isEmpty) {
        continue;
      }
      final label = (entry['label'] ?? entry['lang'] ?? '').toString().trim();
      result.add(SubtitleInfo(label: label.isEmpty ? '字幕' : label, url: absolute, format: entry['format'] as String?, mime: entry['mime'] as String?, lang: entry['lang'] as String?));
    }
    return result;
  }

  static List<PlaylistEntry> _cleanPlaylist(dynamic raw) {
    if (raw is! List) return const [];
    final result = <PlaylistEntry>[];
    for (final entry in raw) {
      if (entry is! Map) continue;
      final rawId = entry['item_id'] ?? entry['id'];
      final itemId = _positiveIntOrNull(rawId);
      final episodeNo = _positiveIntOrNull(entry['episode_no']);
      result.add(
        PlaylistEntry(
          itemId: itemId,
          title: (entry['title'] ?? '').toString(),
          code: (entry['code'] ?? '').toString(),
          episodeNo: episodeNo,
          watched: entry['watched'] == true,
          current: entry['current'] == true,
        ),
      );
    }
    return result;
  }
}
