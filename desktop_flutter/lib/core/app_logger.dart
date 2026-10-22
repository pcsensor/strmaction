import 'dart:io';

import 'app_paths.dart';

enum LogLevel { debug, info, warning, error }

/// Small rotating file logger.
///
/// We deliberately do not use the `logging` package here: the app only needs
/// a file with a fixed size cap and a console mirror, and this keeps the
/// dependency surface small.
class AppLogger {
  final AppPaths paths;
  final bool debugEnabled;
  IOSink? _sink;

  AppLogger(this.paths, {this.debugEnabled = false});

  Future<void> initialize() async {
    try {
      await Directory(paths.logDir).create(recursive: true);
      await _openSink();
    } on Object {
      _sink = null;
    }
  }

  Future<void> _openSink() async {
    final file = File(paths.logFile);
    if (await file.exists() && await file.length() > 2 * 1024 * 1024) {
      await _rotate();
    }
    _sink = file.openWrite(mode: FileMode.append);
  }

  Future<void> _rotate() async {
    final file = File(paths.logFile);
    for (var i = 3; i >= 1; i--) {
      final source = File('${file.path}.$i');
      final target = File('${file.path}.${i + 1}');
      if (await source.exists()) {
        if (await target.exists()) await target.delete();
        await source.rename(target.path);
      }
    }
    if (await file.exists()) {
      final target = File('${file.path}.1');
      if (await target.exists()) await target.delete();
      await file.rename(target.path);
    }
  }

  void debug(String message) {
    if (!debugEnabled) return;
    _write(LogLevel.debug, message);
  }

  void info(String message) => _write(LogLevel.info, message);

  void warning(String message) => _write(LogLevel.warning, message);

  void error(String message, [Object? error, StackTrace? stack]) {
    final suffix = error == null ? '' : ': $error';
    _write(LogLevel.error, '$message$suffix');
    if (stack != null && debugEnabled) {
      _write(LogLevel.debug, stack.toString());
    }
  }

  void _write(LogLevel level, String message) {
    final now = DateTime.now();
    final stamp = '${now.year.toString().padLeft(4, '0')}-'
        '${now.month.toString().padLeft(2, '0')}-'
        '${now.day.toString().padLeft(2, '0')} '
        '${now.hour.toString().padLeft(2, '0')}:'
        '${now.minute.toString().padLeft(2, '0')}:'
        '${now.second.toString().padLeft(2, '0')}';
    final label = switch (level) {
      LogLevel.debug => 'DEBUG  ',
      LogLevel.info => 'INFO   ',
      LogLevel.warning => 'WARNING',
      LogLevel.error => 'ERROR  ',
    };
    final line = '$stamp $label strmaction_desktop: $message';
    stderr.writeln(line);
    try {
      _sink?.writeln(line);
    } on Object {
      // Logging must never break the app.
    }
  }

  Future<void> close() async {
    try {
      await _sink?.flush();
      await _sink?.close();
    } on Object {
      // ignore
    }
    _sink = null;
  }
}
