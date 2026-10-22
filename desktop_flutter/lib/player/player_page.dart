import 'dart:async';

import 'package:flutter/material.dart';
import 'package:media_kit_video/media_kit_video.dart';
import 'package:window_manager/window_manager.dart';

import '../app_controller.dart';
import '../models/playback_payload.dart';
import '../services/progress_reporter.dart';
import 'input/player_keyboard.dart';
import 'media_kit_engine.dart';
import 'widgets/app_icons.dart';
import 'widgets/controls_overlay.dart';
import 'widgets/message_card.dart';
import 'widgets/player_drawer.dart';

class PlayerPage extends StatefulWidget {
  final AppController app;
  final PlaybackPayload payload;
  final ValueChanged<int>? onRequestItem;

  const PlayerPage({
    super.key,
    required this.app,
    required this.payload,
    this.onRequestItem,
  });

  @override
  State<PlayerPage> createState() => _PlayerPageState();
}

class _PlayerPageState extends State<PlayerPage> {
  late final MediaKitEngine _engine;
  late final ProgressReporter _reporter;
  late final PlayerKeyboardHandler _keyboard;
  final FocusNode _focusNode = FocusNode(debugLabel: 'player');
  final GlobalKey<PlayerDrawerState> _drawerKey = GlobalKey<PlayerDrawerState>();

  Timer? _hideTimer;
  Timer? _badgeTimer;
  Timer? _watchdog;

  bool _controlsVisible = true;
  bool _drawerVisible = false;
  bool _seeking = false;
  bool _fullscreen = false;
  bool _speedBoost = false;
  double _normalSpeed = 1.0;
  bool _completionHandled = false;
  bool _messageVisible = false;
  String? _cardMode;
  String? _lastError;
  bool _closing = false;
  bool _shutdownDone = false;

  String _cardTitle = '';
  String _cardDescription = '';
  String? _cardPrimary;
  String? _cardSecondary;
  int? _cardCountdown;

  String? _centerIconPath;
  String? _centerText;
  bool _showCenterIcon = false;
  bool _showCenterText = false;

