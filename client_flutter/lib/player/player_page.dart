import 'dart:async';
import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart';
import 'package:window_manager/window_manager.dart';

import '../app_controller.dart';
import '../models/playback_payload.dart';
import '../services/progress_reporter.dart';
import '../services/mobile_window.dart';
import 'input/player_keyboard.dart';
import 'input/latest_value_dispatcher.dart';
import 'media_kit_engine.dart';
import 'native_player_engine.dart';
import 'playback_engine.dart';
import 'widgets/app_icons.dart';
import 'widgets/controls_overlay.dart';
import 'widgets/gesture_feedback.dart';
import 'widgets/message_card.dart';
import 'widgets/player_center_status.dart';
import 'widgets/player_drawer.dart';

class PlayerPage extends StatefulWidget {
  final AppController app;
  final PlaybackPayload payload;
  final bool isTv;
  final ValueChanged<int>? onRequestItem;
  final PlaybackEngine? engine;

  const PlayerPage({
    super.key,
    required this.app,
    required this.payload,
    this.isTv = false,
    this.onRequestItem,
    this.engine,
  });

  @override
  State<PlayerPage> createState() => _PlayerPageState();
}

class _PlayerPageState extends State<PlayerPage> with WidgetsBindingObserver {
  late final PlaybackEngine _engine;
  bool _wasPaused = true;
  bool _locked = false;
  double _tapX = 0;
  double _dragX = 0;
  double _dragY = 0;
  double _dragPosition = 0;
  double _dragStartValue = 0;
  bool _gestureActive = false;
  final ValueNotifier<PlayerGestureValue?> _gestureFeedback = ValueNotifier(null);
  late final LatestValueDispatcher<double> _brightnessAdjustments;
  late final LatestValueDispatcher<int> _volumeAdjustments;
  Timer? _gestureTimer;
  bool get _mobile => defaultTargetPlatform == TargetPlatform.android || defaultTargetPlatform == TargetPlatform.iOS;
  int get _bufferLimit => widget.payload.bufferLimitMb ?? (_mobile && Platform.isAndroid ? 512 : widget.app.config.cacheLimitMb);
  late final ProgressReporter _reporter;
  late final PlayerKeyboardHandler _keyboard;
  final FocusNode _focusNode = FocusNode(debugLabel: 'player');
  final GlobalKey<PlayerDrawerState> _drawerKey = GlobalKey<PlayerDrawerState>();

  Timer? _hideTimer;
  Timer? _badgeTimer;
  Timer? _watchdog;

