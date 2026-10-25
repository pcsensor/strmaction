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
  final double boostSpeed;
  final List<TrackInfo> subtitles;
  final List<TrackInfo> audioTracks;
  final String? currentSid;
  final String? currentAid;
  final String subtitleHint;
  final VideoScaleMode videoScale;
  final List<VideoScaleMode> scaleModes;

  final VoidCallback onClose;
  final ValueChanged<int> onEpisodeSelected;
  final ValueChanged<double> onSpeedSelected;
  final ValueChanged<double> onBoostSpeedSelected;
  final ValueChanged<String?> onSubtitleSelected;
  final ValueChanged<String?> onAudioSelected;
  final ValueChanged<VideoScaleMode> onScaleSelected;

  const PlayerDrawer({
    super.key,
    required this.visible,
    required this.playlist,
    required this.currentItemId,
    required this.currentSpeed,
    required this.boostSpeed,
    required this.subtitles,
    required this.audioTracks,
    required this.currentSid,
    required this.currentAid,
    required this.subtitleHint,
    required this.videoScale,
    required this.scaleModes,
    required this.onClose,
    required this.onEpisodeSelected,
    required this.onSpeedSelected,
    required this.onBoostSpeedSelected,
    required this.onSubtitleSelected,
    required this.onAudioSelected,
    required this.onScaleSelected,
  });

  @override
  State<PlayerDrawer> createState() => PlayerDrawerState();
}

class PlayerDrawerState extends State<PlayerDrawer> {
  String _tab = 'episodes';
  final FocusScopeNode _scope = FocusScopeNode(debugLabel: 'player-drawer');

  @override
  void initState() {
    super.initState();
    if (widget.playlist.length <= 1) _tab = 'speed';
  }

  void openTab(String tab) {
    setState(() => _tab = tab);
    WidgetsBinding.instance.addPostFrameCallback((_) { if (mounted && widget.visible) { _scope.requestFocus(); _scope.nextFocus(); } });
  }

  @override
  void dispose() { _scope.dispose(); super.dispose(); }

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
        final insets = MediaQuery.viewPaddingOf(context);
        final width = math.min(constraints.maxWidth - insets.left,
          math.max(300.0, constraints.maxWidth * 0.4) + insets.right);
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
                  child: FocusScope(node: _scope, canRequestFocus: widget.visible, child: _DrawerPanel(
                    tab: _tab,
                    onTabChanged: (tab) => setState(() => _tab = tab),
                    playlist: widget.playlist,
                    currentItemId: widget.currentItemId,
                    currentSpeed: widget.currentSpeed,
                    boostSpeed: widget.boostSpeed,
                    subtitles: widget.subtitles,
                    audioTracks: widget.audioTracks,
                    currentSid: widget.currentSid,
                    currentAid: widget.currentAid,
                    subtitleHint: widget.subtitleHint,
                    videoScale: widget.videoScale,
                    scaleModes: widget.scaleModes,
                    onClose: widget.onClose,
                    onEpisodeSelected: widget.onEpisodeSelected,
                    onSpeedSelected: widget.onSpeedSelected,
                    onBoostSpeedSelected: widget.onBoostSpeedSelected,
                    onSubtitleSelected: widget.onSubtitleSelected,
                    onAudioSelected: widget.onAudioSelected,
                    onScaleSelected: widget.onScaleSelected,
                  )),
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
  final double boostSpeed;
  final List<TrackInfo> subtitles;
  final List<TrackInfo> audioTracks;
  final String? currentSid;
  final String? currentAid;
  final String subtitleHint;
  final VideoScaleMode videoScale;
  final List<VideoScaleMode> scaleModes;
  final VoidCallback onClose;
  final ValueChanged<int> onEpisodeSelected;
  final ValueChanged<double> onSpeedSelected;
  final ValueChanged<double> onBoostSpeedSelected;
  final ValueChanged<String?> onSubtitleSelected;
  final ValueChanged<String?> onAudioSelected;
  final ValueChanged<VideoScaleMode> onScaleSelected;

  const _DrawerPanel({
    required this.tab,
    required this.onTabChanged,
    required this.playlist,
    required this.currentItemId,
    required this.currentSpeed,
    required this.boostSpeed,
    required this.subtitles,
    required this.audioTracks,
    required this.currentSid,
    required this.currentAid,
    required this.subtitleHint,
    required this.videoScale,
    required this.scaleModes,
    required this.onClose,
    required this.onEpisodeSelected,
    required this.onSpeedSelected,
    required this.onBoostSpeedSelected,
    required this.onSubtitleSelected,
    required this.onAudioSelected,
    required this.onScaleSelected,
  });