  @override
  void initState() {
    super.initState();
    _engine = MediaKitEngine(logger: widget.app.logger);
    _engine.addListener(_onEngineChanged);
    _reporter = ProgressReporter(
      serverUrl: widget.app.config.serverUrl,
      itemId: widget.payload.itemId,
      playToken: widget.payload.playToken,
      intervalMs: widget.payload.progressIntervalMs,
      verifySsl: !widget.app.config.allowSelfSignedHttps,
      onAuthError: _onProgressAuthError,
      logger: widget.app.logger,
    );
    widget.app.activeProgress = _reporter;
    widget.app.setPlaybackShutdown(_shutdownPlayback);
    _keyboard = PlayerKeyboardHandler(
      onPlayPause: _togglePlayPause,
      onSeekRelative: _seekRelative,
      onSpeedBoostStarted: _startSpeedBoost,
      onSpeedBoostEnded: _endSpeedBoost,
      onVolumeRelative: _volumeRelative,
      onMute: _toggleMute,
      onFullscreen: _toggleFullscreen,
      onEscape: _onEscape,
      onPreviousEpisode: _previousEpisode,
      onNextEpisode: _nextEpisode,
      onCycleSubtitle: _cycleSubtitle,
      onCycleAudio: _cycleAudio,
      onToggleDrawer: _toggleDrawer,
    );
    _normalSpeed = 1.0;
    widget.app.configNotifier.addListener(_onConfigChanged);
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!mounted) return;
      _focusNode.requestFocus();
      _load();
      _refreshFullscreen();
    });
  }

  Future<void> _load() async {
    _watchdog?.cancel();
    _watchdog = Timer(const Duration(seconds: 30), () {
      if (!mounted || !_engine.isLoading) return;
      _showError('打开片源超时，请检查网络、链接或证书设置。');
    });
    await _engine.load(
      widget.payload,
      cacheLimitMb: widget.app.config.cacheLimitMb,
      tlsVerify: !widget.app.config.allowSelfSignedHttps,
    );
    _watchdog?.cancel();
    _watchdog = null;
    if (!mounted) return;
    if (_engine.errorMessage == null) {
      _reporter.start();
      _reporter.update(
        widget.payload.resumeMs.clamp(0, 1 << 31),
        durationMs: widget.payload.durationMs,
      );
    }
    _focusNode.requestFocus();
  }

  void _onConfigChanged() {
    _engine.applySettings(
      cacheLimitMb: widget.app.config.cacheLimitMb,
      tlsVerify: !widget.app.config.allowSelfSignedHttps,
    );
  }

  void _onEngineChanged() {
    if (!mounted) return;
    setState(() {});
    _reporter.update(
      (_engine.position * 1000).round(),
      durationMs: _engine.duration > 0 ? (_engine.duration * 1000).round() : null,
    );
    if (_engine.completed && !_completionHandled) {
      _onCompleted();
    }
    final error = _engine.errorMessage;
    if (error != null && error != _lastError) {
      _lastError = error;
      _showError(error);
    }
    if (_engine.isPaused && !_controlsVisible) {
      _showControls();
    }
  }

  void _onCompleted() {
    _completionHandled = true;
    _reporter.finish();
    _reporter.requestFlush();
    final nextId = _nextId;
    _showMessage(
      mode: 'end',
      title: '播放结束',
      description: nextId != null
          ? (_nextTitle.isEmpty ? '即将播放下一集' : '下一集：$_nextTitle')
          : '已记录观看进度',
      primary: nextId != null ? '播放下一集' : '返回',
      secondary: nextId != null ? '返回' : null,
      countdown: nextId != null ? 5 : null,
    );
  }

  void _showError(String message) {
    _showMessage(
      mode: 'error',
      title: '播放失败',
      description: message,
      primary: '重试',
      secondary: '返回',
    );
  }

  void _showMessage({
    required String mode,
    required String title,
    required String description,
    String? primary,
    String? secondary,
    int? countdown,
  }) {
    if (!mounted) return;
    setState(() {
      _cardMode = mode;
      _cardTitle = title;
      _cardDescription = description;
      _cardPrimary = primary;
      _cardSecondary = secondary;
      _cardCountdown = countdown;
      _messageVisible = true;
      _controlsVisible = true;
    });
    _hideTimer?.cancel();
  }

  void _hideMessage() {
    if (!mounted) return;
    setState(() {
      _messageVisible = false;
      _cardMode = null;
      _cardCountdown = null;
    });
    _restartHideTimer();
  }

  Future<void> _retry() async {
    _hideMessage();
    _completionHandled = false;
    _lastError = null;
    await _engine.stop();
    await _load();
  }

  Future<void> _shutdownPlayback() async {
    if (_shutdownDone) return;
    _shutdownDone = true;
    _watchdog?.cancel();
    _hideTimer?.cancel();
    _badgeTimer?.cancel();
    await _reporter.stop(flush: true);
    if (widget.app.activeProgress == _reporter) {
      widget.app.activeProgress = null;
    }
    await _engine.shutdown();
    widget.app.setPlaybackShutdown(null);
  }

  Future<void> _back() async {
    if (_closing) return;
    _closing = true;
    await _shutdownPlayback();
    await _exitFullscreenIfNeeded();
    if (mounted) Navigator.of(context).pop();
  }

  Future<void> _requestItem(int itemId) async {
    if (_closing) return;
    _closing = true;
    await _shutdownPlayback();
    await _exitFullscreenIfNeeded();
    widget.onRequestItem?.call(itemId);
    if (mounted) Navigator.of(context).pop();
  }

  Future<void> _exitFullscreenIfNeeded() async {
    try {
      if (await windowManager.isFullScreen()) {
        await windowManager.setFullScreen(false);
      }
    } on Object {
      // Best effort during teardown.
    }
  }

  Future<void> _refreshFullscreen() async {
    try {
      final value = await windowManager.isFullScreen();
      if (mounted) setState(() => _fullscreen = value);
    } on Object {
      // ignore
    }
  }

  void _showControls() {
    if (!_controlsVisible) {
      setState(() => _controlsVisible = true);
    }
    _restartHideTimer();
  }

  void _restartHideTimer() {
    _hideTimer?.cancel();
    if (_engine.isPaused || _seeking || _drawerVisible || _messageVisible) {
      return;
    }
    _hideTimer = Timer(const Duration(milliseconds: 3500), () {
      if (!mounted) return;
      if (_engine.isPaused || _seeking || _drawerVisible || _messageVisible) {
        return;
      }
      setState(() => _controlsVisible = false);
    });
  }

  void _togglePlayPause() {
    final nextPaused = !_engine.isPaused;
    _engine.setPaused(nextPaused);
    _flashCenterIcon(nextPaused ? AppIcons.play : AppIcons.pause);
    _reporter.requestFlush();
    _showControls();
  }

  void _flashCenterIcon(String path) {
    _badgeTimer?.cancel();
    setState(() {
      _centerIconPath = path;
      _showCenterIcon = true;
      _showCenterText = false;
      _centerText = null;
    });
    _badgeTimer = Timer(const Duration(milliseconds: 600), () {
      if (mounted) setState(() => _showCenterIcon = false);
    });
  }

  void _flashCenterText(String text) {
    _badgeTimer?.cancel();
    setState(() {
      _centerText = text;
      _showCenterText = true;
      _showCenterIcon = false;
      _centerIconPath = null;
    });
    _badgeTimer = Timer(const Duration(milliseconds: 600), () {
      if (mounted) setState(() => _showCenterText = false);
    });
  }

  void _seekRelative(double delta) {
    _engine.seek(delta, relative: true);
    _flashCenterText('${delta > 0 ? '+' : ''}${delta.toInt()}s');
    _reporter.requestFlush();
    _showControls();
  }

  void _onSeek(double target) {
    _engine.seek(target);
    _reporter.requestFlush();
    _showControls();
  }

  void _startSpeedBoost(double speed) {
    _normalSpeed = _engine.speed;
    _engine.setSpeed(speed);
    setState(() => _speedBoost = true);
    _showControls();
  }

  void _endSpeedBoost() {
    _engine.setSpeed(_normalSpeed);
    setState(() => _speedBoost = false);
  }

  void _volumeRelative(int delta) {
    _engine.setVolumeRelative(delta).then((_) {
      if (mounted) _flashCenterText('音量 ${_engine.volume.round()}');
      _reporter.requestFlush();
    });
  }

  void _toggleMute() {
    _engine.toggleMute().then((_) {
      if (!mounted) return;
      _flashCenterText(_engine.volume <= 0 ? '静音' : '音量 ${_engine.volume.round()}');
      _reporter.requestFlush();
    });
  }

  void _cycleSubtitle() {
    _engine.cycleSubtitle();
    _flashCenterText('切换字幕');
    _reporter.requestFlush();
  }

  void _cycleAudio() {
    _engine.cycleAudio();
    _flashCenterText('切换音轨');
    _reporter.requestFlush();
  }

  Future<void> _toggleFullscreen() async {
    try {
      final current = await windowManager.isFullScreen();
      await windowManager.setFullScreen(!current);
      if (mounted) setState(() => _fullscreen = !current);
    } on Object {
      // ignore
    }
    _showControls();
  }

  void _onEscape() {
    if (_drawerVisible) {
      _closeDrawer();
      return;
    }
    if (_fullscreen) {
      _toggleFullscreen();
      return;
    }
    _back();
  }

  void _previousEpisode() {
    if (!_hasPrevious) return;
    final index = widget.payload.currentIndex;
    if (index <= 0) return;
    final entry = widget.payload.playlist[index - 1];
    if (entry.itemId != null) _requestItem(entry.itemId!);
  }

  void _nextEpisode() {
    final id = _nextId;
    if (id != null) _requestItem(id);
  }

  void _openDrawer(String tab) {
    setState(() => _drawerVisible = true);
    _drawerKey.currentState?.openTab(tab);
    _hideTimer?.cancel();
    _showControls();
  }

  void _closeDrawer() {
    setState(() => _drawerVisible = false);
    _focusNode.requestFocus();
    _restartHideTimer();
  }

  void _toggleDrawer() {
    if (_drawerVisible) {
      _closeDrawer();
    } else {
      _openDrawer('episodes');
    }
  }

  void _onEpisodeSelected(int itemId) {
    _closeDrawer();
    _requestItem(itemId);
  }

  void _onSpeedSelected(double speed) {
    _normalSpeed = speed;
    _engine.setSpeed(speed);
    _reporter.requestFlush();
  }

  void _onSubtitleSelected(String? id) {
    _engine.setSubtitleTrack(id);
    _reporter.requestFlush();
  }

  void _onAudioSelected(String? id) {
    _engine.setAudioTrack(id);
    _reporter.requestFlush();
  }

  void _onProgressAuthError() {
    widget.app.logger.warning('播放进度凭证已失效，请从网页重新打开播放');
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(
      const SnackBar(
        content: Text('播放进度凭证已失效，请返回网页重新打开播放'),
        duration: Duration(seconds: 4),
      ),
    );
  }

  int? get _nextId {
    final payload = widget.payload;
    if (payload.playlist.isNotEmpty && payload.currentIndex >= 0) {
      final index = payload.currentIndex;
      if (index + 1 < payload.playlist.length) {
        return payload.playlist[index + 1].itemId;
      }
    }
    return payload.nextItemId;
  }

  String get _nextTitle {
    final payload = widget.payload;
    final id = _nextId;
    if (id != null) {
      for (final entry in payload.playlist) {
        if (entry.itemId == id) {
          return entry.title.isNotEmpty ? entry.title : entry.code;
        }
      }
    }
    return payload.nextTitle;
  }

  bool get _hasPrevious {
    final payload = widget.payload;
    return payload.playlist.isNotEmpty && payload.currentIndex > 0;
  }

  bool get _hasNext => _nextId != null;

  String get _subtitleHint {
    if (_engine.subtitleTracks.isNotEmpty) return '';
    if (widget.payload.subtitles.isNotEmpty) return '外挂字幕加载中…';
    return '片中无字幕轨道';
  }

  void _onCardPrimary() {
    final mode = _cardMode;
    _hideMessage();
    if (mode == 'end') {
      final id = _nextId;
      if (id != null) {
        _requestItem(id);
      } else {
        _back();
      }
      return;
    }
    _retry();
  }

  void _onCardSecondary() {
    _hideMessage();
    _back();
  }

  @override
  void dispose() {
    widget.app.configNotifier.removeListener(_onConfigChanged);
    _engine.removeListener(_onEngineChanged);
    _watchdog?.cancel();
    _hideTimer?.cancel();
    _badgeTimer?.cancel();
    _keyboard.dispose();
    _focusNode.dispose();
    if (!_shutdownDone) {
      unawaited(_shutdownPlayback());
    }
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final video = _engine.videoController;
    return Scaffold(
      backgroundColor: Colors.black,
      body: Focus(
        focusNode: _focusNode,
        autofocus: true,
        onKeyEvent: _keyboard.handle,
        child: MouseRegion(
          cursor: _controlsVisible ? SystemMouseCursors.basic : SystemMouseCursors.none,
          onHover: (_) => _showControls(),
          child: GestureDetector(
            behavior: HitTestBehavior.opaque,
            onTap: _showControls,
            onDoubleTap: _toggleFullscreen,
            child: Stack(
              fit: StackFit.expand,
              children: [
                if (video != null)
                  Video(
                    controller: video,
                    fit: BoxFit.contain,
                    fill: Colors.black,
                    controls: null,
                    wakelock: true,
                  )
                else
                  const ColoredBox(color: Colors.black),
                ControlsOverlay(
                  visible: _controlsVisible,
                  title: widget.payload.title,
                  seriesTitle: widget.payload.seriesTitle,
                  position: _engine.position,
                  duration: _engine.duration,
                  bufferedRanges: _engine.bufferedRanges,
                  speed: _engine.speed,
                  paused: _engine.isPaused,
                  fullscreen: _fullscreen,
                  loading: _engine.isLoading || _engine.isBuffering,
                  networkSpeed: _engine.networkSpeed,
                  hasPrevious: _hasPrevious,
                  hasNext: _hasNext,
                  speedBoost: _speedBoost,
                  speedBoostValue: 2.0,
                  centerIconPath: _centerIconPath,
                  centerText: _centerText,
                  showCenterIcon: _showCenterIcon,
                  showCenterText: _showCenterText,
                  onBack: _back,
                  onPlayPause: _togglePlayPause,
                  onPrevious: _previousEpisode,
                  onNext: _nextEpisode,
                  onSeek: _onSeek,
                  onSeekingChanged: (seeking) {
                    setState(() => _seeking = seeking);
                    if (seeking) {
                      _hideTimer?.cancel();
                    } else {
                      _restartHideTimer();
                    }
                  },
                  onSpeed: () => _openDrawer('speed'),
                  onEpisodes: () => _openDrawer('episodes'),
                  onTracks: () => _openDrawer('tracks'),
                  onFullscreen: _toggleFullscreen,
                ),
                PlayerDrawer(
                  key: _drawerKey,
                  visible: _drawerVisible,
                  playlist: widget.payload.playlist,
                  currentItemId: widget.payload.itemId,
                  currentSpeed: _engine.speed,
                  subtitles: _engine.subtitleTracks,
                  audioTracks: _engine.audioTracks,
                  currentSid: _engine.currentSubtitleId,
                  currentAid: _engine.currentAudioId,
                  subtitleHint: _subtitleHint,
                  onClose: _closeDrawer,
                  onEpisodeSelected: _onEpisodeSelected,
                  onSpeedSelected: _onSpeedSelected,
                  onSubtitleSelected: _onSubtitleSelected,
                  onAudioSelected: _onAudioSelected,
                ),
                MessageCard(
                  visible: _messageVisible,
                  title: _cardTitle,
                  description: _cardDescription,
                  primary: _cardPrimary,
                  secondary: _cardSecondary,
                  countdown: _cardCountdown,
                  onPrimary: _onCardPrimary,
                  onSecondary: _onCardSecondary,
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}
