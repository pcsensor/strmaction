import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';

import 'buffered_seekbar.dart';

enum PlayerGestureKind { brightness, volume, seek }

class PlayerGestureValue {
  final PlayerGestureKind kind;
  final double value;
  final double duration;
  const PlayerGestureValue(this.kind, this.value, {this.duration = 0});
}

/// Kept outside the control bars so feedback remains visible when they hide.
/// Its notifier rebuilds this small layer without rebuilding native video.
class PlayerGestureFeedback extends StatelessWidget {
  final ValueListenable<PlayerGestureValue?> feedback;
  const PlayerGestureFeedback({super.key, required this.feedback});

  @override
  Widget build(BuildContext context) => IgnorePointer(child: RepaintBoundary(
    child: ValueListenableBuilder<PlayerGestureValue?>(
      valueListenable: feedback,
      builder: (context, value, child) => Center(child: AnimatedSwitcher(
        duration: const Duration(milliseconds: 180),
        transitionBuilder: (child, animation) => FadeTransition(opacity: animation,
          child: ScaleTransition(scale: Tween<double>(begin: 0.94, end: 1).animate(animation), child: child)),
        child: value == null ? const SizedBox.shrink() : _FeedbackCard(key: ValueKey(value.kind), value: value),
      )),
    ),
  ));
}

class _FeedbackCard extends StatelessWidget {
  final PlayerGestureValue value;
  const _FeedbackCard({super.key, required this.value});

  @override
  Widget build(BuildContext context) {
    final seeking = value.kind == PlayerGestureKind.seek;
    final label = switch (value.kind) {
      PlayerGestureKind.brightness => '亮度',
      PlayerGestureKind.volume => '音量',
      PlayerGestureKind.seek => '播放位置',
    };
    final icon = switch (value.kind) {
      PlayerGestureKind.brightness => Icons.brightness_6_rounded,
      PlayerGestureKind.volume => value.value <= 0 ? Icons.volume_off_rounded : Icons.volume_up_rounded,
      PlayerGestureKind.seek => Icons.swap_horiz_rounded,
    };
    final progress = seeking
        ? (value.duration > 0 ? value.value / value.duration : 0.0)
        : value.value;
    final text = seeking ? '${formatTime(value.value)} / ${formatTime(value.duration)}'
        : '$label ${(value.value * 100).round()}%';
    return Container(
      key: const ValueKey('player-gesture-feedback'),
      width: 190,
      padding: const EdgeInsets.symmetric(horizontal: 22, vertical: 18),
      decoration: BoxDecoration(color: const Color(0xE610141B),
        borderRadius: BorderRadius.circular(18),
        border: Border.all(color: const Color(0x25FFFFFF))),
      child: Column(mainAxisSize: MainAxisSize.min, children: [
        Icon(icon, color: Colors.white, size: 32),
        const SizedBox(height: 10),
        Text(text, style: const TextStyle(color: Colors.white, fontSize: 16, fontWeight: FontWeight.w600)),
        const SizedBox(height: 12),
        TweenAnimationBuilder<double>(
          tween: Tween<double>(begin: progress.clamp(0, 1), end: progress.clamp(0, 1)),
          duration: const Duration(milliseconds: 80),
          builder: (context, level, child) => LinearProgressIndicator(
            key: const ValueKey('player-gesture-level'),
            value: level, minHeight: 4, borderRadius: BorderRadius.circular(2),
            color: const Color(0xFFF0A94D), backgroundColor: const Color(0x33FFFFFF)),
        ),
      ]),
    );
  }
}