  @override
  Widget build(BuildContext context) {
    final title = switch (tab) {
      'episodes' => '选集 (${playlist.length})',
      'speed' => '播放倍速',
      'frame' => '画面比例',
      _ => '音轨与字幕',
    };
    return Container(
      decoration: const BoxDecoration(
        color: Color(0xF713161F),
        borderRadius: BorderRadius.only(topLeft: Radius.circular(16), bottomLeft: Radius.circular(16)),
      ),
      padding: EdgeInsets.fromLTRB(20, 24 + MediaQuery.viewPaddingOf(context).top,
        20 + MediaQuery.viewPaddingOf(context).right, 24 + MediaQuery.viewPaddingOf(context).bottom),
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
          // Four tabs no longer fit one row on a phone-sized drawer.
          Wrap(
            spacing: 8,
            runSpacing: 8,
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
                text: '画面',
                selected: tab == 'frame',
                onTap: () => onTabChanged('frame'),
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
                    boostSpeed: boostSpeed,
                    onSpeedSelected: onSpeedSelected,
                    onBoostSpeedSelected: onBoostSpeedSelected,
                  ),
                'frame' => _ScaleOptions(
                    current: videoScale,
                    modes: scaleModes,
                    onSelected: onScaleSelected,
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

class _Speeds extends StatefulWidget {
  final double currentSpeed;
  final double boostSpeed;
  final ValueChanged<double> onSpeedSelected;
  final ValueChanged<double> onBoostSpeedSelected;

  const _Speeds({
    required this.currentSpeed,
    required this.boostSpeed,
    required this.onSpeedSelected,
    required this.onBoostSpeedSelected,
  });

  @override
  State<_Speeds> createState() => _SpeedsState();
}

class _SpeedsState extends State<_Speeds> {
  late final TextEditingController _customSpeedController;
  late final TextEditingController _customBoostController;
  late final FocusNode _speedFocus;
  late final FocusNode _boostFocus;
  String? _speedError;
  String? _boostError;

  static const List<double> _defaultSpeeds = [0.5, 0.75, 1.0, 1.25, 1.5, 2.0, 3.0];
  static const List<double> _defaultBoostSpeeds = [1.5, 2.0, 2.5, 3.0, 4.0];

  @override
  void initState() {
    super.initState();
    _customSpeedController = TextEditingController(text: _formatSpeedVal(widget.currentSpeed));
    _customBoostController = TextEditingController(text: _formatSpeedVal(widget.boostSpeed));
    _speedFocus = FocusNode();
    _boostFocus = FocusNode();
  }

  @override
  void didUpdateWidget(covariant _Speeds oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (!_speedFocus.hasFocus && (oldWidget.currentSpeed - widget.currentSpeed).abs() > 0.001) {
      _customSpeedController.text = _formatSpeedVal(widget.currentSpeed);
    }
    if (!_boostFocus.hasFocus && (oldWidget.boostSpeed - widget.boostSpeed).abs() > 0.001) {
      _customBoostController.text = _formatSpeedVal(widget.boostSpeed);
    }
  }

  @override
  void dispose() {
    _customSpeedController.dispose();
    _customBoostController.dispose();
    _speedFocus.dispose();
    _boostFocus.dispose();
    super.dispose();
  }

  static String _formatSpeedVal(double value) {
    return value.toStringAsFixed(2).replaceFirst(RegExp(r'0+$'), '').replaceFirst(RegExp(r'\.$'), '');
  }

  void _applyCustomSpeed(String raw) {
    final parsed = double.tryParse(raw.trim());
    if (parsed == null || parsed < 0.25 || parsed > 4.0) {
      setState(() => _speedError = '请输入 0.25 ~ 4.0 之间的倍速');
      return;
    }
    setState(() => _speedError = null);
    final rounded = (parsed * 100).round() / 100;
    _customSpeedController.text = _formatSpeedVal(rounded);
    widget.onSpeedSelected(rounded);
  }

  void _stepCustomSpeed(double delta) {
    final current = double.tryParse(_customSpeedController.text.trim()) ?? widget.currentSpeed;
    final next = ((current + delta) * 100).round() / 100;
    final clamped = next.clamp(0.25, 4.0).toDouble();
    _applyCustomSpeed(clamped.toString());
  }

  void _applyCustomBoost(String raw) {
    final parsed = double.tryParse(raw.trim());
    if (parsed == null || parsed < 0.25 || parsed > 4.0) {
      setState(() => _boostError = '请输入 0.25 ~ 4.0 之间的倍速');
      return;
    }
    setState(() => _boostError = null);
    final rounded = (parsed * 100).round() / 100;
    _customBoostController.text = _formatSpeedVal(rounded);
    widget.onBoostSpeedSelected(rounded);
  }

  void _stepCustomBoost(double delta) {
    final current = double.tryParse(_customBoostController.text.trim()) ?? widget.boostSpeed;
    final next = ((current + delta) * 100).round() / 100;
    final clamped = next.clamp(0.25, 4.0).toDouble();
    _applyCustomBoost(clamped.toString());
  }

  @override
  Widget build(BuildContext context) {
    final isPresetSpeed = _defaultSpeeds.any((s) => (s - widget.currentSpeed).abs() < 0.01);
    final isPresetBoost = _defaultBoostSpeeds.any((s) => (s - widget.boostSpeed).abs() < 0.01);

    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Row(
          children: [
            const Text(
              '常规播放倍速',
              style: TextStyle(color: Color(0xFFF0A94D), fontSize: 14, fontWeight: FontWeight.bold),
            ),
            const Spacer(),
            Text(
              '当前: ${_formatSpeedVal(widget.currentSpeed)}x',
              style: const TextStyle(color: Color(0xFFF0A94D), fontSize: 12),
            ),
          ],
        ),
        const SizedBox(height: 10),
        Wrap(
          spacing: 8,
          runSpacing: 8,
          children: [
            for (final speed in _defaultSpeeds)
              _SpeedChip(
                text: '${_formatSpeedVal(speed)}x',
                active: (speed - widget.currentSpeed).abs() < 0.01,
                onTap: () {
                  setState(() => _speedError = null);
                  _customSpeedController.text = _formatSpeedVal(speed);
                  widget.onSpeedSelected(speed);
                },
              ),
          ],
        ),
        const SizedBox(height: 12),
        Container(
          padding: const EdgeInsets.all(12),
          decoration: BoxDecoration(
            color: const Color(0x0DFFFFFF),
            borderRadius: BorderRadius.circular(8),
            border: Border.all(
              color: !isPresetSpeed ? const Color(0xFFF0A94D) : const Color(0x1AFFFFFF),
            ),
          ),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Row(
                children: [
                  const Text('自定义倍速', style: TextStyle(color: Colors.white70, fontSize: 12)),
                  const Spacer(),
                  if (!isPresetSpeed)
                    const Text('当前生效中', style: TextStyle(color: Color(0xFFF0A94D), fontSize: 11, fontWeight: FontWeight.bold)),
                ],
              ),
              const SizedBox(height: 8),
              Row(
                children: [
                  _StepButton(icon: Icons.remove, onTap: () => _stepCustomSpeed(-0.1)),
                  const SizedBox(width: 6),
                  Expanded(
                    child: SizedBox(
                      height: 36,
                      child: TextField(
                        controller: _customSpeedController,
                        focusNode: _speedFocus,
                        style: const TextStyle(color: Colors.white, fontSize: 13),
                        keyboardType: const TextInputType.numberWithOptions(decimal: true),
                        decoration: InputDecoration(
                          contentPadding: const EdgeInsets.symmetric(horizontal: 10, vertical: 8),
                          filled: true,
                          fillColor: const Color(0x1AFFFFFF),
                          hintText: '0.25 - 4.0',
                          hintStyle: const TextStyle(color: Colors.white30, fontSize: 12),
                          suffixText: 'x',
                          suffixStyle: const TextStyle(color: Colors.white70, fontSize: 12),
                          border: OutlineInputBorder(borderRadius: BorderRadius.circular(6), borderSide: BorderSide.none),
                          focusedBorder: OutlineInputBorder(borderRadius: BorderRadius.circular(6), borderSide: const BorderSide(color: Color(0xFFF0A94D))),
                        ),
                        onSubmitted: _applyCustomSpeed,
                      ),
                    ),
                  ),
                  const SizedBox(width: 6),
                  _StepButton(icon: Icons.add, onTap: () => _stepCustomSpeed(0.1)),
                  const SizedBox(width: 8),
                  SizedBox(
                    height: 36,
                    child: ElevatedButton(
                      style: ElevatedButton.styleFrom(
                        backgroundColor: const Color(0xFFF0A94D),
                        foregroundColor: Colors.black,
                        padding: const EdgeInsets.symmetric(horizontal: 12),
                        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(6)),
                        elevation: 0,
                      ),
                      onPressed: () => _applyCustomSpeed(_customSpeedController.text),
                      child: const Text('应用', style: TextStyle(fontSize: 12, fontWeight: FontWeight.bold)),
                    ),
                  ),
                ],
              ),
              if (_speedError != null) ...[
                const SizedBox(height: 6),
                Text(_speedError!, style: const TextStyle(color: Colors.redAccent, fontSize: 11)),
              ],
            ],
          ),
        ),
        const Padding(
          padding: EdgeInsets.symmetric(vertical: 16),
          child: Divider(color: Color(0x1AFFFFFF), height: 1),
        ),
        Row(
          children: [
            const Text(
              '长按倍速（按住 → 键）',
              style: TextStyle(color: Color(0xFFF0A94D), fontSize: 14, fontWeight: FontWeight.bold),
            ),
            const Spacer(),
            Text(
              '当前: ${_formatSpeedVal(widget.boostSpeed)}x',
              style: const TextStyle(color: Color(0xFFF0A94D), fontSize: 12),
            ),
          ],
        ),
        const SizedBox(height: 4),
        const Text(
          '播放时按住键盘右方向键（→）加速播放，松开恢复正常倍速。',
          style: TextStyle(color: Color(0xFF7C8698), fontSize: 11),
        ),
        const SizedBox(height: 10),
        Wrap(
          spacing: 8,
          runSpacing: 8,
          children: [
            for (final speed in _defaultBoostSpeeds)
              _SpeedChip(
                text: '${_formatSpeedVal(speed)}x',
                active: (speed - widget.boostSpeed).abs() < 0.01,
                onTap: () {
                  setState(() => _boostError = null);
                  _customBoostController.text = _formatSpeedVal(speed);
                  widget.onBoostSpeedSelected(speed);
                },
              ),
          ],
        ),
        const SizedBox(height: 12),
        Container(
          padding: const EdgeInsets.all(12),
          decoration: BoxDecoration(
            color: const Color(0x0DFFFFFF),
            borderRadius: BorderRadius.circular(8),
            border: Border.all(
              color: !isPresetBoost ? const Color(0xFFF0A94D) : const Color(0x1AFFFFFF),
            ),
          ),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Row(
                children: [
                  const Text('自定义长按倍速', style: TextStyle(color: Colors.white70, fontSize: 12)),
                  const Spacer(),
                  if (!isPresetBoost)
                    const Text('当前生效中', style: TextStyle(color: Color(0xFFF0A94D), fontSize: 11, fontWeight: FontWeight.bold)),
                ],
              ),
              const SizedBox(height: 8),
              Row(
                children: [
                  _StepButton(icon: Icons.remove, onTap: () => _stepCustomBoost(-0.25)),
                  const SizedBox(width: 6),
                  Expanded(
                    child: SizedBox(
                      height: 36,
                      child: TextField(
                        controller: _customBoostController,
                        focusNode: _boostFocus,
                        style: const TextStyle(color: Colors.white, fontSize: 13),
                        keyboardType: const TextInputType.numberWithOptions(decimal: true),
                        decoration: InputDecoration(
                          contentPadding: const EdgeInsets.symmetric(horizontal: 10, vertical: 8),
                          filled: true,
                          fillColor: const Color(0x1AFFFFFF),
                          hintText: '0.25 - 4.0',
                          hintStyle: const TextStyle(color: Colors.white30, fontSize: 12),
                          suffixText: 'x',
                          suffixStyle: const TextStyle(color: Colors.white70, fontSize: 12),
                          border: OutlineInputBorder(borderRadius: BorderRadius.circular(6), borderSide: BorderSide.none),
                          focusedBorder: OutlineInputBorder(borderRadius: BorderRadius.circular(6), borderSide: const BorderSide(color: Color(0xFFF0A94D))),
                        ),
                        onSubmitted: _applyCustomBoost,
                      ),
                    ),
                  ),
                  const SizedBox(width: 6),
                  _StepButton(icon: Icons.add, onTap: () => _stepCustomBoost(0.25)),
                  const SizedBox(width: 8),
                  SizedBox(
                    height: 36,
                    child: ElevatedButton(
                      style: ElevatedButton.styleFrom(
                        backgroundColor: const Color(0xFFF0A94D),
                        foregroundColor: Colors.black,
                        padding: const EdgeInsets.symmetric(horizontal: 12),
                        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(6)),
                        elevation: 0,
                      ),
                      onPressed: () => _applyCustomBoost(_customBoostController.text),
                      child: const Text('应用', style: TextStyle(fontSize: 12, fontWeight: FontWeight.bold)),
                    ),
                  ),
                ],
              ),
              if (_boostError != null) ...[
                const SizedBox(height: 6),
                Text(_boostError!, style: const TextStyle(color: Colors.redAccent, fontSize: 11)),
              ],
            ],
          ),
        ),
      ],
    );
  }
}

