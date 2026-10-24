import 'dart:convert';
import 'dart:io';

import '../core/version.dart';

/// JavaScript compatibility shim injected at document start.
///
/// The React app already knows `window.StrmActionNative` and the older
/// `window.pywebview.api`. Keeping both means the web frontend needs no
/// changes for the Flutter migration.
String buildBridgeScript({bool isTV = false}) {
  final desktop = Platform.isWindows || Platform.isMacOS;
  final versionLiteral = jsonEncode(appVersion);
  return '''
(function () {
  if (window.__strmactionFlutterBridgeInstalled) return;
  window.__strmactionFlutterBridgeInstalled = true;

  function invoke(method) {
    var args = Array.prototype.slice.call(arguments, 1);
    return new Promise(function (resolve, reject) {
      function send() {
        if (window.flutter_inappwebview &&
            typeof window.flutter_inappwebview.callHandler === 'function') {
          window.flutter_inappwebview
            .callHandler.apply(window.flutter_inappwebview, ['strmaction', method].concat(args))
            .then(function (result) {
              try {
                resolve(typeof result === 'string' ? JSON.parse(result) : result);
              } catch (e) {
                resolve(result);
              }
            })
            .catch(reject);
        } else {
          setTimeout(send, 25);
        }
      }
      send();
    });
  }

  var api = {
    isDesktop: function () { return $desktop; },
    version: function () { return $versionLiteral; },
    playItem: function (payload) {
      return invoke('playItem', typeof payload === 'string' ? payload : JSON.stringify(payload));
    },
    stopPlayback: function () { return invoke('stopPlayback'); },
    openSettings: function () { return invoke('openSettings'); },
    get_settings: function () { return invoke('get_settings'); },
    save_settings: function (data) {
      return invoke('save_settings', typeof data === 'string' ? data : JSON.stringify(data));
    },
    retryConnection: function () { return invoke('retryConnection'); },
    getConnectionError: function () { return invoke('getConnectionError'); },
    quit: function () { return invoke('quit'); }
  };

  window.pywebview = { api: api };
  window._strmaction_api = api;
  window.StrmActionNative = {
    isCompanion: function () { return true; },
    isTV: function () { return $isTV; },
    requestPlayback: function (request) { return invoke('requestPlayback', request); },
    isDesktop: function () { return $desktop; },
    version: function () { return $versionLiteral; },
    playItem: function (payload) { return api.playItem(payload); },
    stopPlayback: function () { return api.stopPlayback(); },
    openSettings: function () { return api.openSettings(); },
    quit: function () { return api.quit(); }
  };
  window._strmaction_bridge = { api: api };

  function announce() {
    try { window.dispatchEvent(new Event('pywebviewready')); } catch (e) {}
    try { window.dispatchEvent(new Event('strmaction:desktop-ready')); } catch (e) {}
  }
  announce();
  setTimeout(announce, 0);
  setTimeout(announce, 250);
})();
''';
}
