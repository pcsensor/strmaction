import AVFoundation
import Flutter
import KSPlayer
import MediaPlayer
import SwiftUI
import UIKit

/// Native decode/transport and system services; Flutter owns controls and progress.
@MainActor
final class UnifiedPlayerPlugin: NSObject, FlutterPlugin, FlutterStreamHandler {
    let controller = VideoPlayerController()
    private var sink: FlutterEventSink?
    private var timer: Timer?
    private var requestTask: Task<Void, Never>?
    private var subtitleTask: Task<Void, Never>?
    private var subtitles: [SubtitleEntry] = []
    private var selectedExternal: String?
    private var notice: String?
    private var completed = false
    private var title = "StrmAction"
    private var loaded = false
    private var sessionID: String?
    private let originalBrightness = UIScreen.main.brightness
    private var remoteTargets: [(MPRemoteCommand, Any)] = []
    private var interruptionObserver: NSObjectProtocol?
    private var wasPlayingBeforeInterruption = false
    private var lastNowPlayingAt: TimeInterval = 0
    private var lastNowPlayingRate: Double = -1

    static func register(with registrar: FlutterPluginRegistrar) {
        let plugin = UnifiedPlayerPlugin()
        let channel = FlutterMethodChannel(name: "strmaction/player", binaryMessenger: registrar.messenger())
        registrar.addMethodCallDelegate(plugin, channel: channel)
        FlutterEventChannel(name: "strmaction/player/events", binaryMessenger: registrar.messenger()).setStreamHandler(plugin)
        let native = FlutterMethodChannel(name: "strmaction/native", binaryMessenger: registrar.messenger())
        native.setMethodCallHandler { call, result in plugin.handleNative(call, result: result) }
        registrar.register(UnifiedVideoFactory(plugin: plugin, parent: registrar.viewController), withId: "strmaction/video")
        plugin.controller.onPlaybackEnded = { [weak plugin] in plugin?.completed = true; plugin?.emit() }
        plugin.timer = Timer.scheduledTimer(withTimeInterval: 0.5, repeats: true) { [weak plugin] _ in
            Task { @MainActor in plugin?.emit() }
        }
        plugin.installSystemControls()
    }

