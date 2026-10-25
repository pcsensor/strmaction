import 'package:flutter/material.dart';

import 'app_icons.dart';

/// Transient playback feedback: play/pause, volume, mute, seek, "缓冲中".
///
/// This used to live inside [ControlsOverlay]'s faded layer, so a keyboard
/// shortcut pressed while the controls were hidden changed the state without
/// showing anything. The hint must stay visible even when the bar is gone.
class PlayerCenterStatus extends StatelessWidget {
  final String? iconPath;
  final String? text;
  final bool showIcon;
  final bool showText;
  final bool loading;

  const PlayerCenterStatus({
    super.key,
    this.iconPath,
    this.text,
    this.showIcon = false,
    this.showText = false,
    this.loading = false,
  });

  @override
  Widget build(BuildContext context) {
    final insets = MediaQuery.viewPaddingOf(context);
    final hasBadge = (showIcon && iconPath != null) || (showText && text != null);
    final children = <Widget>[
      if (showIcon && iconPath != null)
        Container(
          padding: const EdgeInsets.all(18),
          decoration: const BoxDecoration(
            color: Color(0x99000000),
            shape: BoxShape.circle,
          ),
          child: AppIcons.icon(iconPath!, size: 44),
        ),
      if (showText && text != null)
        Container(
          margin: const EdgeInsets.only(top: 10),
          padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
          decoration: BoxDecoration(
            color: const Color(0xCC000000),
            borderRadius: BorderRadius.circular(18),
            border: Border.all(color: const Color(0x33FFFFFF)),
          ),
          child: Text(
            text!,
            style: const TextStyle(
              color: Colors.white,
              fontSize: 16,
              fontWeight: FontWeight.bold,
            ),
          ),
        ),
      if (loading)
        Container(
          margin: EdgeInsets.only(top: hasBadge ? 10 : 0),
          padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 6),
          decoration: BoxDecoration(
            color: const Color(0xB3000000),
            borderRadius: BorderRadius.circular(14),
          ),
          child: const Text(
            '缓冲中...',
            style: TextStyle(color: Color(0xFFB0B3B8), fontSize: 13),
          ),
        ),
    ];
    if (children.isEmpty) return const SizedBox.shrink();
    return LayoutBuilder(
      builder: (context, constraints) {
        final compact = constraints.maxWidth - insets.horizontal < 650;
        final bottom = (compact ? 124.0 : 88.0) + insets.bottom;
        return Padding(
          // Keep the badge centred in the video area, above the bottom bar even
          // while the bar is faded out.
          padding: EdgeInsets.only(
            top: 72 + insets.top,
            bottom: bottom,
            left: insets.left,
            right: insets.right,
          ),
          child: IgnorePointer(
            child: Center(
              child: Column(mainAxisSize: MainAxisSize.min, children: children),
            ),
          ),
        );
      },
    );
  }
}
