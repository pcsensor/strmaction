import 'package:flutter/material.dart';

import '../playback_engine.dart';
import 'app_icons.dart';
import 'buffered_seekbar.dart';

String formatNetworkSpeed(double? bytesPerSec) {
  if (bytesPerSec == null || !bytesPerSec.isFinite || bytesPerSec < 0) return '';
  if (bytesPerSec >= 1024 * 1024) {
    return '↓ ${(bytesPerSec / (1024 * 1024)).toStringAsFixed(1)} MB/s';
  }
  if (bytesPerSec >= 1024) {
    return '↓ ${(bytesPerSec / 1024).round()} KB/s';
  }
  return '↓ ${bytesPerSec.round()} B/s';
}

class ControlsOverlay extends StatelessWidget {
  final bool visible;
  final String title;
  final String seriesTitle;
  final double position;
  final double duration;
  final List<BufferedRange> bufferedRanges;
  final double speed;
  final bool paused;
  final bool fullscreen;
  final double? networkSpeed;
  final String? networkStatus;
  final bool hasPrevious;
  final bool hasNext;
  final bool speedBoost;
  final double speedBoostValue;
  final double trailingWidth;

  final VoidCallback onBack;
  final VoidCallback onPlayPause;
  final VoidCallback onPrevious;
  final VoidCallback onNext;
  final ValueChanged<double> onSeek;
  final ValueChanged<bool>? onSeekingChanged;
  final VoidCallback onSpeed;
  final VoidCallback onEpisodes;
  final VoidCallback onTracks;
  final VoidCallback onFrame;
  final VoidCallback onFullscreen;

  const ControlsOverlay({
    super.key,
    required this.visible,
    required this.title,
    required this.seriesTitle,
    required this.position,
    required this.duration,
    required this.bufferedRanges,
    required this.speed,
    required this.paused,
    required this.fullscreen,
    required this.networkSpeed,
    this.networkStatus,
    required this.hasPrevious,
    required this.hasNext,
    required this.speedBoost,
    required this.speedBoostValue,
    this.trailingWidth = 0,
    required this.onBack,
    required this.onPlayPause,
    required this.onPrevious,
    required this.onNext,
    required this.onSeek,
    required this.onSeekingChanged,
    required this.onSpeed,
    required this.onEpisodes,
    required this.onTracks,
    required this.onFrame,
    required this.onFullscreen,
  });

  @override
  Widget build(BuildContext context) {
    final fullTitle = seriesTitle.isNotEmpty && seriesTitle != title
        ? '$seriesTitle - $title'
        : title;
    final insets = MediaQuery.viewPaddingOf(context);
    final controls = IgnorePointer(
      ignoring: !visible,
      child: AnimatedOpacity(
        opacity: visible ? 1 : 0,
        duration: const Duration(milliseconds: 160),
        child: SizedBox.expand(
          child: LayoutBuilder(
            builder: (context, constraints) {
              final compact = constraints.maxWidth - insets.horizontal < 650;
              return Stack(
                children: [
                  Positioned(
                    top: 0,
                    left: 0,
                    right: 0,
                    child: _TopBar(title: fullTitle, onBack: onBack,
                      insets: insets, trailingWidth: trailingWidth),
                  ),
                  Positioned(
                    bottom: 0,
                    left: 0,
                    right: 0,
                    child: _BottomBar(
                      compact: compact,
                      insets: insets,
                      position: position,
                      duration: duration,
                      bufferedRanges: bufferedRanges,
                      speed: speed,
                      paused: paused,
                      fullscreen: fullscreen,
                      networkSpeed: networkSpeed,
                      networkStatus: networkStatus,
                      hasPrevious: hasPrevious,
                      hasNext: hasNext,
                      onPlayPause: onPlayPause,
                      onPrevious: onPrevious,
                      onNext: onNext,
                      onSeek: onSeek,
                      onSeekingChanged: onSeekingChanged,
                      onSpeed: onSpeed,
                      onEpisodes: onEpisodes,
                      onTracks: onTracks,
                      onFrame: onFrame,
                      onFullscreen: onFullscreen,
                    ),
                  ),
                ],
              );
            },
          ),
        ),
      ),
    );
    return Stack(children: [
      controls,
      if (speedBoost)
        Positioned(
          top: 78 + insets.top,
          left: insets.left,
          right: insets.right,
          child: IgnorePointer(
            child: Center(
              child: Container(
                key: const ValueKey('player-speed-boost'),
                padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 6),
                decoration: BoxDecoration(
                  color: const Color(0x73000000),
                  borderRadius: BorderRadius.circular(16),
                  border: Border.all(color: const Color(0x59F0A94D)),
                ),
                child: Text(
                  '⚡ ${_formatSpeed(speedBoostValue)} 极速播放中',
                  style: const TextStyle(
                    color: Color(0xFFF0A94D),
                    fontSize: 14,
                    fontWeight: FontWeight.bold,
                  ),
                ),
              ),
            ),
          ),
        ),
    ]);
  }

  static String _formatSpeed(double value) {
    final text = value.toStringAsFixed(2);
    return '${text.replaceFirst(RegExp(r'0+$'), '').replaceFirst(RegExp(r'\.$'), '')}x';
  }
}

