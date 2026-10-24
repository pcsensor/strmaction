import 'dart:async';

import 'package:flutter/services.dart';
import 'package:flutter/widgets.dart';

class PlayerKeyboardHandler {
  final VoidCallback onPlayPause;
  final ValueChanged<double> onSeekRelative;
  final ValueChanged<double> onSpeedBoostStarted;
  final VoidCallback onSpeedBoostEnded;
  final ValueChanged<int> onVolumeRelative;
  final VoidCallback onMute;
  final VoidCallback onFullscreen;
  final VoidCallback onEscape;
  final VoidCallback onPreviousEpisode;
  final VoidCallback onNextEpisode;
  final VoidCallback onCycleSubtitle;
  final VoidCallback onCycleAudio;
  final VoidCallback onToggleDrawer;

  double boostSpeed;
  bool _rightPressed = false;
  bool _boostActive = false;
  Timer? _holdTimer;

  PlayerKeyboardHandler({
    required this.onPlayPause,
    required this.onSeekRelative,
    required this.onSpeedBoostStarted,
    required this.onSpeedBoostEnded,
    required this.onVolumeRelative,
    required this.onMute,
    required this.onFullscreen,
    required this.onEscape,
    required this.onPreviousEpisode,
    required this.onNextEpisode,
    required this.onCycleSubtitle,
    required this.onCycleAudio,
    required this.onToggleDrawer,
    this.boostSpeed = 2.0,
  });

  KeyEventResult handle(FocusNode node, KeyEvent event) {
    try {
      if (FocusManager.instance.primaryFocus?.context?.widget is EditableText) {
        return KeyEventResult.ignored;
      }
    } catch (_) {
      // Binding not initialized (e.g. in test environments without a widget tree)
    }

    final key = event.logicalKey;
    final repeat = event is KeyRepeatEvent;

    if (key == LogicalKeyboardKey.arrowRight) {
      if (event is KeyDownEvent) {
        if (!repeat) {
          _rightPressed = true;
          _boostActive = false;
          _holdTimer?.cancel();
          _holdTimer = Timer(const Duration(milliseconds: 250), () {
            if (_rightPressed) {
              _boostActive = true;
              onSpeedBoostStarted(boostSpeed);
            }
          });
        }
        return KeyEventResult.handled;
      }
      if (event is KeyUpEvent) {
        if (repeat) return KeyEventResult.handled;
        _rightPressed = false;
        _holdTimer?.cancel();
        _holdTimer = null;
        if (_boostActive) {
          _boostActive = false;
          onSpeedBoostEnded();
        } else {
          onSeekRelative(5);
        }
        return KeyEventResult.handled;
      }
      return KeyEventResult.handled;
    }

    if (repeat) {
      if (key == LogicalKeyboardKey.arrowUp) {
        onVolumeRelative(5);
        return KeyEventResult.handled;
      }
      if (key == LogicalKeyboardKey.arrowDown) {
        onVolumeRelative(-5);
        return KeyEventResult.handled;
      }
      if (_isHandledKey(key)) {
        return KeyEventResult.handled;
      }
      return KeyEventResult.ignored;
    }

    if (event is KeyUpEvent) {
      if (_isHandledKey(key)) {
        return KeyEventResult.handled;
      }
      return KeyEventResult.ignored;
    }

    if (event is! KeyDownEvent) {
      return KeyEventResult.ignored;
    }

    if (key == LogicalKeyboardKey.space) {
      onPlayPause();
      return KeyEventResult.handled;
    }
    if (key == LogicalKeyboardKey.arrowLeft) {
      onSeekRelative(-5);
      return KeyEventResult.handled;
    }
    if (key == LogicalKeyboardKey.arrowUp) {
      onVolumeRelative(5);
      return KeyEventResult.handled;
    }
    if (key == LogicalKeyboardKey.arrowDown) {
      onVolumeRelative(-5);
      return KeyEventResult.handled;
    }
    if (key == LogicalKeyboardKey.keyM) {
      onMute();
      return KeyEventResult.handled;
    }
    if (key == LogicalKeyboardKey.keyF || key == LogicalKeyboardKey.f11) {
      onFullscreen();
      return KeyEventResult.handled;
    }
    if (key == LogicalKeyboardKey.escape) {
      onEscape();
      return KeyEventResult.handled;
    }
    if (key == LogicalKeyboardKey.bracketLeft) {
      onPreviousEpisode();
      return KeyEventResult.handled;
    }
    if (key == LogicalKeyboardKey.bracketRight) {
      onNextEpisode();
      return KeyEventResult.handled;
    }
    if (key == LogicalKeyboardKey.keyC || key == LogicalKeyboardKey.keyS) {
      onCycleSubtitle();
      return KeyEventResult.handled;
    }
    if (key == LogicalKeyboardKey.keyA) {
      onCycleAudio();
      return KeyEventResult.handled;
    }
    if (key == LogicalKeyboardKey.keyE || key == LogicalKeyboardKey.tab) {
      onToggleDrawer();
      return KeyEventResult.handled;
    }
    return KeyEventResult.ignored;
  }

  bool _isHandledKey(LogicalKeyboardKey key) {
    return key == LogicalKeyboardKey.space ||
        key == LogicalKeyboardKey.arrowLeft ||
        key == LogicalKeyboardKey.arrowUp ||
        key == LogicalKeyboardKey.arrowDown ||
        key == LogicalKeyboardKey.keyM ||
        key == LogicalKeyboardKey.keyF ||
        key == LogicalKeyboardKey.f11 ||
        key == LogicalKeyboardKey.escape ||
        key == LogicalKeyboardKey.bracketLeft ||
        key == LogicalKeyboardKey.bracketRight ||
        key == LogicalKeyboardKey.keyC ||
        key == LogicalKeyboardKey.keyS ||
        key == LogicalKeyboardKey.keyA ||
        key == LogicalKeyboardKey.keyE ||
        key == LogicalKeyboardKey.tab;
  }

  void cancelBoost() {
    _rightPressed = false;
    _holdTimer?.cancel();
    _holdTimer = null;
    if (_boostActive) {
      _boostActive = false;
      onSpeedBoostEnded();
    }
  }

  void dispose() {
    _holdTimer?.cancel();
  }
}
