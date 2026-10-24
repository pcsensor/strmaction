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
  final bool loading;
  final double? networkSpeed;
  final bool hasPrevious;
  final bool hasNext;
  final bool speedBoost;
  final double speedBoostValue;
  final String? centerIconPath;
  final String? centerText;
  final bool showCenterIcon;
  final bool showCenterText;

  final VoidCallback onBack;
  final VoidCallback onPlayPause;
  final VoidCallback onPrevious;
  final VoidCallback onNext;
  final ValueChanged<double> onSeek;
  final ValueChanged<bool>? onSeekingChanged;
  final VoidCallback onSpeed;
  final VoidCallback onEpisodes;
  final VoidCallback onTracks;
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
    required this.loading,
    required this.networkSpeed,
    required this.hasPrevious,
    required this.hasNext,
    required this.speedBoost,
    required this.speedBoostValue,
    required this.centerIconPath,
    required this.centerText,
    required this.showCenterIcon,
    required this.showCenterText,
    required this.onBack,
    required this.onPlayPause,
    required this.onPrevious,
    required this.onNext,
    required this.onSeek,
    required this.onSeekingChanged,
    required this.onSpeed,
    required this.onEpisodes,
    required this.onTracks,
    required this.onFullscreen,
  });

  @override
  Widget build(BuildContext context) {
    final fullTitle = seriesTitle.isNotEmpty && seriesTitle != title
        ? '$seriesTitle - $title'
        : title;
    return IgnorePointer(
      ignoring: !visible,
      child: AnimatedOpacity(
        opacity: visible ? 1 : 0,
        duration: const Duration(milliseconds: 160),
        child: SizedBox.expand(
          child: LayoutBuilder(
            builder: (context, constraints) {
              final height = constraints.maxHeight.isFinite
                  ? constraints.maxHeight
                  : MediaQuery.sizeOf(context).height;
              final bottomHeight = constraints.maxWidth < 650 ? 124.0 : 88.0;
              return Stack(
                children: [
                  Positioned(
                    top: 0,
                    left: 0,
                    right: 0,
                    child: _TopBar(title: fullTitle, onBack: onBack),
                  ),
                  Positioned(
                    top: 72,
                    left: 0,
                    right: 0,
                    bottom: bottomHeight,
                    child: IgnorePointer(
                      child: Center(
                        child: Column(
                          mainAxisSize: MainAxisSize.min,
                          children: [
                            if (showCenterIcon && centerIconPath != null)
                              Container(
                                padding: const EdgeInsets.all(18),
                                decoration: const BoxDecoration(
                                  color: Color(0x99000000),
                                  shape: BoxShape.circle,
                                ),
                                child: AppIcons.icon(centerIconPath!, size: 44),
                              ),
                            if (showCenterText && centerText != null)
                              Container(
                                margin: const EdgeInsets.only(top: 10),
                                padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
                                decoration: BoxDecoration(
                                  color: const Color(0xCC000000),
                                  borderRadius: BorderRadius.circular(18),
                                  border: Border.all(color: const Color(0x33FFFFFF)),
                                ),
                                child: Text(
                                  centerText!,
                                  style: const TextStyle(
                                    color: Colors.white,
                                    fontSize: 16,
                                    fontWeight: FontWeight.bold,
                                  ),
                                ),
                              ),
                            if (loading)
                              Container(
                                margin: const EdgeInsets.only(top: 10),
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
                          ],
                        ),
                      ),
                    ),
                  ),
                  Positioned(
                    top: height - bottomHeight,
                    left: 0,
                    right: 0,
                    child: _BottomBar(
                      compact: constraints.maxWidth < 650,
                      position: position,
                      duration: duration,
                      bufferedRanges: bufferedRanges,
                      speed: speed,
                      paused: paused,
                      fullscreen: fullscreen,
                      networkSpeed: networkSpeed,
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
                      onFullscreen: onFullscreen,
                    ),
                  ),
                  if (speedBoost)
                    Positioned(
                      top: 78,
                      left: 0,
                      right: 0,
                      child: Center(
                        child: Container(
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
                ],
              );
            },
          ),
        ),
      ),
    );
  }

  static String _formatSpeed(double value) {
    final text = value.toStringAsFixed(2);
    return '${text.replaceFirst(RegExp(r'0+$'), '').replaceFirst(RegExp(r'\.$'), '')}x';
  }
}

class _TopBar extends StatelessWidget {
  final String title;
  final VoidCallback onBack;

  const _TopBar({required this.title, required this.onBack});

  @override
  Widget build(BuildContext context) {
    return Container(
      height: 72,
      padding: const EdgeInsets.only(left: 20, right: 20, top: 14),
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

class _BottomBar extends StatelessWidget {
  final bool compact;
  final double position;
  final double duration;
  final List<BufferedRange> bufferedRanges;
  final double speed;
  final bool paused;
  final bool fullscreen;
  final double? networkSpeed;
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
  final VoidCallback onFullscreen;

  const _BottomBar({
    required this.compact,
    required this.position,
    required this.duration,
    required this.bufferedRanges,
    required this.speed,
    required this.paused,
    required this.fullscreen,
    required this.networkSpeed,
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
    required this.onFullscreen,
  });

  @override
  Widget build(BuildContext context) {
    final time = Text(
      '${formatTime(position)} / ${formatTime(duration)}',
      style: const TextStyle(color: Color(0xFFD1D5DB), fontSize: 13),
    );
    final network = Text(formatNetworkSpeed(networkSpeed),
      style: const TextStyle(color: Color(0xFF9CA3AF), fontSize: 12));
    return Container(
      height: compact ? 124 : 88,
      padding: EdgeInsets.fromLTRB(compact ? 12 : 20, 0, compact ? 12 : 20, 12),
      decoration: const BoxDecoration(gradient: LinearGradient(
        begin: Alignment.topCenter, end: Alignment.bottomCenter,
        colors: [Color(0x00000000), Color(0xDC000000)],
      )),
      child: Column(children: [
        BufferedSeekBar(position: position, duration: duration,
          bufferedRanges: bufferedRanges, onSeek: onSeek,
          onSeekingChanged: onSeekingChanged),
        if (compact) SizedBox(height: 24, child: Row(children: [
          time, const Spacer(), Flexible(child: network),
        ])),
        Expanded(child: Row(children: [
          _ToolButton(iconPath: paused ? AppIcons.play : AppIcons.pause, size: 22, onTap: onPlayPause),
          _ToolButton(iconPath: AppIcons.previous, size: 20, onTap: hasPrevious ? onPrevious : null),
          _ToolButton(iconPath: AppIcons.next, size: 20, onTap: hasNext ? onNext : null),
          if (!compact) ...[
            const SizedBox(width: 4), time,
            if (formatNetworkSpeed(networkSpeed).isNotEmpty) ...[const SizedBox(width: 10), network],
          ],
          const Spacer(),
          _SpeedChip(speed: speed, onTap: onSpeed),
          _ToolButton(iconPath: AppIcons.episodes, size: 20, onTap: onEpisodes),
          _ToolButton(iconPath: AppIcons.more, size: 20, onTap: onTracks),
          _ToolButton(iconPath: fullscreen ? AppIcons.fullscreenExit : AppIcons.fullscreen, size: 20, onTap: onFullscreen),
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