class _TopBar extends StatelessWidget {
  final String title;
  final VoidCallback onBack;
  final EdgeInsets insets;
  final double trailingWidth;

  const _TopBar({required this.title, required this.onBack,
    required this.insets, required this.trailingWidth});

  @override
  Widget build(BuildContext context) {
    return Container(
      key: const ValueKey('player-top-bar'),
      height: 72 + insets.top,
      padding: EdgeInsets.only(left: 20 + insets.left,
        right: 20 + insets.right + trailingWidth, top: 14 + insets.top),
      decoration: const BoxDecoration(
        gradient: LinearGradient(
          begin: Alignment.topCenter,
          end: Alignment.bottomCenter,
          colors: [Color(0xB3000000), Color(0x00000000)],
        ),
      ),
      child: Row(
        children: [
          _CircleButton(
            iconPath: AppIcons.back,
            size: 24,
            onTap: onBack,
          ),
          const SizedBox(width: 14),
          Expanded(
            child: Text(
              title.isEmpty ? '正在加载...' : title,
              maxLines: 1,
              overflow: TextOverflow.ellipsis,
              style: const TextStyle(
                color: Colors.white,
                fontSize: 16,
                fontWeight: FontWeight.bold,
                shadows: [Shadow(color: Color(0xCC000000), blurRadius: 3)],
              ),
            ),
          ),
        ],
      ),
    );
  }
}

class _CircleButton extends StatelessWidget {
  final String iconPath;
  final double size;
  final VoidCallback onTap;

  const _CircleButton({
    required this.iconPath,
    required this.size,
    required this.onTap,
  });

  @override
  Widget build(BuildContext context) {
    return Material(
      color: const Color(0x66000000),
      shape: const CircleBorder(side: BorderSide(color: Color(0x26FFFFFF))),
      child: InkWell(
        customBorder: const CircleBorder(),
        onTap: onTap,
        child: SizedBox(
          width: 40,
          height: 40,
          child: Center(child: AppIcons.icon(iconPath, size: size)),
        ),
      ),
    );
  }
}

class _BottomBar extends StatefulWidget {
  final EdgeInsets insets;
  final bool compact;
  final double position;
  final double duration;
  final List<BufferedRange> bufferedRanges;
  final double speed;
  final bool paused;
  final bool fullscreen;
  final double? networkSpeed;
  final String? networkStatus;
  final bool hasPrevious;
  final bool hasNext;
  final VoidCallback onPlayPause;
  final VoidCallback onPrevious;
  final VoidCallback onNext;
  final ValueChanged<double> onSeek;
  final ValueChanged<bool>? onSeekingChanged;
  final VoidCallback onSpeed;
  final VoidCallback onEpisodes;
  final VoidCallback onTracks;
  final VoidCallback onFrame;
  final VoidCallback onFullscreen;

  const _BottomBar({
    required this.insets,
    required this.compact,
    required this.position,
    required this.duration,
    required this.bufferedRanges,
    required this.speed,
    required this.paused,
    required this.fullscreen,
    required this.networkSpeed,
    this.networkStatus,
    required this.hasPrevious,
    required this.hasNext,
    required this.onPlayPause,
    required this.onPrevious,
    required this.onNext,
    required this.onSeek,
    required this.onSeekingChanged,
    required this.onSpeed,
    required this.onEpisodes,
    required this.onTracks,
    required this.onFrame,
    required this.onFullscreen,
  });

  @override
  State<_BottomBar> createState() => _BottomBarState();
}

class _BottomBarState extends State<_BottomBar> {
  double? _previewPosition;

