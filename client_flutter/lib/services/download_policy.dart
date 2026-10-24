/// Automatic transport tuning. These are deliberately not user preferences:
/// cache capacity is a separate, hard limit supplied by the caller.
class DownloadPolicy {
  static const mib = 1024 * 1024;
  int concurrency = 2;
  int segmentBytes = 4 * mib;
  int _healthy = 0;
  double? _lastRate;

  void completed(int bytes, Duration elapsed) {
    final seconds = elapsed.inMicroseconds / 1000000;
    if (seconds <= 0) return;
    final rate = bytes / seconds;
    if (seconds > 15 || (_lastRate != null && rate < _lastRate! * 0.5)) {
      failed();
    } else if (++_healthy >= 2) {
      concurrency = (concurrency + 1).clamp(1, 4);
      if (rate >= 2 * mib) segmentBytes = 8 * mib;
      _healthy = 0;
    }
    _lastRate = rate;
  }

  void failed() {
    concurrency = (concurrency - 1).clamp(1, 4);
    segmentBytes = 4 * mib;
    _healthy = 0;
    _lastRate = null;
  }
}

/// Counts upstream bytes only, using monotonic time and a fixed rolling window.
/// Expired samples are removed completely so a real stall eventually reads zero.
class NetworkRate {
  final Duration Function() _now;
  final Duration window;
  final List<(Duration, int)> _samples = [];
  final Duration _started;

  NetworkRate({Duration Function()? now, Duration window = const Duration(seconds: 3)})
      : this._(now ?? _clock(), window: window);

  NetworkRate._(Duration Function() now, {this.window = const Duration(seconds: 3)})
      : _now = now, _started = now();

  static Duration Function() _clock() {
    final clock = Stopwatch()..start();
    return () => clock.elapsed;
  }

  void add(int bytes) {
    final now = _now();
    if (bytes > 0) {
      if (_samples.isNotEmpty && now - _samples.last.$1 < const Duration(milliseconds: 100)) {
        final last = _samples.removeLast();
        _samples.add((last.$1, last.$2 + bytes));
      } else {
        _samples.add((now, bytes));
      }
    }
    _trim(now);
  }

  double get bytesPerSecond {
    final now = _now();
    _trim(now);
    final elapsed = now - _started;
    final micros = elapsed.inMicroseconds.clamp(500000, window.inMicroseconds);
    return _samples.fold<int>(0, (sum, sample) => sum + sample.$2) * 1000000 / micros;
  }

  void _trim(Duration now) => _samples.removeWhere((sample) => now - sample.$1 >= window);
}
