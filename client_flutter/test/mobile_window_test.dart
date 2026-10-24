import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:strmaction_desktop/services/mobile_window.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  for (final platform in [TargetPlatform.android, TargetPlatform.iOS]) {
    test('$platform restores bars and orientations after fullscreen', () async {
      debugDefaultTargetPlatformOverride = platform;
      addTearDown(() => debugDefaultTargetPlatformOverride = null);
      final native = <MethodCall>[];
      final system = <MethodCall>[];
      final messenger = TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger;
      const channel = MethodChannel('strmaction/native');
      messenger.setMockMethodCallHandler(channel, (call) async { native.add(call); return null; });
      messenger.setMockMethodCallHandler(SystemChannels.platform, (call) async { system.add(call); return null; });
      addTearDown(() {
        messenger.setMockMethodCallHandler(channel, null);
        messenger.setMockMethodCallHandler(SystemChannels.platform, null);
      });
      await setMobileFullscreen(true);
      await setMobileFullscreen(false);
      expect(system.where((c) => c.method == 'SystemChrome.setEnabledSystemUIMode').map((c) => c.arguments),
        ['SystemUiMode.immersiveSticky', 'SystemUiMode.edgeToEdge']);
      final orientations = system.where((c) => c.method == 'SystemChrome.setPreferredOrientations').toList();
      expect(orientations.first.arguments, ['DeviceOrientation.landscapeLeft', 'DeviceOrientation.landscapeRight']);
      expect(orientations.last.arguments, hasLength(4));
      expect(native.map((c) => c.arguments), platform == TargetPlatform.android ? [true, false] : isEmpty);
    });
  }
}
