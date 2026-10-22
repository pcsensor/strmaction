import 'dart:math' as math;

import 'package:flutter/material.dart';

import '../../models/playback_payload.dart';
import '../playback_engine.dart';
import 'app_icons.dart';

class PlayerDrawer extends StatefulWidget {
  final bool visible;
  final List<PlaylistEntry> playlist;
  final int? currentItemId;
  final double currentSpeed;
  final List<TrackInfo> subtitles;
  final List<TrackInfo> audioTracks;
  final String? currentSid;
  final String? currentAid;
  final String subtitleHint;

  final VoidCallback onClose;
  final ValueChanged<int> onEpisodeSelected;
  final ValueChanged<double> onSpeedSelected;
  final ValueChanged<String?> onSubtitleSelected;
  final ValueChanged<String?> onAudioSelected;

  const PlayerDrawer({
    super.key,
    required this.visible,
    required this.playlist,
    required this.currentItemId,
    required this.currentSpeed,
    required this.subtitles,
    required this.audioTracks,
    required this.currentSid,
    required this.currentAid,
    required this.subtitleHint,
    required this.onClose,
    required this.onEpisodeSelected,
    required this.onSpeedSelected,
    required this.onSubtitleSelected,
    required this.onAudioSelected,
  });

  @override
  State<PlayerDrawer> createState() => PlayerDrawerState();
}

class PlayerDrawerState extends State<PlayerDrawer> {
  String _tab = 'episodes';

  @override
  void initState() {
    super.initState();
    if (widget.playlist.length <= 1) _tab = 'speed';
  }

  void openTab(String tab) {
    setState(() => _tab = tab);
  }

  @override
  void didUpdateWidget(covariant PlayerDrawer oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (widget.playlist.length <= 1 && _tab == 'episodes') {
      _tab = 'speed';
    }
  }

  @override
  Widget build(BuildContext context) {
    return LayoutBuilder(
      builder: (context, constraints) {
        final width = math.max(300.0, constraints.maxWidth * 0.4);
        return IgnorePointer(
          ignoring: !widget.visible,
          child: AnimatedOpacity(
            opacity: widget.visible ? 1 : 0,
            duration: const Duration(milliseconds: 220),
            child: Stack(
              children: [
                Positioned.fill(
                  child: GestureDetector(
                    onTap: widget.onClose,
                    child: Container(color: const Color(0x8C000000)),
                  ),
                ),
                AnimatedPositioned(
                  duration: const Duration(milliseconds: 240),
                  curve: Curves.easeOutCubic,
                  top: 0,
                  bottom: 0,
                  right: widget.visible ? 0 : -width,
                  width: width,
                  child: _DrawerPanel(
                    tab: _tab,
                    onTabChanged: (tab) => setState(() => _tab = tab),
                    playlist: widget.playlist,
                    currentItemId: widget.currentItemId,
                    currentSpeed: widget.currentSpeed,
                    subtitles: widget.subtitles,
                    audioTracks: widget.audioTracks,
                    currentSid: widget.currentSid,
                    currentAid: widget.currentAid,
                    subtitleHint: widget.subtitleHint,
                    onClose: widget.onClose,
                    onEpisodeSelected: widget.onEpisodeSelected,
                    onSpeedSelected: widget.onSpeedSelected,
                    onSubtitleSelected: widget.onSubtitleSelected,
                    onAudioSelected: widget.onAudioSelected,
                  ),
                ),
              ],
            ),
          ),
        );
      },
    );
  }
}

class _DrawerPanel extends StatelessWidget {
  final String tab;
  final ValueChanged<String> onTabChanged;
  final List<PlaylistEntry> playlist;
  final int? currentItemId;
  final double currentSpeed;
  final List<TrackInfo> subtitles;
  final List<TrackInfo> audioTracks;
  final String? currentSid;
  final String? currentAid;
  final String subtitleHint;
  final VoidCallback onClose;
  final ValueChanged<int> onEpisodeSelected;
  final ValueChanged<double> onSpeedSelected;
  final ValueChanged<String?> onSubtitleSelected;
  final ValueChanged<String?> onAudioSelected;

  const _DrawerPanel({
    required this.tab,
    required this.onTabChanged,
    required this.playlist,
    required this.currentItemId,
    required this.currentSpeed,
    required this.subtitles,
    required this.audioTracks,
    required this.currentSid,
    required this.currentAid,
    required this.subtitleHint,
    required this.onClose,
    required this.onEpisodeSelected,
    required this.onSpeedSelected,
    required this.onSubtitleSelected,
    required this.onAudioSelected,
  });