class _SpeedChip extends StatelessWidget {
  final String text;
  final bool active;
  final VoidCallback onTap;

  const _SpeedChip({
    required this.text,
    required this.active,
    required this.onTap,
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
        child: Container(
          padding: const EdgeInsets.symmetric(horizontal: 13, vertical: 8),
          child: Text(
            text,
            style: TextStyle(
              color: active ? const Color(0xFFF0A94D) : Colors.white,
              fontSize: 13,
              fontWeight: active ? FontWeight.bold : FontWeight.normal,
            ),
          ),
        ),
      ),
    );
  }
}

class _StepButton extends StatelessWidget {
  final IconData icon;
  final VoidCallback onTap;

  const _StepButton({required this.icon, required this.onTap});

  @override
  Widget build(BuildContext context) {
    return Material(
      color: const Color(0x1AFFFFFF),
      borderRadius: BorderRadius.circular(6),
      child: InkWell(
        borderRadius: BorderRadius.circular(6),
        onTap: onTap,
        child: SizedBox(
          width: 36,
          height: 36,
          child: Icon(icon, color: Colors.white70, size: 16),
        ),
      ),
    );
  }
}

class _ScaleOptions extends StatelessWidget {
  final VideoScaleMode current;
  final List<VideoScaleMode> modes;
  final ValueChanged<VideoScaleMode> onSelected;

