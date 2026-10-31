import 'dart:io';

class UnsafeMediaRedirect extends HttpException {
  const UnsafeMediaRedirect() : super('片源重定向协议不安全');
}

/// Only non-secret compatibility headers follow a media redirect to another origin.
bool forwardMediaHeader(Uri origin, Uri target, String name) {
  final sameOrigin =
      origin.scheme == target.scheme &&
      origin.host == target.host &&
      origin.port == target.port;
  return sameOrigin ||
      const {
        'user-agent',
        'referer',
        'accept',
        'accept-language',
      }.contains(name.toLowerCase());
}

Uri checkedMediaRedirect(Uri current, String location) {
  final next = current.resolve(location);
  if (!['http', 'https'].contains(next.scheme) ||
      (current.scheme == 'https' && next.scheme != 'https')) {
    throw const UnsafeMediaRedirect();
  }
  return next;
}
