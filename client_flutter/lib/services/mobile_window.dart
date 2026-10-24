import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart';

/// Keep the library edge-to-edge and restore system bars when leaving playback.
Future<void> setMobileFullscreen(bool fullscreen) async {
  final platform = defaultTargetPlatform;
  if (platform != TargetPlatform.android && platform != TargetPlatform.iOS) return;
  SystemChrome.setSystemUIOverlayStyle(const SystemUiOverlayStyle(
    statusBarColor: Color(0x00000000),
    systemNavigationBarColor: Color(0x00000000),
    statusBarIconBrightness: Brightness.light,
    statusBarBrightness: Brightness.dark,
    systemNavigationBarIconBrightness: Brightness.light,
  ));
  await SystemChrome.setEnabledSystemUIMode(
    fullscreen ? SystemUiMode.immersiveSticky : SystemUiMode.edgeToEdge,
  );
  await SystemChrome.setPreferredOrientations(fullscreen
      ? [DeviceOrientation.landscapeLeft, DeviceOrientation.landscapeRight]
      : DeviceOrientation.values);
  // Flutter's legacy immersive flags are ignored at target SDK 36. The native
  // controller hides bars while keeping the window edge-to-edge on Android.
  if (platform == TargetPlatform.android) {
    await const MethodChannel('strmaction/native')
        .invokeMethod<void>('fullscreen', fullscreen);
  }
}