  const _ScaleOptions({
    required this.current,
    required this.modes,
    required this.onSelected,
  });

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        const Text(
          '画面比例',
          style: TextStyle(color: Color(0xFFF0A94D), fontSize: 14, fontWeight: FontWeight.bold),
        ),
        const SizedBox(height: 4),
        const Text(
          '决定画面如何放进播放区域；选择后会记住，下次播放沿用。',
          style: TextStyle(color: Color(0xFF7C8698), fontSize: 11),
        ),
        const SizedBox(height: 10),
        for (final mode in modes) ...[
          _ScaleOption(
            mode: mode,
            active: mode == current,
            onTap: () => onSelected(mode),
          ),
          const SizedBox(height: 8),
        ],
      ],
    );
  }
}

class _ScaleOption extends StatelessWidget {
  final VideoScaleMode mode;
  final bool active;
  final VoidCallback onTap;

  const _ScaleOption({required this.mode, required this.active, required this.onTap});

  @override
  Widget build(BuildContext context) {
    return Material(
      color: active ? const Color(0x33F0A94D) : const Color(0x0DFFFFFF),
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(8),
        side: BorderSide(
          color: active ? const Color(0xFFF0A94D) : Colors.transparent,
          width: active ? 1.5 : 1,
        ),
      ),
      child: InkWell(
        borderRadius: BorderRadius.circular(8),
        onTap: onTap,
        child: Padding(
          padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                children: [
                  Expanded(
                    child: Text(
                      mode.label,
                      style: TextStyle(
                        color: active ? const Color(0xFFF0A94D) : Colors.white,
                        fontSize: 14,
                        fontWeight: active ? FontWeight.bold : FontWeight.normal,
                      ),
                    ),
                  ),
                  if (active)
                    const Text('使用中',
                        style: TextStyle(color: Color(0xFFF0A94D), fontSize: 11, fontWeight: FontWeight.bold)),
                ],
              ),
              const SizedBox(height: 2),
              Text(
                mode.description,
                style: const TextStyle(color: Color(0xFF8E9297), fontSize: 11.5),
              ),
            ],
          ),
        ),
      ),
    );
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
  final VoidCallback onTap;

  const _TrackOption({
    required this.text,
    required this.active,
    required this.onTap,
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
          height: 40,
          child: Align(
            alignment: Alignment.centerLeft,
            child: Padding(
              padding: const EdgeInsets.symmetric(horizontal: 12),
              child: Text(
                text,
                style: TextStyle(
                  color: active ? const Color(0xFFF0A94D) : Colors.white,
                  fontSize: 13,
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
