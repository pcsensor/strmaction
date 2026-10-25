import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:strmaction_desktop/services/mobile_window.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  Future<({List<MethodCall> native, List<MethodCall> system, VoidCallback clear})>
      mockChannels() async {
    final native = <MethodCall>[];
    final system = <MethodCall>[];
    final messenger = TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger;
    const channel = MethodChannel('strmaction/native');
    messenger.setMockMethodCallHandler(channel, (call) async {
      native.add(call);
      return null;
    });
    messenger.setMockMethodCallHandler(SystemChannels.platform, (call) async {
      system.add(call);
      return null;
    });
    return (
      native: native,
      system: system,
      clear: () {
        messenger.setMockMethodCallHandler(channel, null);
        messenger.setMockMethodCallHandler(SystemChannels.platform, null);
      },
    );
  }

  for (final platform in [TargetPlatform.android, TargetPlatform.iOS]) {
    test('$platform restores bars and orientations after fullscreen', () async {
      debugDefaultTargetPlatformOverride = platform;
      addTearDown(() => debugDefaultTargetPlatformOverride = null);
      final mocked = await mockChannels();
      addTearDown(mocked.clear);
      await setMobileFullscreen(true);
      await setMobileFullscreen(false);
      expect(
        mocked.system
            .where((c) => c.method == 'SystemChrome.setEnabledSystemUIMode')
            .map((c) => c.arguments),
        ['SystemUiMode.immersiveSticky', 'SystemUiMode.edgeToEdge'],
      );
      final orientations =
          mocked.system.where((c) => c.method == 'SystemChrome.setPreferredOrientations').toList();
      expect(
        orientations.first.arguments,
        ['DeviceOrientation.landscapeLeft', 'DeviceOrientation.landscapeRight'],
      );
      expect(orientations.last.arguments, hasLength(4));
      expect(
        mocked.native.map((c) => c.arguments),
        platform == TargetPlatform.android ? [true, false] : isEmpty,
      );
    });

    test('$platform keeps the bars hidden when leaving landscape inside the player',
        () async {
      debugDefaultTargetPlatformOverride = platform;
      addTearDown(() => debugDefaultTargetPlatformOverride = null);
      final mocked = await mockChannels();
      addTearDown(mocked.clear);
      await setMobileImmersive(true);
      await setMobileFullscreen(false, keepImmersive: true);
      expect(
        mocked.system
            .where((c) => c.method == 'SystemChrome.setEnabledSystemUIMode')
            .map((c) => c.arguments),
        ['SystemUiMode.immersiveSticky', 'SystemUiMode.immersiveSticky'],
      );
      final last = mocked.system
          .where((c) => c.method == 'SystemChrome.setPreferredOrientations')
          .last;
      expect(last.arguments, hasLength(4));
      expect(
        mocked.native.map((c) => c.arguments),
        platform == TargetPlatform.android ? [true, true] : isEmpty,
      );
    });
  }
}
