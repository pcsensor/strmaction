import 'dart:async';
import 'dart:collection';
import 'dart:convert';
import 'dart:io';

import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_inappwebview/flutter_inappwebview.dart';
import 'package:url_launcher/url_launcher.dart';
import 'package:window_manager/window_manager.dart';

import '../app_controller.dart';
import '../core/config.dart';
import '../core/http_api.dart';
import '../core/redaction.dart';
import '../core/version.dart';
import '../core/trust.dart';
import '../features/connection/error_page.dart';
import '../features/settings/settings_dialog.dart';
import '../models/playback_payload.dart';
import '../player/player_page.dart';
import 'bridge_script.dart';

class WebShellPage extends StatefulWidget {
  final AppController app;

  const WebShellPage({super.key, required this.app});

  @override
  State<WebShellPage> createState() => _WebShellPageState();
}

class _WebShellPageState extends State<WebShellPage> {
  InAppWebViewController? _webController;
  WebViewEnvironment? _webViewEnvironment;
  String? _url;
  bool _loading = true;
  bool _checking = false;
  String _error = '';
  bool _playerOpen = false;
  int? _pendingRequestId;
  bool _bootstrapped = false;
  bool _isTv = false;
  bool _requestingPlayback = false;

  AppController get app => widget.app;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) => _bootstrap());
  }

  Future<void> _bootstrap() async {
    if (_bootstrapped) return;
    _bootstrapped = true;
    if (Platform.isAndroid) {
      _isTv = await const MethodChannel('strmaction/native').invokeMethod<bool>('isTV') ?? false;
    }
    if (Platform.isWindows) {
      try {
        _webViewEnvironment = await WebViewEnvironment.create(
          settings: WebViewEnvironmentSettings(
            userDataFolder: app.paths.webviewDataDir,
          ),
        );
      } on Object catch (error) {
        app.logger.warning('WebView2 环境创建失败，使用默认目录：$error');
      }
    }
    if (!app.config.isConfigured || app.options.settings) {
      await _showSettings(allowCancel: app.config.isConfigured);
      if (!app.config.isConfigured) {
        setState(() {
          _loading = false;
          _error = '尚未配置服务器地址';
        });
        return;
      }
    }
    await _checkAndLoad();
  }

  Future<void> _checkAndLoad() async {
    if (!app.config.isConfigured) {
      setState(() {
        _loading = false;
        _error = '尚未配置服务器地址';
      });
      return;
    }
    setState(() {
      _checking = true;
      _error = '';
      _loading = true;
    });
    final result = await ApiClient(app.config).checkHealth();
    if (!mounted) return;
    if (!result.ok) {
      app.setLastError(result.message);
      setState(() {
        _checking = false;
        _loading = false;
        _error = result.message;
      });
      return;
    }
    app.setLastError('');
    setState(() {
      _checking = false;
      _url ??= _isTv ? '${app.config.serverUrl}/?tv=1' : app.config.serverUrl;
    });
    final controller = _webController;
    if (controller != null && _url != null) {
      await controller.loadUrl(urlRequest: URLRequest(url: WebUri(_url!)));
    }
    if (mounted) setState(() => _loading = false);
  }

  Future<String> _cookie() async {
    final cookies = await CookieManager.instance().getCookies(url: WebUri(app.config.serverUrl));
    return cookies.map((c) => '${c.name}=${c.value}').join('; ');
  }

  Future<void> _refreshAccount() async {
    if (!app.config.isConfigured) return;
    try {
      final auth = await ApiClient(app.config).request('/api/auth/state', cookie: await _cookie());
      final user = auth['user'];
      app.accountKey = user is Map ? '${app.config.serverUrl}|${user['id']}' : null;
    } on Object { app.accountKey = null; }
  }

  Future<Map<String, dynamic>> _startPlayback(Map<String, dynamic> request) async {
    if (_requestingPlayback || _playerOpen) return {'ok': false, 'error': '播放器正在打开'};
    _requestingPlayback = true;
    try {
      final id = request['itemId'];
      if (id is! int || id <= 0) throw const ConfigException('条目 ID 无效');
      await _refreshAccount();
      final mode = request['mode'] ?? app.config.playbackOverrides[app.accountKey];
      final raw = await ApiClient(app.config).request('/api/play/$id', cookie: await _cookie(), body: {
        if (mode == 'builtin' || mode == 'copy') 'mode': mode,
        if (request['mediaFileId'] != null) 'media_file_id': request['mediaFileId'],
      });
      if (!app.config.inheritCacheDefaults) {
        raw['buffer_limit_mb'] = app.config.cacheLimitMb;
        raw['disk_cache_limit_mb'] = app.config.diskCacheLimitMb;
      }
      final payload = PlaybackPayload.fromJson(raw, app.config.serverUrl);
      if (payload.mode == 'copy') {
        await Clipboard.setData(ClipboardData(text: payload.playUrl));
        if (mounted) ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('已复制所选版本的播放链接')));
      } else {
        if (Platform.isAndroid || Platform.isIOS) {
          await const MethodChannel('strmaction/native').invokeMethod<void>('trust', app.config.trustedCaPem);
        }
        unawaited(_openPlayer(payload));
      }
      return {'ok': true, 'mode': payload.mode};
    } on Object catch (error) {
      return {'ok': false, 'error': '$error'};
    } finally { _requestingPlayback = false; }
  }

  Future<bool> _showSettings({required bool allowCancel}) async {
    await _refreshAccount();
    if (!mounted) return false;
    final result = await showDialog<AppConfig>(
      context: context,
      barrierDismissible: allowCancel,
      builder: (_) => SettingsDialog(
        accountKey: app.accountKey,
        initial: app.config,
        allowCancel: allowCancel,
      ),
    );
    if (result == null) return false;
    final serverChanged = await app.saveSettings(result);
    if (!mounted) return serverChanged;
    if (serverChanged || _url == null) {
      setState(() {
        _url = app.config.serverUrl;
        _error = '';
      });
      await _checkAndLoad();
    }
    return serverChanged;
  }

  Future<bool> _saveSettingsFromBridge(dynamic data) async {
    final decoded = data is String ? jsonDecode(data) : data;
    if (decoded is! Map) {
      throw const ConfigException('设置格式不正确');
    }
    final next = app.config.copyWith(
      serverUrl: (decoded['server_url'] ?? app.config.serverUrl).toString(),
      cacheLimitMb: int.tryParse('${decoded['cache_limit_mb'] ?? app.config.cacheLimitMb}') ??
          app.config.cacheLimitMb,
      allowSelfSignedHttps: decoded.containsKey('allow_self_signed_https')
          ? decoded['allow_self_signed_https'] == true
          : app.config.allowSelfSignedHttps,
    ).normalized();
    final serverChanged = await app.saveSettings(next);
    if (!mounted) return serverChanged;
    if (serverChanged) {
      setState(() {
        _url = app.config.serverUrl;
        _error = '';
      });
      await _checkAndLoad();
    }
    return serverChanged;
  }

  Future<dynamic> _handleBridge(String method, dynamic arg) async {
    switch (method) {
      case 'requestPlayback':
        final decoded = arg is String ? jsonDecode(arg) : arg;
        if (decoded is! Map) return {'ok': false, 'error': '播放参数无效'};
        return _startPlayback(Map<String, dynamic>.from(decoded));
      case 'playItem':
        try {
          final decoded = arg is String ? jsonDecode(arg) : arg;
          if (decoded is! Map) {
            return jsonEncode({'ok': false, 'error': '播放数据格式不正确'});
          }
          final payload = PlaybackPayload.fromJson(
            Map<String, dynamic>.from(decoded),
            app.config.serverUrl,
          );
          app.logger.info(
            '内嵌播放请求 item=${payload.itemId} url=${redactUrl(payload.playUrl)} '
            'headers=${redactHeaders(payload.headers).length}',
          );
          if (payload.headers.isNotEmpty) {
            app.logger.debug('播放请求头字段：${payload.headers.keys.join(', ')}');
          }
          unawaited(_openPlayer(payload));
          return jsonEncode({'ok': true});
        } on PlaybackPayloadException catch (error) {
          app.logger.warning('播放请求校验失败：${error.message}');
          return jsonEncode({'ok': false, 'error': error.message});
        } on Object catch (error) {
          app.logger.warning('播放请求失败：$error');
          return jsonEncode({'ok': false, 'error': '播放请求失败'});
        }
      case 'stopPlayback':
        if (_playerOpen && mounted) {
          Navigator.of(context).maybePop();
        }
        return jsonEncode({'ok': true});
      case 'openSettings':
        await _showSettings(allowCancel: true);
        return jsonEncode({'ok': true});
      case 'get_settings':
        return jsonEncode({
          'ok': true,
          'server_url': app.config.serverUrl,
          'cache_limit_mb': app.config.cacheLimitMb,
          'allow_self_signed_https': app.config.allowSelfSignedHttps,
          'version': appVersion,
        });
      case 'save_settings':
        try {
          await _saveSettingsFromBridge(arg);
          return jsonEncode({'ok': true, 'restart_required': false});
        } on Object catch (error) {
          return jsonEncode({'ok': false, 'error': '$error'});
        }
      case 'retryConnection':
        unawaited(_checkAndLoad());
        return jsonEncode({'ok': true});
      case 'getConnectionError':
        return jsonEncode({'ok': true, 'error': app.lastError});
      case 'quit':
        try {
          await windowManager.hide();
        } on Object {
          // ignore
        }
        try {
          await app.shutdown().timeout(const Duration(milliseconds: 1500));
        } on Object {
          // ignore
        }
        try {
          await windowManager.destroy();
        } on Object {
          // ignore
        }
        if (Platform.isAndroid || Platform.isIOS) return {'ok': true};
        exit(0);
      default:
        return jsonEncode({'ok': false, 'error': '未知的桌面端方法：$method'});
    }
  }

  Future<void> _openPlayer(PlaybackPayload payload) async {
    if (!mounted || _playerOpen) return;
    _playerOpen = true;
    _pendingRequestId = null;
    await Navigator.of(context).push(
      PageRouteBuilder<void>(
        pageBuilder: (context, animation, secondaryAnimation) => PlayerPage(
          app: app,
          payload: payload,
          onRequestItem: (id) => _pendingRequestId = id,
        ),
        transitionDuration: Duration.zero,
        reverseTransitionDuration: Duration.zero,
        allowSnapshotting: false,
      ),
    );
    _playerOpen = false;
    final pending = _pendingRequestId;
    _pendingRequestId = null;
    if (pending != null) {
      _requestItem(pending);
    } else {
      _dispatchProgressUpdated();
    }
  }

  void _requestItem(int itemId) {
    unawaited(_startPlayback({'itemId': itemId, 'mode': 'builtin'}));
  }

  void _dispatchProgressUpdated() {
    _webController?.evaluateJavascript(
      source: "window.dispatchEvent(new CustomEvent('strmaction:progress-updated'));",
    );
  }

  bool _isAllowed(Uri uri) {
    if (uri.scheme == 'about' ||
        uri.scheme == 'data' ||
        uri.scheme == 'file' ||
        uri.scheme == 'qrc') {
      return true;
    }
    final server = Uri.tryParse(app.config.serverUrl);
    if (server == null) return false;
    return uri.scheme == server.scheme &&
        uri.host == server.host &&
        (uri.port == server.port || (uri.port == 80 && server.port == 0) ||
            (uri.port == 443 && server.port == 0));
  }

  Future<void> _openExternal(Uri uri) async {
    try {
      await launchUrl(uri, mode: LaunchMode.externalApplication);
    } on Object catch (error) {
      app.logger.warning('打开外部链接失败：$error');
    }
  }

  InAppWebViewSettings _settings() {
    return InAppWebViewSettings(
      useShouldOverrideUrlLoading: true,
      javaScriptEnabled: true,
      applicationNameForUserAgent: 'StrmActionCompanion/2.0',
      mediaPlaybackRequiresUserGesture: false,
      allowsInlineMediaPlayback: true,
      cacheEnabled: true,
      incognito: false,
      supportMultipleWindows: false,
      isInspectable: kDebugMode,
      transparentBackground: false,
    );
  }

  Widget _buildWebView() {
    final url = _url;
    if (url == null) {
      return _SetupPrompt(
        onSettings: () => _showSettings(allowCancel: false),
        error: _error,
      );
    }
    return InAppWebView(
      webViewEnvironment: _webViewEnvironment,
      initialUrlRequest: URLRequest(url: WebUri(url)),
      initialSettings: _settings(),
      initialUserScripts: UnmodifiableListView<UserScript>([
        UserScript(
          source: buildBridgeScript(isTV: _isTv),
          injectionTime: UserScriptInjectionTime.AT_DOCUMENT_START,
          forMainFrameOnly: true,
        ),
      ]),
      onWebViewCreated: (controller) {
        _webController = controller;
        controller.addJavaScriptHandler(
          handlerName: 'strmaction',
          callback: (args) async {
            final origin = await controller.getUrl();
            if (origin == null || !_isAllowed(origin)) return {'ok': false, 'error': '页面来源不受信任'};
            final method = args.isNotEmpty ? '${args[0]}' : '';
            final arg = args.length > 1 ? args[1] : null;
            try {
              return await _handleBridge(method, arg);
            } on Object catch (error) {
              app.logger.warning('Bridge 调用失败 $method：$error');
              return jsonEncode({'ok': false, 'error': '$error'});
            }
          },
        );
      },
      onLoadStart: (controller, url) {
        if (mounted) {
          setState(() {
            _loading = true;
            _error = '';
          });
        }
      },
      onLoadStop: (controller, url) async {
        if (!mounted) return;
        setState(() => _loading = false);
        await _refreshAccount();
        try {
          await controller.evaluateJavascript(source: buildBridgeScript(isTV: _isTv));
        } on Object {
          // The document may be navigating again.
        }
      },
      onProgressChanged: (controller, progress) {
        if (progress >= 100 && mounted && _loading) {
          setState(() => _loading = false);
        }
      },
      onReceivedError: (controller, request, error) {
        if (request.isForMainFrame == false) return;
        if (mounted) {
          setState(() {
            _loading = false;
            _error = error.description.isEmpty ? '页面加载失败' : error.description;
          });
        }
      },
      onReceivedHttpError: (controller, request, response) {
        if (request.isForMainFrame == false) return;
        if (response.statusCode != null && response.statusCode! >= 400) {
          if (mounted) {
            setState(() {
              _loading = false;
              _error = '服务器页面返回 HTTP ${response.statusCode}';
            });
          }
        }
      },
      shouldOverrideUrlLoading: (controller, navigationAction) async {
        final uri = navigationAction.request.url;
        if (uri == null) return NavigationActionPolicy.ALLOW;
        if (_isAllowed(uri)) return NavigationActionPolicy.ALLOW;
        if (uri.scheme == 'http' || uri.scheme == 'https') {
          await _openExternal(uri);
        }
        return NavigationActionPolicy.CANCEL;
      },
      onCreateWindow: (controller, action) async => false,
      onReceivedServerTrustAuthRequest: (controller, challenge) async {
        return ServerTrustAuthResponse(
          action: await verifyWebViewHost(app.config, challenge.protectionSpace.host, challenge.protectionSpace.port ?? 443)
              ? ServerTrustAuthResponseAction.PROCEED : ServerTrustAuthResponseAction.CANCEL,
        );
      },
    );
  }

  @override
  Widget build(BuildContext context) {
    return PopScope(
      canPop: false,
      child: Scaffold(
        backgroundColor: const Color(0xFF0B0E13),
        body: Stack(
          fit: StackFit.expand,
          children: [
            _buildWebView(),
            if (_loading || _checking)
              const ColoredBox(
                color: Color(0xD90B0E13),
                child: Center(
                  child: CircularProgressIndicator(color: Color(0xFFF0A94D)),
                ),
              ),
            if (_error.isNotEmpty && !_loading)
              ErrorPage(
                message: _error,
                onRetry: _checkAndLoad,
                onSettings: () => _showSettings(allowCancel: true),
              ),
          ],
        ),
      ),
    );
  }
}

class _SetupPrompt extends StatelessWidget {
  final VoidCallback onSettings;
  final String error;

  const _SetupPrompt({required this.onSettings, required this.error});

  @override
  Widget build(BuildContext context) {
    return ColoredBox(
      color: const Color(0xFF0B0E13),
      child: Center(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            const Icon(Icons.settings_remote_rounded, size: 48, color: Color(0xFFF0A94D)),
            const SizedBox(height: 16),
            const Text(
              'StrmAction Desktop',
              style: TextStyle(color: Colors.white, fontSize: 22, fontWeight: FontWeight.bold),
            ),
            const SizedBox(height: 8),
            Text(
              error.isEmpty ? '请先配置服务器地址，然后登录。' : error,
              style: const TextStyle(color: Color(0xFFA9B0BE), fontSize: 13),
            ),
            const SizedBox(height: 20),
            FilledButton(
              style: FilledButton.styleFrom(
                backgroundColor: const Color(0xFFF0A94D),
                foregroundColor: const Color(0xFF17120B),
              ),
              onPressed: onSettings,
              child: const Text('打开设置'),
            ),
          ],
        ),
      ),
    );
  }
}