  @override
  Widget build(BuildContext context) {
    final title = switch (tab) {
      'episodes' => '选集 (${playlist.length})',
      'speed' => '播放倍速',
      _ => '音轨与字幕',
    };
    return Container(
      decoration: const BoxDecoration(
        color: Color(0xF713161F),
        borderRadius: BorderRadius.only(topLeft: Radius.circular(16), bottomLeft: Radius.circular(16)),
      ),
      padding: const EdgeInsets.fromLTRB(20, 24, 20, 24),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Row(
            children: [
              Expanded(
                child: Text(
                  title,
                  style: const TextStyle(
                    color: Colors.white,
                    fontSize: 18,
                    fontWeight: FontWeight.bold,
                  ),
                ),
              ),
              IconButton(
                onPressed: onClose,
                icon: AppIcons.icon(AppIcons.close, size: 20, color: const Color(0xFFAAAAAA)),
                splashRadius: 18,
              ),
            ],
          ),
          const SizedBox(height: 8),
          Row(
            children: [
              if (playlist.length > 1)
                _TabChip(
                  text: '选集',
                  selected: tab == 'episodes',
                  onTap: () => onTabChanged('episodes'),
                ),
              _TabChip(
                text: '倍速',
                selected: tab == 'speed',
                onTap: () => onTabChanged('speed'),
              ),
              _TabChip(
                text: '音轨与字幕',
                selected: tab == 'tracks',
                onTap: () => onTabChanged('tracks'),
              ),
            ],
          ),
          const SizedBox(height: 14),
          Expanded(
            child: SingleChildScrollView(
              child: switch (tab) {
                'episodes' => _Episodes(
                    playlist: playlist,
                    currentItemId: currentItemId,
                    onSelected: onEpisodeSelected,
                  ),
                'speed' => _Speeds(
                    currentSpeed: currentSpeed,
                    onSelected: onSpeedSelected,
                  ),
                _ => _Tracks(
                    subtitles: subtitles,
                    audioTracks: audioTracks,
                    currentSid: currentSid,
                    currentAid: currentAid,
                    subtitleHint: subtitleHint,
                    onSubtitleSelected: onSubtitleSelected,
                    onAudioSelected: onAudioSelected,
                  ),
              },
            ),
          ),
        ],
      ),
    );
  }
}

class _TabChip extends StatelessWidget {
  final String text;
  final bool selected;
  final VoidCallback onTap;

  const _TabChip({required this.text, required this.selected, required this.onTap});

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(right: 8),
      child: Material(
        color: selected ? const Color(0x33F0A94D) : const Color(0x14FFFFFF),
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(14),
          side: BorderSide(color: selected ? const Color(0xFFF0A94D) : Colors.transparent),
        ),
        child: InkWell(
          borderRadius: BorderRadius.circular(14),
          onTap: onTap,
          child: Padding(
            padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 5),
            child: Text(
              text,
              style: TextStyle(
                color: selected ? const Color(0xFFF0A94D) : const Color(0xFF8E9297),
                fontSize: 13,
                fontWeight: selected ? FontWeight.bold : FontWeight.normal,
              ),
            ),
          ),
        ),
      ),
    );
  }
}

class _Episodes extends StatelessWidget {
  final List<PlaylistEntry> playlist;
  final int? currentItemId;
  final ValueChanged<int> onSelected;

  const _Episodes({required this.playlist, required this.currentItemId, required this.onSelected});

  @override
  Widget build(BuildContext context) {
    if (playlist.isEmpty) {
      return const Text('暂无选集', style: TextStyle(color: Color(0xFF8E9297), fontSize: 12));
    }
    return Column(
      children: [
        for (final entry in playlist) ...[
          _EpisodeCard(
            entry: entry,
            current: entry.current || (entry.itemId != null && entry.itemId == currentItemId),
            onTap: entry.itemId == null ? null : () => onSelected(entry.itemId!),
          ),
          const SizedBox(height: 8),
        ],
      ],
    );
  }
}

class _EpisodeCard extends StatelessWidget {
  final PlaylistEntry entry;
  final bool current;
  final VoidCallback? onTap;

  const _EpisodeCard({required this.entry, required this.current, required this.onTap});

  @override
  Widget build(BuildContext context) {
    final code = entry.code.isNotEmpty
        ? entry.code
        : 'P${(entry.episodeNo ?? 0).toString().padLeft(2, '0')}';
    return Material(
      color: current ? const Color(0x2EF0A94D) : const Color(0x0DFFFFFF),
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(8),
        side: BorderSide(
          color: current ? const Color(0xFFF0A94D) : Colors.transparent,
          width: current ? 1.5 : 1,
        ),
      ),
      child: InkWell(
        borderRadius: BorderRadius.circular(8),
        onTap: onTap,
        child: SizedBox(
          height: 50,
          child: Padding(
            padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
            child: Row(
              children: [
                if (current)
                  const Padding(
                    padding: EdgeInsets.only(right: 6),
                    child: Text('▶', style: TextStyle(color: Color(0xFFF0A94D), fontSize: 11)),
                  ),
                Text(
                  code,
                  style: TextStyle(
                    color: current ? const Color(0xFFF0A94D) : Colors.white,
                    fontSize: 14,
                    fontWeight: FontWeight.bold,
                  ),
                ),
                const SizedBox(width: 8),
                Expanded(
                  child: Text(
                    entry.title,
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    style: TextStyle(
                      color: current ? const Color(0xFFF0A94D) : const Color(0xFFB0B3B8),
                      fontSize: 13,
                    ),
                  ),
                ),
                if (current)
                  _badge('播放中', const Color(0xFFF0A94D), const Color(0xFF17120B))
                else if (entry.watched)
                  _badge('已看', const Color(0x1AFFFFFF), const Color(0xFF8E9297)),
              ],
            ),
          ),
        ),
      ),
    );
  }

  Widget _badge(String text, Color bg, Color fg) {
    return Container(
      margin: const EdgeInsets.only(left: 6),
      padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
      decoration: BoxDecoration(color: bg, borderRadius: BorderRadius.circular(4)),
      child: Text(text, style: TextStyle(color: fg, fontSize: 10, fontWeight: FontWeight.bold)),
    );
  }
}

