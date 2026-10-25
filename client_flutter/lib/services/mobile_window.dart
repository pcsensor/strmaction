import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart';

const _mobilePlatforms = {TargetPlatform.android, TargetPlatform.iOS};

void _applyMobileOverlayStyle() {
  SystemChrome.setSystemUIOverlayStyle(const SystemUiOverlayStyle(
    statusBarColor: Color(0x00000000),
    systemNavigationBarColor: Color(0x00000000),
    statusBarIconBrightness: Brightness.light,
    statusBarBrightness: Brightness.dark,
    systemNavigationBarIconBrightness: Brightness.light,
  ));
}

/// 隐藏或恢复系统状态栏 / 导航栏，但不改变屏幕方向。
///
/// 播放页一打开就用它进入沉浸式：控制栏和画面要铺满整块屏幕，而不是被
/// 状态栏和手势条挤在中间。全屏按钮另外再锁定横屏。
Future<void> setMobileImmersive(bool immersive) =>
    setMobileFullscreen(false, keepImmersive: immersive);

/// 切换移动端全屏：隐藏系统栏并按需锁定横屏，退出时恢复系统栏与方向。
///
/// [keepImmersive] 用于「退出横屏全屏但仍在播放页」：方向解锁，系统栏
/// 继续保持隐藏，避免控制栏又缩回系统栏之间。
Future<void> setMobileFullscreen(
  bool fullscreen, {
  bool keepImmersive = false,
}) async {
  final platform = defaultTargetPlatform;
  if (!_mobilePlatforms.contains(platform)) return;
  _applyMobileOverlayStyle();
  final immersive = fullscreen || keepImmersive;
  try {
    await SystemChrome.setEnabledSystemUIMode(
      immersive ? SystemUiMode.immersiveSticky : SystemUiMode.edgeToEdge,
    );
  } on Object {
    // 系统栏设置失败（例如测试环境、窗口已销毁）不应阻断播放器。
  }
  try {
    await SystemChrome.setPreferredOrientations(fullscreen
        ? [DeviceOrientation.landscapeLeft, DeviceOrientation.landscapeRight]
        : DeviceOrientation.values);
  } on Object {
    // 方向锁定失败同样只影响沉浸式外观。
  }
  // Flutter 的旧版沉浸标志在 target SDK 36 上会被忽略，Android 原生侧
  // 负责隐藏系统栏并保持窗口 edge-to-edge。
  if (platform == TargetPlatform.android) {
    try {
      await const MethodChannel('strmaction/native')
          .invokeMethod<void>('fullscreen', immersive);
    } on Object {
      // 桌面测试环境或尚未注册的原生通道：Flutter 侧的系统栏设置已生效。
    }
  }
}