  @override
  Widget build(BuildContext context) {
    final time = Text(
      '${formatTime(_previewPosition ?? widget.position)} / ${formatTime(widget.duration)}',
      style: const TextStyle(color: Color(0xFFD1D5DB), fontSize: 13),
    );
    final networkText = widget.networkStatus ?? formatNetworkSpeed(widget.networkSpeed);
    final network = Text(networkText,
      style: const TextStyle(color: Color(0xFF9CA3AF), fontSize: 12));
    return Container(
      key: const ValueKey('player-bottom-bar'),
      height: (widget.compact ? 124 : 88) + widget.insets.bottom,
      padding: EdgeInsets.fromLTRB((widget.compact ? 12 : 20) + widget.insets.left, 0,
        (widget.compact ? 12 : 20) + widget.insets.right, 12 + widget.insets.bottom),
      decoration: const BoxDecoration(gradient: LinearGradient(
        begin: Alignment.topCenter, end: Alignment.bottomCenter,
        colors: [Color(0x00000000), Color(0xDC000000)],
      )),
      child: Column(children: [
        BufferedSeekBar(position: widget.position, duration: widget.duration,
          bufferedRanges: widget.bufferedRanges, onSeek: widget.onSeek,
          onSeekingChanged: widget.onSeekingChanged,
          onPreviewChanged: (position) {
            if (_previewPosition == position) return;
            setState(() => _previewPosition = position);
          }),
        if (widget.compact) SizedBox(height: 24, child: Row(children: [
          time, const Spacer(), Flexible(child: network),
        ])),
        Expanded(child: Row(children: [
          _ToolButton(iconPath: widget.paused ? AppIcons.play : AppIcons.pause, size: 22, onTap: widget.onPlayPause),
          _ToolButton(iconPath: AppIcons.previous, size: 20, onTap: widget.hasPrevious ? widget.onPrevious : null),
          _ToolButton(iconPath: AppIcons.next, size: 20, onTap: widget.hasNext ? widget.onNext : null),
          if (!widget.compact) ...[
            const SizedBox(width: 4), time,
            if (networkText.isNotEmpty) ...[const SizedBox(width: 10), network],
          ],
          const Spacer(),
          _SpeedChip(speed: widget.speed, onTap: widget.onSpeed),
          _ToolButton(iconPath: AppIcons.frame, size: 20, onTap: widget.onFrame, key: const ValueKey('player-frame-button')),
          _ToolButton(iconPath: AppIcons.episodes, size: 20, onTap: widget.onEpisodes),
          _ToolButton(iconPath: AppIcons.more, size: 20, onTap: widget.onTracks),
          _ToolButton(iconPath: widget.fullscreen ? AppIcons.fullscreenExit : AppIcons.fullscreen, size: 20, onTap: widget.onFullscreen),
        ])),
      ]),
    );
  }
}

class _SpeedChip extends StatelessWidget {
  final double speed;
  final VoidCallback onTap;

  const _SpeedChip({required this.speed, required this.onTap});

  @override
  Widget build(BuildContext context) {
    final text = speed.toStringAsFixed(2).replaceFirst(RegExp(r'0+$'), '').replaceFirst(RegExp(r'\.$'), '');
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 4),
      child: Material(
        color: const Color(0x14FFFFFF),
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(14),
          side: const BorderSide(color: Color(0x26FFFFFF)),
        ),
        child: InkWell(
          borderRadius: BorderRadius.circular(14),
          onTap: onTap,
          child: Padding(
            padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 5),
            child: Text(
              '${text}x',
              style: const TextStyle(
                color: Colors.white,
                fontSize: 13,
                fontWeight: FontWeight.bold,
              ),
            ),
          ),
        ),
      ),
    );
  }
}

class _ToolButton extends StatelessWidget {
  final String iconPath;
  final double size;
  final VoidCallback? onTap;

  const _ToolButton({
    super.key,
    required this.iconPath,
    required this.size,
    required this.onTap,
  });

  @override
  Widget build(BuildContext context) {
    final enabled = onTap != null;
    return Opacity(
      opacity: enabled ? 1 : 0.3,
      child: Material(
        color: Colors.transparent,
        child: InkWell(
          borderRadius: BorderRadius.circular(4),
          onTap: onTap,
          child: Padding(
            padding: const EdgeInsets.all(6),
            child: AppIcons.icon(iconPath, size: size),
          ),
        ),
      ),
    );
  }
}
