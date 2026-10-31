/// WebView 只允许加载 StrmAction 服务器自身的 http/https 页面。
/// 媒体播放地址不经过这里，由原生播放器按自己的 CA 策略连接。
bool isAllowedWebShellUrl(Uri uri, String serverUrl) {
  // 空白子框架是 WebView 内部常用页面，不加载任何外部内容。
  if (uri.scheme == 'about' && uri.path == 'blank') return true;
  if (uri.scheme != 'http' && uri.scheme != 'https') return false;
  final server = Uri.tryParse(serverUrl);
  if (server == null || server.host.isEmpty) return false;
  if (uri.scheme != server.scheme || uri.host != server.host) return false;
  final serverPort = server.hasPort
      ? server.port
      : (server.scheme == 'https' ? 443 : 80);
  final uriPort = uri.hasPort ? uri.port : (uri.scheme == 'https' ? 443 : 80);
  return uriPort == serverPort;
}

/// 非服务器 origin 的 http/https 链接交给外部浏览器；其它协议直接拒绝。
bool shouldOpenExternally(Uri uri) =>
    uri.scheme == 'http' || uri.scheme == 'https';