    private func handleNative(_ call: FlutterMethodCall, result: @escaping FlutterResult) {
        do {
            switch call.method {
            case "configDirectory":
                let root = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0].appendingPathComponent("unified-client", isDirectory: true)
                try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
                result(root.path)
            case "legacySettings":
                let defaults = UserDefaults.standard
                result([
                    "server_url": defaults.string(forKey: "server_url") ?? "",
                    "trusted_ca_pem": TLSTrustStore.shared.snapshot().map(\.pem).joined(separator: "\n"),
                    "cache_limit_mb": PlaybackBufferPreference.limitMb,
                    "disk_cache_limit_mb": DiskCachePreference.limitMb,
                    "inherit_cache_defaults": defaults.object(forKey: PlaybackBufferPreference.defaultsKey) == nil && defaults.object(forKey: DiskCachePreference.defaultsKey) == nil,
                ])
            case "isTV": result(false)
            case "trust":
                let pem = call.arguments as? String ?? ""
                let store = TLSTrustStore.shared
                let previous = store.snapshot().map(\.pem).joined(separator: "\n").trimmingCharacters(in: .whitespacesAndNewlines)
                if previous != pem.trimmingCharacters(in: .whitespacesAndNewlines) {
                    // Validate before replacing a previously usable trust store.
                    if !pem.isEmpty {
                        let roots = CertificateTools.certificates(fromPEM: pem)
                        guard !roots.isEmpty && roots.allSatisfy({ CertificateTools.isSelfSigned($0) }) else { throw TrustAnchorError.noCertificate }
                    }
                    store.removeAll()
                    if !pem.isEmpty { try store.addAnchor(pem: pem) }
                }
                result(nil)
            default: result(FlutterMethodNotImplemented)
            }
        } catch { result(FlutterError(code: "native", message: error.localizedDescription, details: nil)) }
    }

    func handle(_ call: FlutterMethodCall, result: @escaping FlutterResult) {
        switch call.method {
        case "load":
            guard let data = call.arguments as? [String: Any], let raw = data["play_url"] as? String, let url = URL(string: raw) else {
                result(FlutterError(code: "player", message: "播放地址无效", details: nil)); return
            }
            clear()
            do {
                try AVAudioSession.sharedInstance().setCategory(.playback, mode: .moviePlayback)
                try AVAudioSession.sharedInstance().setActive(true)
            } catch {
                result(FlutterError(code: "audio_session", message: error.localizedDescription, details: nil)); return
            }
            loaded = true
            sessionID = data["session_id"] as? String
            let requestSessionID = sessionID
            completed = false
            title = data["title"] as? String ?? "StrmAction"
            if let entries = data["subtitles"], let json = try? JSONSerialization.data(withJSONObject: entries) {
                subtitles = (try? JSONDecoder().decode([SubtitleEntry].self, from: json)) ?? []
            }
            let request = PlaybackRequest(url: url, headers: data["headers"] as? [String: String] ?? [:],
                resumeMs: (data["resume_ms"] as? NSNumber)?.int64Value ?? 0,
                bufferLimitMb: (data["buffer_limit_mb"] as? NSNumber)?.intValue ?? 128,
                diskCacheLimitMb: (data["disk_cache_limit_mb"] as? NSNumber)?.intValue ?? 2048)
            UIApplication.shared.isIdleTimerDisabled = true
            requestTask = Task { [weak self] in
                guard let self, !Task.isCancelled, self.sessionID == requestSessionID else { return }
                await self.controller.load(request, presentationID: requestSessionID)
                guard !Task.isCancelled, self.sessionID == requestSessionID else { return }
                self.emit()
            }
        case "play":
            if completed { controller.seek(toMs: 0); completed = false }
            controller.play()
        case "pause": controller.pause()
        case "seek": completed = false; controller.seek(toMs: (call.arguments as? NSNumber)?.int64Value ?? 0)
        case "speed": controller.setSpeed((call.arguments as? NSNumber)?.doubleValue ?? 1)
        case "volume": SystemVolumeController.shared.set(Float((call.arguments as? NSNumber)?.doubleValue ?? 100) / 100)
        case "brightness": UIScreen.main.brightness = min(1, max(0.02, UIScreen.main.brightness + ((call.arguments as? NSNumber)?.doubleValue ?? 0)))
        case "brightnessLevel": UIScreen.main.brightness = min(1, max(0.02, (call.arguments as? NSNumber)?.doubleValue ?? 0.5))
        case "pip": _ = controller.togglePiP()
        case "audio":
            if let id = call.arguments as? String, let track = controller.ksCoordinator.playerLayer?.player.tracks(mediaType: .audio).first(where: { String($0.trackID) == id }) {
                controller.ksCoordinator.playerLayer?.player.select(track: track)
            }
        case "subtitle": selectSubtitle(call.arguments as? String)
        case "settings":
            if let data = call.arguments as? [String: Any], let value = data["buffer_limit_mb"] as? Int { controller.setBufferLimit(value) }
        case "dispose":
            if let owner = (call.arguments as? [String: Any])?["session_id"] as? String,
               owner != sessionID { result(nil); return }
            clear()
        default: result(FlutterMethodNotImplemented); return
        }
        if !["volume", "brightness", "brightnessLevel"].contains(call.method) { emit() }
        result(nil)
    }

    private func selectSubtitle(_ id: String?) {
        subtitleTask?.cancel()
        notice = nil
        selectedExternal = nil
        controller.clearSubtitle()
        guard let id else { return }
        if id.hasPrefix("external:"), let index = Int(id.dropFirst(9)), subtitles.indices.contains(index) {
            selectedExternal = id
            let entry = subtitles[index]
            subtitleTask = Task { [weak self] in
                guard let self else { return }
                do { try await self.controller.loadSubtitle(entry, serverUrl: "") }
                catch { if !Task.isCancelled { self.notice = "字幕加载失败：\(error.localizedDescription)"; self.selectedExternal = nil } }
                self.emit()
            }
        } else {
            controller.ksCoordinator.subtitleModel.selectedSubtitleInfo = controller.ksCoordinator.subtitleModel.subtitleInfos.first { $0.subtitleID == id }
        }
    }

    func emit() {
        let audio = controller.ksCoordinator.playerLayer?.player.tracks(mediaType: .audio) ?? []
        let model = controller.ksCoordinator.subtitleModel
        let internalSubs: [[String: Any]] = model.subtitleInfos.map { ["id": $0.subtitleID, "title": $0.name] }
        let externalSubs: [[String: Any]] = subtitles.enumerated().map { ["id": "external:\($0.offset)", "title": $0.element.label, "external": true] }
        let loading = loaded && (controller.phase == .resolving || controller.phase == .connecting)
        sink?([
            "session_id": sessionID as Any? ?? NSNull(),
            "position_ms": controller.currentPositionMs, "duration_ms": controller.durationMs,
            "buffered_ms": controller.bufferedPositionMs, "playing": controller.isPlaying,
            "loading": loading, "buffering": controller.phase == .buffering,
            "notice": notice as Any? ?? NSNull(),
            "completed": completed, "error": controller.errorMessage as Any? ?? NSNull(),
            "speed": controller.playbackSpeed, "volume": Double(SystemVolumeController.shared.current) * 100,
            "brightness": Double(UIScreen.main.brightness) * 100,
            "network_speed": controller.networkSpeedBps, "pip": controller.isPiPActive,
            "audio_tracks": audio.map { ["id": String($0.trackID), "title": $0.name] },
            "audio_id": audio.first(where: { $0.isEnabled }).map { String($0.trackID) } as Any? ?? NSNull(),
            "subtitle_tracks": internalSubs + externalSubs,
            "subtitle_id": (selectedExternal ?? model.selectedSubtitleInfo?.subtitleID) as Any? ?? NSNull(),
            "subtitle_text": controller.subtitleText as Any? ?? NSNull(),
            "cached_ranges": controller.cachedSegments.map { ["start_ms": $0.startMs, "end_ms": $0.endMs] },
        ])
        if loaded {
            let rate = controller.isPlaying ? controller.playbackSpeed : 0
            let now = ProcessInfo.processInfo.systemUptime
            guard now - lastNowPlayingAt >= 1 || rate != lastNowPlayingRate else { return }
            lastNowPlayingAt = now; lastNowPlayingRate = rate
            MPNowPlayingInfoCenter.default().nowPlayingInfo = [
                MPMediaItemPropertyTitle: title, MPMediaItemPropertyPlaybackDuration: Double(controller.durationMs) / 1000,
                MPNowPlayingInfoPropertyElapsedPlaybackTime: Double(controller.currentPositionMs) / 1000,
                MPNowPlayingInfoPropertyPlaybackRate: controller.isPlaying ? controller.playbackSpeed : 0,
            ]
        }
    }
    func onListen(withArguments arguments: Any?, eventSink events: @escaping FlutterEventSink) -> FlutterError? { sink = events; emit(); return nil }
    func onCancel(withArguments arguments: Any?) -> FlutterError? { sink = nil; return nil }

    private func installSystemControls() {
        let commands = MPRemoteCommandCenter.shared()
        func add(_ command: MPRemoteCommand, _ handler: @escaping (MPRemoteCommandEvent) -> MPRemoteCommandHandlerStatus) {
            command.isEnabled = true
            remoteTargets.append((command, command.addTarget(handler: handler)))
        }
        add(commands.playCommand) { [weak self] _ in self?.controller.play(); return .success }
        add(commands.pauseCommand) { [weak self] _ in self?.controller.pause(); return .success }
        add(commands.togglePlayPauseCommand) { [weak self] _ in self?.controller.togglePlayPause(); return .success }
        add(commands.changePlaybackPositionCommand) { [weak self] event in
            guard let event = event as? MPChangePlaybackPositionCommandEvent else { return .commandFailed }
            self?.controller.seek(toMs: Int64(event.positionTime * 1000)); return .success
        }
        commands.skipForwardCommand.preferredIntervals = [10]
        commands.skipBackwardCommand.preferredIntervals = [10]
        add(commands.skipForwardCommand) { [weak self] _ in self?.controller.skip(seconds: 10); return .success }
        add(commands.skipBackwardCommand) { [weak self] _ in self?.controller.skip(seconds: -10); return .success }
        interruptionObserver = NotificationCenter.default.addObserver(forName: AVAudioSession.interruptionNotification, object: nil, queue: .main) { [weak self] notification in
            Task { @MainActor in
                guard let self, let value = notification.userInfo?[AVAudioSessionInterruptionTypeKey] as? UInt, let type = AVAudioSession.InterruptionType(rawValue: value) else { return }
                if type == .began { self.wasPlayingBeforeInterruption = self.controller.isPlaying; self.controller.pause() }
                else if self.wasPlayingBeforeInterruption, let raw = notification.userInfo?[AVAudioSessionInterruptionOptionKey] as? UInt, AVAudioSession.InterruptionOptions(rawValue: raw).contains(.shouldResume) { self.controller.play() }
            }
        }
    }
    private func clear() {
        requestTask?.cancel(); requestTask = nil
        subtitleTask?.cancel(); subtitleTask = nil
        controller.destroy()
        try? AVAudioSession.sharedInstance().setActive(false, options: .notifyOthersOnDeactivation)
        subtitles = []; selectedExternal = nil; loaded = false; completed = false
        sessionID = nil; notice = nil
        UIScreen.main.brightness = originalBrightness
        UIApplication.shared.isIdleTimerDisabled = false
        MPNowPlayingInfoCenter.default().nowPlayingInfo = nil
        lastNowPlayingAt = 0; lastNowPlayingRate = -1
    }
}

