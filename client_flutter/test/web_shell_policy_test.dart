import 'package:flutter_test/flutter_test.dart';
import 'package:strmaction_desktop/web/web_shell_policy.dart';

void main() {
  test('only allows the configured server origin in the WebView', () {
    const server = 'https://media.example.com';
    expect(
      isAllowedWebShellUrl(Uri.parse('https://media.example.com/home'), server),
      isTrue,
    );
    expect(
      isAllowedWebShellUrl(Uri.parse('https://evil.example.com/home'), server),
      isFalse,
    );
    expect(
      isAllowedWebShellUrl(Uri.parse('file:///etc/passwd'), server),
      isFalse,
    );
    expect(
      isAllowedWebShellUrl(Uri.parse('data:text/html,hello'), server),
      isFalse,
    );
    expect(
      isAllowedWebShellUrl(Uri.parse('http://media.example.com/home'), server),
      isFalse,
    );
  });

  test('external navigation is limited to http(s)', () {
    expect(shouldOpenExternally(Uri.parse('https://example.com')), isTrue);
    expect(shouldOpenExternally(Uri.parse('file:///tmp/x')), isFalse);
  });
}
