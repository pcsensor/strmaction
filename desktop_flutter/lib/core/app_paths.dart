import 'dart:io';

import 'package:path/path.dart' as p;

import 'version.dart';

/// Filesystem locations used by the desktop app.
///
/// The paths intentionally match the old Python desktop app so that existing
/// users keep their server address, cache setting and log files.
class AppPaths {
  final String baseDir;

  const AppPaths(this.baseDir);

  factory AppPaths.forCurrentUser() {
    if (Platform.isMacOS) {
      final home = Platform.environment['HOME'] ?? '';
      return AppPaths(
        p.join(home, 'Library', 'Application Support', appName),
      );
    }
    if (Platform.isWindows) {
      final appData = Platform.environment['APPDATA'];
      if (appData != null && appData.isNotEmpty) {
        return AppPaths(p.join(appData, appName));
      }
      return AppPaths(p.join(Directory.current.path, appName));
    }
    final xdg = Platform.environment['XDG_CONFIG_HOME'];
    if (xdg != null && xdg.isNotEmpty) {
      return AppPaths(p.join(xdg, appName));
    }
    final home = Platform.environment['HOME'] ?? Directory.current.path;
    return AppPaths(p.join(home, '.config', appName));
  }

  String get configFile => p.join(baseDir, 'config.json');

  String get logDir => p.join(baseDir, 'logs');

  String get logFile => p.join(logDir, 'desktop.log');

  String get webviewDir => p.join(baseDir, 'webview');

  String get webviewCacheDir => p.join(baseDir, 'webview-cache');

  String get webviewDataDir => p.join(baseDir, 'webview2');

  void ensureDirectories() {
    Directory(baseDir).createSync(recursive: true);
    Directory(logDir).createSync(recursive: true);
    Directory(webviewDir).createSync(recursive: true);
    Directory(webviewCacheDir).createSync(recursive: true);
  }
}