class _Speeds extends StatelessWidget {
  final double currentSpeed;
  final ValueChanged<double> onSelected;

  const _Speeds({required this.currentSpeed, required this.onSelected});

  @override
  Widget build(BuildContext context) {
    const speeds = [0.5, 0.75, 1.0, 1.25, 1.5, 2.0, 3.0];
    return Column(
      children: [
        for (final speed in speeds) ...[
          _TrackOption(
            text: _speedText(speed),
            active: (speed - currentSpeed).abs() < 0.01,
            height: 44,
            onTap: () => onSelected(speed),
          ),
          const SizedBox(height: 8),
        ],
      ],
    );
  }

  static String _speedText(double value) {
    final text = value.toStringAsFixed(2).replaceFirst(RegExp(r'0+$'), '').replaceFirst(RegExp(r'\.$'), '');
    return '${text}x';
  }
}

class _Tracks extends StatelessWidget {
  final List<TrackInfo> subtitles;
  final List<TrackInfo> audioTracks;
  final String? currentSid;
  final String? currentAid;
  final String subtitleHint;
  final ValueChanged<String?> onSubtitleSelected;
  final ValueChanged<String?> onAudioSelected;

  const _Tracks({
    required this.subtitles,
    required this.audioTracks,
    required this.currentSid,
    required this.currentAid,
    required this.subtitleHint,
    required this.onSubtitleSelected,
    required this.onAudioSelected,
  });

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        const Text('字幕', style: TextStyle(color: Color(0xFFF0A94D), fontSize: 14, fontWeight: FontWeight.bold)),
        const SizedBox(height: 8),
        _TrackOption(
          text: '关闭字幕',
          active: currentSid == null || currentSid == 'no',
          onTap: () => onSubtitleSelected(null),
        ),
        const SizedBox(height: 6),
        for (final subtitle in subtitles) ...[
          _TrackOption(
            text: subtitle.title,
            active: currentSid == subtitle.id,
            onTap: () => onSubtitleSelected(subtitle.id),
          ),
          const SizedBox(height: 6),
        ],
        if (subtitleHint.isNotEmpty)
          Padding(
            padding: const EdgeInsets.only(top: 2),
            child: Text(
              subtitleHint,
              style: const TextStyle(color: Color(0xFF8E9297), fontSize: 11.5),
            ),
          ),
        const SizedBox(height: 14),
        const Text('音轨', style: TextStyle(color: Color(0xFFF0A94D), fontSize: 14, fontWeight: FontWeight.bold)),
        const SizedBox(height: 8),
        if (audioTracks.isEmpty)
          const Text('暂无额外音轨', style: TextStyle(color: Color(0xFF8E9297), fontSize: 12))
        else
          for (final audio in audioTracks) ...[
            _TrackOption(
              text: audio.title,
              active: currentAid == audio.id,
              onTap: () => onAudioSelected(audio.id),
            ),
            const SizedBox(height: 6),
          ],
      ],
    );
  }
}

class _TrackOption extends StatelessWidget {
  final String text;
  final bool active;
  final double height;
  final VoidCallback onTap;

  const _TrackOption({
    required this.text,
    required this.active,
    required this.onTap,
    this.height = 40,
  });

  @override
  Widget build(BuildContext context) {
    return Material(
      color: active ? const Color(0x33F0A94D) : const Color(0x0DFFFFFF),
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(6),
        side: BorderSide(color: active ? const Color(0xFFF0A94D) : Colors.transparent),
      ),
      child: InkWell(
        borderRadius: BorderRadius.circular(6),
        onTap: onTap,
        child: SizedBox(
          height: height,
          child: Align(
            alignment: Alignment.centerLeft,
            child: Padding(
              padding: const EdgeInsets.symmetric(horizontal: 12),
              child: Text(
                text,
                style: TextStyle(
                  color: active ? const Color(0xFFF0A94D) : Colors.white,
                  fontSize: height > 40 ? 15 : 13,
                  fontWeight: active ? FontWeight.bold : FontWeight.normal,
                ),
              ),
            ),
          ),
        ),
      ),
    );
  }
}
