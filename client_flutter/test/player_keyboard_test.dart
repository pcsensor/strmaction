import 'package:flutter/services.dart';
import 'package:flutter/widgets.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:strmaction_desktop/player/input/player_keyboard.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  group('PlayerKeyboardHandler', () {
    test('space key triggers play/pause only once on press, not on release or repeat', () {
      int playPauseCalls = 0;
      final handler = PlayerKeyboardHandler(
        onPlayPause: () => playPauseCalls++,
        onSeekRelative: (_) {},
        onSpeedBoostStarted: (_) {},
        onSpeedBoostEnded: () {},
        onVolumeRelative: (_) {},
        onMute: () {},
        onFullscreen: () {},
        onEscape: () {},
        onPreviousEpisode: () {},
        onNextEpisode: () {},
        onCycleSubtitle: () {},
        onCycleAudio: () {},
        onToggleDrawer: () {},
      );

      final node = FocusNode();

      // 1. KeyDown
      final downResult = handler.handle(
        node,
        const KeyDownEvent(
          physicalKey: PhysicalKeyboardKey.space,
          logicalKey: LogicalKeyboardKey.space,
          timeStamp: Duration.zero,
        ),
      );
      expect(downResult, KeyEventResult.handled);
      expect(playPauseCalls, 1);

      // 2. KeyRepeat (holding down space)
      final repeatResult = handler.handle(
        node,
        const KeyRepeatEvent(
          physicalKey: PhysicalKeyboardKey.space,
          logicalKey: LogicalKeyboardKey.space,
          timeStamp: Duration(milliseconds: 100),
        ),
      );
      expect(repeatResult, KeyEventResult.handled);
      expect(playPauseCalls, 1, reason: 'Repeat should not toggle play/pause again');

      // 3. KeyUp (releasing space)
      final upResult = handler.handle(
        node,
        const KeyUpEvent(
          physicalKey: PhysicalKeyboardKey.space,
          logicalKey: LogicalKeyboardKey.space,
          timeStamp: Duration(milliseconds: 200),
        ),
      );
      expect(upResult, KeyEventResult.handled);
      expect(playPauseCalls, 1, reason: 'KeyUp must NOT toggle play/pause again');

      node.dispose();
      handler.dispose();
    });

    test('other action hotkeys only trigger on KeyDownEvent', () {
      int muteCalls = 0;
      int fullscreenCalls = 0;
      int prevEpisodeCalls = 0;
      int nextEpisodeCalls = 0;
      int drawerCalls = 0;
      double seekAmount = 0;
      int volumeDelta = 0;

      final handler = PlayerKeyboardHandler(
        onPlayPause: () {},
        onSeekRelative: (v) => seekAmount += v,
        onSpeedBoostStarted: (_) {},
        onSpeedBoostEnded: () {},
        onVolumeRelative: (v) => volumeDelta += v,
        onMute: () => muteCalls++,
        onFullscreen: () => fullscreenCalls++,
        onEscape: () {},
        onPreviousEpisode: () => prevEpisodeCalls++,
        onNextEpisode: () => nextEpisodeCalls++,
        onCycleSubtitle: () {},
        onCycleAudio: () {},
        onToggleDrawer: () => drawerCalls++,
      );

      final node = FocusNode();

      // M key (mute)
      handler.handle(
        node,
        const KeyDownEvent(
          physicalKey: PhysicalKeyboardKey.keyM,
          logicalKey: LogicalKeyboardKey.keyM,
          timeStamp: Duration.zero,
        ),
      );
      expect(muteCalls, 1);
      handler.handle(
        node,
        const KeyUpEvent(
          physicalKey: PhysicalKeyboardKey.keyM,
          logicalKey: LogicalKeyboardKey.keyM,
          timeStamp: Duration.zero,
        ),
      );
      expect(muteCalls, 1);

      // F key (fullscreen)
      handler.handle(
        node,
        const KeyDownEvent(
          physicalKey: PhysicalKeyboardKey.keyF,
          logicalKey: LogicalKeyboardKey.keyF,
          timeStamp: Duration.zero,
        ),
      );
      expect(fullscreenCalls, 1);
      handler.handle(
        node,
        const KeyUpEvent(
          physicalKey: PhysicalKeyboardKey.keyF,
          logicalKey: LogicalKeyboardKey.keyF,
          timeStamp: Duration.zero,
        ),
      );
      expect(fullscreenCalls, 1);

      // ArrowLeft (seek -5)
      handler.handle(
        node,
        const KeyDownEvent(
          physicalKey: PhysicalKeyboardKey.arrowLeft,
          logicalKey: LogicalKeyboardKey.arrowLeft,
          timeStamp: Duration.zero,
        ),
      );
      expect(seekAmount, -5.0);
      handler.handle(
        node,
        const KeyUpEvent(
          physicalKey: PhysicalKeyboardKey.arrowLeft,
          logicalKey: LogicalKeyboardKey.arrowLeft,
          timeStamp: Duration.zero,
        ),
      );
      expect(seekAmount, -5.0, reason: 'KeyUp should not seek again');

      // Previous and Next episode
      handler.handle(
        node,
        const KeyDownEvent(
          physicalKey: PhysicalKeyboardKey.bracketLeft,
          logicalKey: LogicalKeyboardKey.bracketLeft,
          timeStamp: Duration.zero,
        ),
      );
      handler.handle(
        node,
        const KeyUpEvent(
          physicalKey: PhysicalKeyboardKey.bracketLeft,
          logicalKey: LogicalKeyboardKey.bracketLeft,
          timeStamp: Duration.zero,
        ),
      );
      expect(prevEpisodeCalls, 1);

      handler.handle(
        node,
        const KeyDownEvent(
          physicalKey: PhysicalKeyboardKey.bracketRight,
          logicalKey: LogicalKeyboardKey.bracketRight,
          timeStamp: Duration.zero,
        ),
      );
      handler.handle(
        node,
        const KeyUpEvent(
          physicalKey: PhysicalKeyboardKey.bracketRight,
          logicalKey: LogicalKeyboardKey.bracketRight,
          timeStamp: Duration.zero,
        ),
      );
      expect(nextEpisodeCalls, 1);

      // Drawer
      handler.handle(
        node,
        const KeyDownEvent(
          physicalKey: PhysicalKeyboardKey.keyE,
          logicalKey: LogicalKeyboardKey.keyE,
          timeStamp: Duration.zero,
        ),
      );
      handler.handle(
        node,
        const KeyUpEvent(
          physicalKey: PhysicalKeyboardKey.keyE,
          logicalKey: LogicalKeyboardKey.keyE,
          timeStamp: Duration.zero,
        ),
      );
      expect(drawerCalls, 1);

      // Volume up repeat
      handler.handle(
        node,
        const KeyDownEvent(
          physicalKey: PhysicalKeyboardKey.arrowUp,
          logicalKey: LogicalKeyboardKey.arrowUp,
          timeStamp: Duration.zero,
        ),
      );
      expect(volumeDelta, 5);
      handler.handle(
        node,
        const KeyRepeatEvent(
          physicalKey: PhysicalKeyboardKey.arrowUp,
          logicalKey: LogicalKeyboardKey.arrowUp,
          timeStamp: Duration.zero,
        ),
      );
      expect(volumeDelta, 10);
      handler.handle(
        node,
        const KeyUpEvent(
          physicalKey: PhysicalKeyboardKey.arrowUp,
          logicalKey: LogicalKeyboardKey.arrowUp,
          timeStamp: Duration.zero,
        ),
      );
      expect(volumeDelta, 10);

      node.dispose();
      handler.dispose();
    });

    test('boostSpeed can be configured and updated dynamically', () async {
      double? boostedSpeed;
      bool boostEnded = false;

      final handler = PlayerKeyboardHandler(
        onPlayPause: () {},
        onSeekRelative: (_) {},
        onSpeedBoostStarted: (speed) => boostedSpeed = speed,
        onSpeedBoostEnded: () => boostEnded = true,
        onVolumeRelative: (_) {},
        onMute: () {},
        onFullscreen: () {},
        onEscape: () {},
        onPreviousEpisode: () {},
        onNextEpisode: () {},
        onCycleSubtitle: () {},
        onCycleAudio: () {},
        onToggleDrawer: () {},
        boostSpeed: 3.5,
      );

      expect(handler.boostSpeed, 3.5);

      final node = FocusNode();

      handler.handle(
        node,
        const KeyDownEvent(
          physicalKey: PhysicalKeyboardKey.arrowRight,
          logicalKey: LogicalKeyboardKey.arrowRight,
          timeStamp: Duration.zero,
        ),
      );

      // Boost triggers after 250ms hold
      await Future<void>.delayed(const Duration(milliseconds: 300));
      expect(boostedSpeed, 3.5);

      handler.handle(
        node,
        const KeyUpEvent(
          physicalKey: PhysicalKeyboardKey.arrowRight,
          logicalKey: LogicalKeyboardKey.arrowRight,
          timeStamp: Duration(milliseconds: 300),
        ),
      );
      expect(boostEnded, isTrue);

      // Update boost speed dynamically
      handler.boostSpeed = 2.5;
      expect(handler.boostSpeed, 2.5);

      node.dispose();
      handler.dispose();
    });
  });
}