  bool _controlsVisible = true;
  bool _drawerVisible = false;
  late VideoScaleMode _videoScale;
  bool _seeking = false;
  bool _fullscreen = false;
  bool _speedBoost = false;
  double _normalSpeed = 1.0;
  late double _boostSpeed;
  bool _completionHandled = false;
  bool _messageVisible = false;
  String? _cardMode;
  String? _lastError;
  String? _lastNotice;
  bool _closing = false;
  Future<void>? _shutdownFuture;

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
    _boostSpeed = widget.app.config.boostSpeed;
    _videoScale = videoScaleModeFromId(widget.app.config.videoScale);
    WidgetsBinding.instance.addObserver(this);
    _engine = widget.engine ?? (_mobile ? NativePlayerEngine() : MediaKitEngine(
      caBundlePath: '${widget.app.paths.baseDir}/media-ca.pem',
      trustedCaPem: widget.app.config.trustedCaPem,
      cacheDirectory: '${widget.app.paths.baseDir}/playback-${DateTime.now().microsecondsSinceEpoch}',
      diskLimitMb: widget.payload.diskCacheLimitMb ?? widget.app.config.diskCacheLimitMb,
      logger: widget.app.logger,
      hardwareAcceleration: widget.app.config.playerHardwareAcceleration,
    ));
    _engine.addListener(_onEngineChanged);
    _brightnessAdjustments = LatestValueDispatcher<double>(
      apply: _engine.setBrightnessLevel,
      onError: (error) => widget.app.logger.warning('手势调节失败：$error'),
    );
    _volumeAdjustments = LatestValueDispatcher<int>(
      apply: _engine.setVolume,
      onError: (error) => widget.app.logger.warning('手势调节失败：$error'),
    );
    _reporter = ProgressReporter(
      serverUrl: widget.app.config.serverUrl,
      itemId: widget.payload.itemId,
      playToken: widget.payload.playToken,
      intervalMs: widget.payload.progressIntervalMs,
      verifySsl: true,
      trustedCaPem: widget.app.config.trustedCaPem,
      outboxPath: '${widget.app.paths.baseDir}/progress-outbox.json',
      accountKey: widget.app.accountKey,
      baseRevision: widget.payload.progressRevision,
      onAuthError: _onProgressAuthError,
      onConflict: _onProgressConflict,
      logger: widget.app.logger,
    );
    widget.app.activeProgress = _reporter;
    widget.app.setPlaybackShutdown(_shutdownPlayback);
    _keyboard = PlayerKeyboardHandler(
      boostSpeed: _boostSpeed,
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
    // 连播会关闭当前播放页并新建下一集的页面，倍速必须从持久化配置恢复，
    // 否则每一集都会回到默认的 1.0x。
    _normalSpeed = widget.app.config.customSpeed ?? 1.0;
    widget.app.configNotifier.addListener(_onConfigChanged);
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!mounted) return;
      // 手机上进入播放器就隐藏系统栏：控制栏和画面要铺满整块屏幕。
      // 全屏按钮只负责再锁定横屏，退出播放器时恢复系统栏和方向。
      if (_mobile) unawaited(setMobileFullscreen(false, keepImmersive: true));
      _focusNode.requestFocus();
      _load();
      _refreshFullscreen();
    });
  }

  Future<void> _load({int? resumeMs}) async {
    if (_shutdownFuture != null) return;
    _watchdog?.cancel();
    _watchdog = Timer(const Duration(seconds: 30), () {
      if (!mounted || !_engine.isLoading) return;
      _showError('打开片源超时，请检查网络、链接或证书设置。');
    });
    if (!_mobile) {
      final publicRoots = await rootBundle.loadString('assets/public-roots.pem');
      await File('${widget.app.paths.baseDir}/media-ca.pem').writeAsString('$publicRoots\n${widget.app.config.trustedCaPem}');
    }
    if (!mounted || _shutdownFuture != null) return;
    // 重试时从最后一次有效位置继续，不要回到打开播放器时的续播点。
    final payload = widget.payload.withResumeMs(resumeMs ?? 0);
    await _engine.load(
      payload,
      cacheLimitMb: _bufferLimit,
      tlsVerify: true,
    );
    _watchdog?.cancel();
    _watchdog = null;
    if (!mounted || _shutdownFuture != null) return;
    // A fresh session rebuilds the platform view, so the remembered picture
    // mode has to be handed to it again.
    await _engine.setVideoScale(_videoScale);
    if ((_normalSpeed - 1.0).abs() > 0.001 ||
        widget.app.config.customSpeed != null) {
      await _engine.setSpeed(_normalSpeed);
    }
    if (_engine.errorMessage == null) {
      _reporter.start();
      // 已经记录过进度的会话（例如出错后重试）保留原位置，等待引擎
      // 上报真实位置；不要用打开时的旧续播点把进度拉回去。
      if (!_reporter.hasPosition) {
        _reporter.update(
          payload.resumeMs.clamp(0, 1 << 31),
          durationMs: payload.durationMs,
        );
      }
    }
    _focusNode.requestFocus();
  }

  void _onConfigChanged() {
    _engine.applySettings(
      cacheLimitMb: _bufferLimit,
      tlsVerify: true,
    );
    if ((_boostSpeed - widget.app.config.boostSpeed).abs() > 0.001) {
      setState(() {
        _boostSpeed = widget.app.config.boostSpeed;
        _keyboard.boostSpeed = _boostSpeed;
      });
    }
  }

  void _syncProgress() {
    // 加载、缓存或错误状态下引擎会把位置临时归零（重新装载、切源都会）。
    // 这时的 0 不是用户的实际进度，写回服务端会清空续播点。只在播放器
    // 处于可用状态且位置有效时更新。
    if (_engine.isLoading || _engine.errorMessage != null) return;
    final positionMs = (_engine.position * 1000).round();
    if (positionMs <= 0) return;
    _reporter.update(
      positionMs,
      durationMs: _engine.duration > 0 ? (_engine.duration * 1000).round() : null,
    );
  }

  void _onEngineChanged() {
    if (!mounted || _shutdownFuture != null) return;
    setState(() {});
    _syncProgress();
    final pauseChanged = _wasPaused != _engine.isPaused;
    if (pauseChanged && _engine.isPaused && _engine.position > 0) _reporter.requestFlush();
    _wasPaused = _engine.isPaused;
    if (_engine.completed && !_completionHandled) {
      _onCompleted();
    }
    final notice = _engine.notice;
    if (notice != null && notice != _lastNotice) {
      _lastNotice = notice;
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(notice)));
    }
    final error = _engine.errorMessage;
    if (error == null) {
      _lastError = null;
      if (_messageVisible && _cardMode == 'error' && !_engine.isPaused &&
          !_engine.isLoading && !_engine.isBuffering) {
        _hideMessage();
      }
    } else if (error != _lastError) {
      _lastError = error;
      // 先把出错前最后一次有效位置保存掉，再展示错误卡片。后续退出或重试
      // 都不会用 0 覆盖它。
      _reporter.requestFlush();
      _showError(error);
    }
    if (pauseChanged) {
      if (_engine.isPaused) { _showControls(); }
      else { _restartHideTimer(); }
    }
  }

  void _onCompleted() {
    _completionHandled = true;
    _reporter.finish();
    _reporter.requestFlush();
    final nextId = widget.payload.nextItemId;
    _showMessage(
      mode: 'end',
      title: '播放结束',
      description: nextId != null
          ? '下一集：${widget.payload.nextTitle}'
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
    // 出错时播放器通常还保留最后位置；重试从那里继续，不必从头播。
    final resumeMs = (_engine.position * 1000).round();
    await _engine.stop();
    await _load(resumeMs: resumeMs);
  }

  Future<void> _cleanupStep(String name, Future<void> Function() action,
      {Duration timeout = const Duration(seconds: 3)}) async {
    try {
      await action().timeout(timeout);
    } on Object catch (error) {
      widget.app.logger.warning('播放器退出：$name 失败：$error');
    }
  }

  Future<void> _shutdownPlayback() =>
      _shutdownFuture ??= Future<void>.microtask(_performShutdown);

  Future<void> _performShutdown() async {
    _brightnessAdjustments.dispose(); _volumeAdjustments.dispose();
    _gestureTimer?.cancel();
    _watchdog?.cancel();
    _hideTimer?.cancel();
    _badgeTimer?.cancel();
    await _cleanupStep('暂停', _engine.pause);
    _syncProgress();
    // Stop owns the bounded final upload and persists it before sending.
    await _cleanupStep('保存进度', () => _reporter.stop(flush: true),
        timeout: const Duration(seconds: 13));
    await _cleanupStep('释放引擎', _engine.shutdown);
    if (widget.app.activeProgress == _reporter) {
      widget.app.activeProgress = null;
      widget.app.setPlaybackShutdown(null);
    }
  }

  Future<void> _back() => _close();

  Future<void> _requestItem(int itemId) => _close(itemId: itemId);

  Future<void> _close({int? itemId}) async {
    if (_closing) return;
    _closing = true;
    try {
      await _shutdownPlayback();
    } on Object catch (error) {
      widget.app.logger.warning('播放器退出失败：$error');
    } finally {
      await _cleanupStep('恢复窗口', _exitFullscreenIfNeeded);
      if (mounted) {
        if (itemId != null) {
          widget.onRequestItem?.call(itemId);
          // 先让分集遮罩在播放页背后完成构建，再关闭当前路由。
          // 否则零时长转场会先露出主页一帧，再进入加载遮罩。
          await WidgetsBinding.instance.endOfFrame;
        }
        if (mounted) Navigator.of(context).pop();
      }
    }
  }

  Future<void> _exitFullscreenIfNeeded() async {
    if (_mobile) {
      await setMobileFullscreen(false);
      return;
    }
    if (await windowManager.isFullScreen()) {
      await windowManager.setFullScreen(false);
    }
  }

  Future<void> _refreshFullscreen() async {
    if (_mobile) return;
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

  void _toggleControls() {
    if (_drawerVisible || _messageVisible || _seeking || _gestureActive || _speedBoost) return;
    if (_controlsVisible) {
      _hideTimer?.cancel();
      setState(() => _controlsVisible = false);
    } else {
      _showControls();
    }
  }

  void _restartHideTimer() {
    _hideTimer?.cancel();
    if ((_engine.isPaused && !_locked) || _seeking || _drawerVisible || _messageVisible || _gestureActive) {
      return;
    }
    _hideTimer = Timer(const Duration(milliseconds: 3500), () {
      if (!mounted) return;
      if ((_engine.isPaused && !_locked) || _seeking || _drawerVisible || _messageVisible || _gestureActive) {
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
    if (_closing || _speedBoost) return;
    _normalSpeed = _engine.speed;
    _engine.setSpeed(speed);
    setState(() => _speedBoost = true);
  }

  void _endSpeedBoost() {
    if (_closing || !_speedBoost) return;
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
    if (_mobile) {
      final next = !_fullscreen;
      setState(() => _fullscreen = next);
      // 退出横屏全屏时仍留在播放页，所以系统栏继续保持隐藏。
      await setMobileFullscreen(next, keepImmersive: !next);
      _showControls();
      return;
    }
    try {
      final current = await windowManager.isFullScreen();
      await windowManager.setFullScreen(!current);
      if (mounted) setState(() => _fullscreen = !current);
    } on Object {
      // ignore
    }
    _showControls();
  }

  void _toggleLock() {
    _cancelGesture();
    setState(() => _locked = !_locked);
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
    if (index <= 0 || index > widget.payload.playlist.length) return;
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
    unawaited(widget.app.updateSettings((config) => config.copyWith(customSpeed: speed)));
  }

  void _onBoostSpeedSelected(double speed) {
    setState(() {
      _boostSpeed = speed;
      _keyboard.boostSpeed = speed;
    });
    unawaited(widget.app.updateSettings((config) => config.copyWith(boostSpeed: speed)));
  }

  void _onSubtitleSelected(String? id) {
    _engine.setSubtitleTrack(id);
    _reporter.requestFlush();
  }

  void _onAudioSelected(String? id) {
    _engine.setAudioTrack(id);
    _reporter.requestFlush();
  }

  /// Modes the running engine can actually honour.
  List<VideoScaleMode> get _scaleModes => VideoScaleMode.values
      .where((mode) => mode != VideoScaleMode.stretch || !Platform.isIOS)
      .toList();

  void _onScaleSelected(VideoScaleMode mode) {
    if (_videoScale == mode) {
      _closeDrawer();
      return;
    }
    setState(() => _videoScale = mode);
    unawaited(_engine.setVideoScale(mode));
    unawaited(widget.app.updateSettings((config) => config.copyWith(videoScale: mode.id)));
    _flashCenterText(mode.label);
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

  void _onProgressConflict() {
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(const SnackBar(
      content: Text('播放进度已在其他设备更新，本次进度已保留，请重新打开播放。'),
      duration: Duration(seconds: 5),
    ));
  }

  void _startVerticalGesture(DragStartDetails details) {
    if (_controlsVisible || _locked || _closing) return;
    _gestureTimer?.cancel();
    _hideTimer?.cancel();
    _gestureActive = true;
    _dragY = details.localPosition.dy;
    final kind = details.localPosition.dx < MediaQuery.sizeOf(context).width / 2
        ? PlayerGestureKind.brightness : PlayerGestureKind.volume;
    _dragStartValue = (kind == PlayerGestureKind.brightness ? _engine.brightness ?? 50 : _engine.volume) / 100;
    _gestureFeedback.value = PlayerGestureValue(kind, _dragStartValue);
  }

  void _updateVerticalGesture(DragUpdateDetails details) {
    final feedback = _gestureFeedback.value;
    if (_controlsVisible || _locked || _closing || !_gestureActive || feedback == null) return;
    final target = (_dragStartValue + (_dragY - details.localPosition.dy) /
        MediaQuery.sizeOf(context).height * 1.25)
        .clamp(feedback.kind == PlayerGestureKind.brightness ? 0.02 : 0.0, 1.0).toDouble();
    if (target == feedback.value) return;
    final value = PlayerGestureValue(feedback.kind, target);
    _gestureFeedback.value = value;
    if (value.kind == PlayerGestureKind.brightness) {
      _brightnessAdjustments.schedule(value.value);
    } else {
      _volumeAdjustments.schedule((value.value * 100).round());
    }
  }

  void _finishGesture() {
    if (_closing || !_gestureActive) return;
    _gestureActive = false;
    unawaited(_brightnessAdjustments.flush()); unawaited(_volumeAdjustments.flush());
    _gestureTimer?.cancel();
    _gestureTimer = Timer(const Duration(milliseconds: 700), () { _gestureFeedback.value = null; });
    _restartHideTimer();
  }

  void _cancelGesture() {
    if (_closing) return;
    _gestureActive = false;
    _gestureTimer?.cancel();
    _brightnessAdjustments.cancelPending(); _volumeAdjustments.cancelPending();
    _gestureFeedback.value = null;
  }

  void _startSeekGesture(DragStartDetails details) {
    if (_locked || _closing) return;
    _gestureTimer?.cancel(); _hideTimer?.cancel();
    _gestureActive = true;
    _dragX = details.localPosition.dx;
    _dragPosition = _engine.position;
    _gestureFeedback.value = PlayerGestureValue(PlayerGestureKind.seek, _dragPosition, duration: _engine.duration);
  }

  void _updateSeekGesture(DragUpdateDetails details) {
    if (_locked || _closing || !_gestureActive) return;
    final seconds = _dragPosition + (details.localPosition.dx - _dragX) / MediaQuery.sizeOf(context).width * 120;
    _gestureFeedback.value = PlayerGestureValue(PlayerGestureKind.seek,
        seconds.clamp(0, _engine.duration > 0 ? _engine.duration : 1e12).toDouble(), duration: _engine.duration);
  }

  void _finishSeekGesture() {
    if (_closing) return;
    final feedback = _gestureFeedback.value;
    if (!_gestureActive || feedback?.kind != PlayerGestureKind.seek) return;
    unawaited(_engine.seek(feedback!.value).catchError((Object error) {
      widget.app.logger.warning('手势定位失败：$error');
    }));
    _reporter.requestFlush();
    _finishGesture();
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

  bool get _hasPrevious {
    final payload = widget.payload;
    return payload.playlist.isNotEmpty && payload.currentIndex > 0 && payload.currentIndex <= payload.playlist.length;
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
      final id = widget.payload.nextItemId;
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
    _closing = true;
    _gestureTimer?.cancel();
    _brightnessAdjustments.dispose(); _volumeAdjustments.dispose();
    _gestureFeedback.dispose();
    widget.app.configNotifier.removeListener(_onConfigChanged);
    _engine.removeListener(_onEngineChanged);
    _watchdog?.cancel();
    _hideTimer?.cancel();
    _badgeTimer?.cancel();
    _keyboard.dispose();
    _focusNode.dispose();
    if (_shutdownFuture == null) {
      unawaited(_shutdownPlayback());
    }
    WidgetsBinding.instance.removeObserver(this);
    super.dispose();
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (state != AppLifecycleState.resumed) _reporter.requestFlush();
  }

  @override
  Widget build(BuildContext context) {
    return PopScope(
      canPop: false,
      onPopInvokedWithResult: (didPop, result) { if (!didPop) { if (_drawerVisible) { _closeDrawer(); } else { _back(); } } },
      child: Scaffold(
      backgroundColor: Colors.black,
      resizeToAvoidBottomInset: false,
      body: Focus(
        focusNode: _focusNode,
        autofocus: true,
        onKeyEvent: (node, event) {
          if (_drawerVisible) {
            if (event.logicalKey == LogicalKeyboardKey.escape && event is KeyDownEvent) {
              _closeDrawer(); return KeyEventResult.handled;
            }
            return KeyEventResult.ignored;
          }
          if (widget.isTv && event is KeyDownEvent) {
            if (event.logicalKey == LogicalKeyboardKey.arrowUp) { _openDrawer('tracks'); return KeyEventResult.handled; }
            if (event.logicalKey == LogicalKeyboardKey.arrowDown) { _openDrawer('episodes'); return KeyEventResult.handled; }
            if (event.logicalKey == LogicalKeyboardKey.select || event.logicalKey == LogicalKeyboardKey.enter) {
              if (_messageVisible) { _onCardPrimary(); } else { _togglePlayPause(); }
              return KeyEventResult.handled;
            }
          }
          return _keyboard.handle(node, event);
        },
        child: MouseRegion(
          cursor: _controlsVisible ? SystemMouseCursors.basic : SystemMouseCursors.none,
          onHover: _mobile ? null : (_) => _showControls(),
          child: GestureDetector(
            behavior: HitTestBehavior.opaque,
            onTap: _toggleControls,
            child: Stack(
              key: const ValueKey('player-viewport'),
              fit: StackFit.expand,
              children: [
                // Native views only render; complex gestures stay below UI.
                IgnorePointer(child: RepaintBoundary(child: _engine.buildVideo())),
                if (!_engine.isPiP) Positioned.fill(child: GestureDetector(
            key: const ValueKey('player-gestures'),
            behavior: HitTestBehavior.opaque,
            onTap: _toggleControls,
            onDoubleTapDown: (details) => _tapX = details.localPosition.dx,
            onDoubleTap: () {
              if (_locked) return;
              if (!_mobile) { _toggleFullscreen(); return; }
              final width = MediaQuery.sizeOf(context).width;
              if (_tapX < width * .35) { _seekRelative(-10); }
              else if (_tapX > width * .65) { _seekRelative(10); }
              else { _togglePlayPause(); }
            },
            onLongPressStart: _mobile ? (_) {
              if (_controlsVisible || _locked || _closing) return;
              HapticFeedback.mediumImpact();
              _startSpeedBoost(_boostSpeed);
            } : null,
            onLongPressEnd: _mobile ? (_) => _endSpeedBoost() : null,
            onLongPressCancel: _mobile ? _endSpeedBoost : null,
            onHorizontalDragStart: _mobile ? _startSeekGesture : null,
            onHorizontalDragUpdate: _mobile ? _updateSeekGesture : null,
            onHorizontalDragEnd: _mobile ? (_) => _finishSeekGesture() : null,
            onHorizontalDragCancel: _mobile ? _cancelGesture : null,
            onVerticalDragStart: _mobile ? _startVerticalGesture : null,
            onVerticalDragUpdate: _mobile ? _updateVerticalGesture : null,
            onVerticalDragEnd: _mobile ? (_) => _finishGesture() : null,
            onVerticalDragCancel: _mobile ? _cancelGesture : null,
                  child: const SizedBox.expand(),
                )),
                if (!_engine.isPiP) ControlsOverlay(
                  visible: _controlsVisible && !_locked && !_engine.isPiP,
                  title: widget.payload.title,
                  seriesTitle: widget.payload.seriesTitle,
                  position: _engine.position,
                  duration: _engine.duration,
                  bufferedRanges: _engine.bufferedRanges,
                  speed: _engine.speed,
                  paused: _engine.isPaused,
                  fullscreen: _fullscreen,
                  networkSpeed: _engine.networkSpeed,
                  networkStatus: _engine.networkStatus,
                  hasPrevious: _hasPrevious,
                  hasNext: _hasNext,
                  speedBoost: _speedBoost,
                  speedBoostValue: _boostSpeed,
                  trailingWidth: _mobile ? 100 : 0,
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
                  onFrame: () => _openDrawer('frame'),
                  onFullscreen: _toggleFullscreen,
                ),
                // Playback feedback (volume, mute, seek, play/pause, buffering)
                // must survive the control bar fading out; it used to be drawn
                // inside the overlay and disappeared with it.
                if (!_engine.isPiP) Positioned.fill(
                  child: PlayerCenterStatus(
                    iconPath: _centerIconPath,
                    text: _centerText,
                    showIcon: _showCenterIcon,
                    showText: _showCenterText,
                    loading: _engine.isLoading || _engine.isBuffering,
                  ),
                ),
                if (_mobile && !_engine.isPiP) PlayerGestureFeedback(feedback: _gestureFeedback),
                if (_mobile && !_engine.isPiP && _controlsVisible) Positioned(
                  right: 12 + MediaQuery.viewPaddingOf(context).right,
                  top: 20 + MediaQuery.viewPaddingOf(context).top,
                  child: Row(children: [
                    if (!_locked) IconButton(tooltip: '画中画', icon: const Icon(Icons.picture_in_picture_alt, color: Colors.white), onPressed: _engine.enterPiP),
                    IconButton(tooltip: _locked ? '解锁' : '锁定', icon: Icon(_locked ? Icons.lock : Icons.lock_open, color: Colors.white), onPressed: _toggleLock),
                  ]),
                ),
                if (!_engine.isPiP) PlayerDrawer(
                  key: _drawerKey,
                  visible: _drawerVisible,
                  playlist: widget.payload.playlist,
                  currentItemId: widget.payload.itemId,
                  currentSpeed: _engine.speed,
                  boostSpeed: _boostSpeed,
                  subtitles: _engine.subtitleTracks,
                  audioTracks: _engine.audioTracks,
                  currentSid: _engine.currentSubtitleId,
                  currentAid: _engine.currentAudioId,
                  subtitleHint: _subtitleHint,
                  videoScale: _videoScale,
                  scaleModes: _scaleModes,
                  onClose: _closeDrawer,
                  onEpisodeSelected: _onEpisodeSelected,
                  onSpeedSelected: _onSpeedSelected,
                  onBoostSpeedSelected: _onBoostSpeedSelected,
                  onSubtitleSelected: _onSubtitleSelected,
                  onAudioSelected: _onAudioSelected,
                  onScaleSelected: _onScaleSelected,
                ),
                if (!_engine.isPiP) MessageCard(
                  visible: _messageVisible,
                  title: _cardTitle,
                  description: _cardDescription,
                  primary: _cardPrimary,
                  secondary: _cardSecondary,
                  countdown: _cardCountdown,
                  onPrimary: _onCardPrimary,
                  onSecondary: _onCardSecondary,
                  onDismiss: _cardMode == 'error' ? _hideMessage : null,
                  onCopyLink: _cardMode == 'error' ? () async {
                    await Clipboard.setData(ClipboardData(text: widget.payload.playUrl));
                    if (mounted) _flashCenterText('已复制播放链接');
                  } : null,
                ),
              ],
            ),
          ),
        ),
      ),
    ));
  }
}
