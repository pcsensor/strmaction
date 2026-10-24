import 'dart:async';

/// Bound platform work independently of gesture frame rate. Only the newest
/// pending target is kept; a slow platform call never builds up a queue.
class LatestValueDispatcher<T extends Object> {
  final Future<void> Function(T) apply;
  final void Function(Object) onError;
  final Duration interval;
  T? _pending;
  Timer? _timer;
  Future<void>? _active;
  bool _disposed = false;

  LatestValueDispatcher({required this.apply, required this.onError,
    this.interval = const Duration(milliseconds: 40)});

  void schedule(T value) {
    if (_disposed) return;
    _pending = value;
    _schedule();
  }

  void _schedule() {
    if (_disposed || _active != null || _timer != null || _pending == null) return;
    _timer = Timer(interval, () { _timer = null; unawaited(_send()); });
  }

  Future<void> _send() {
    if (_active != null) return _active!;
    final value = _pending;
    if (_disposed || value == null) return Future<void>.value();
    _pending = null;
    _active = Future<void>.sync(() => apply(value)).catchError((Object error) {
      onError(error);
    }).whenComplete(() { _active = null; _schedule(); });
    return _active!;
  }

  Future<void> flush() async {
    do {
      _timer?.cancel(); _timer = null;
      await (_active ?? _send());
    } while (!_disposed && _pending != null);
  }

  void dispose() {
    _disposed = true;
    cancelPending();
  }

  void cancelPending() {
    _pending = null;
    _timer?.cancel(); _timer = null;
  }
}