@MainActor
private final class UnifiedVideoFactory: NSObject, FlutterPlatformViewFactory {
    let plugin: UnifiedPlayerPlugin
    weak var parent: UIViewController?
    init(plugin: UnifiedPlayerPlugin, parent: UIViewController?) { self.plugin = plugin; self.parent = parent }
    func createArgsCodec() -> FlutterMessageCodec & NSObjectProtocol { FlutterStandardMessageCodec.sharedInstance() }
    func create(withFrame frame: CGRect, viewIdentifier viewId: Int64, arguments args: Any?) -> FlutterPlatformView {
        UnifiedVideoView(plugin: plugin, parent: parent, frame: frame,
            sessionID: (args as? [String: Any])?["session_id"] as? String)
    }
}

@MainActor
private final class UnifiedVideoView: NSObject, FlutterPlatformView {
    let host: UIHostingController<VideoSurfaceView>
    init(plugin: UnifiedPlayerPlugin, parent: UIViewController?, frame: CGRect, sessionID: String?) {
        host = UIHostingController(rootView: VideoSurfaceView(controller: plugin.controller, url: URL(string: "about:blank")!, resumeMs: 0, presentationID: sessionID))
        super.init()
        parent?.addChild(host)
        host.view.frame = frame; host.view.backgroundColor = .black
        host.didMove(toParent: parent)
        SystemVolumeController.shared.attach(to: host.view)
    }
    func view() -> UIView { host.view }
    deinit { host.willMove(toParent: nil); host.view.removeFromSuperview(); host.removeFromParent() }
}
