import 'package:flutter/widgets.dart';

/// 在 document-start 注入当前方向的系统安全区，并接管顶部和左右留白。
///
/// Flutter 壳现在把 WebView 放进刘海/挖孔的安全区里，所以页面自己不能再为
/// 顶部和左右加 padding，否则会双倍留白；而旧版网页只认识 `env()`，在
/// Android WebView 上通常返回 0。这里用 `!important` 覆盖 `.safe-top` /
/// `.safe-x`，无论服务器上的前端是新版还是旧版，首页顶栏按钮都不会再落到
/// 摄像头下面。底部手势条不在壳层的收缩范围内，`.safe-bottom` 仍然由页面
/// 自己处理。
String buildWebShellSafeAreaScript(EdgeInsets insets) => '''
(function () {
  var root = document.documentElement;
  if (!root) return;
  root.style.setProperty('--safe-top-inset', '${insets.top.toStringAsFixed(1)}px');
  root.style.setProperty('--safe-right-inset', '${insets.right.toStringAsFixed(1)}px');
  root.style.setProperty('--safe-bottom-inset', '${insets.bottom.toStringAsFixed(1)}px');
  root.style.setProperty('--safe-left-inset', '${insets.left.toStringAsFixed(1)}px');
  var style = document.getElementById('strmaction-shell-safe-area');
  if (!style) {
    style = document.createElement('style');
    style.id = 'strmaction-shell-safe-area';
    (document.head || root).appendChild(style);
  }
  style.textContent =
    '.safe-top{padding-top:0!important}' +
    '.safe-x{padding-left:0!important;padding-right:0!important}';
})();
''';
