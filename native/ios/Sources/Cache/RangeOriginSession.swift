import Foundation
import Network

/// Automatic tuning is shared by demand reads and speculation, never a user
/// setting. Two initial connections, four maximum, 4–8 MiB network segments.
final class RangeDownloadPolicy {
    private(set) var concurrency = 2
    private(set) var segmentBytes: Int64 = 4 * 1_048_576
    private var healthy = 0
    private var lastRate: Double = 0
    func completed(bytes: Int64, seconds: Double) {
        guard seconds > 0 else { return }
        let rate = Double(bytes) / seconds
        if seconds > 15 || (lastRate > 0 && rate < lastRate * 0.5) { failed() }
        else {
            healthy += 1
            if healthy >= 2 {
                concurrency = min(4, concurrency + 1)
                if rate >= 2 * 1_048_576 { segmentBytes = 8 * 1_048_576 }
                healthy = 0
            }
        }
        lastRate = rate
    }
    func failed() { concurrency = max(1, concurrency - 1); segmentBytes = 4 * 1_048_576; healthy = 0; lastRate = 0 }
}

final class OriginRequest {
    let id = UUID()
    let start: Int64
    let end: Int64?
    let pace: (Int64) -> PaceDecision
    let onMeta: (OriginClient.Meta) -> Void
    let onData: (Data) -> Void
    let onEnd: (Error?) -> Void
    var client: OriginClient?
    var cancelled = false
    var retried = false
    var cancelAction: (() -> Void)?
    init(start: Int64, end: Int64?, pace: @escaping (Int64) -> PaceDecision,
         onMeta: @escaping (OriginClient.Meta) -> Void, onData: @escaping (Data) -> Void,
         onEnd: @escaping (Error?) -> Void) {
        self.start = start; self.end = end; self.pace = pace
        self.onMeta = onMeta; self.onData = onData; self.onEnd = onEnd
    }
    func cancel() { cancelAction?() }
    func resume() { client?.resume() }
}

/// Queue-confined URL lease and connection scheduler. An expired link triggers
/// one 1-byte resolution probe; all queued readers wait for that probe.
final class RangeOriginSession {
    enum SessionError: LocalizedError {
        case rangeMismatch, changed, nonRange
        var errorDescription: String? {
            switch self {
            case .rangeMismatch: return "片源范围读取不一致"
            case .changed: return "片源文件已变化，请重新播放"
            case .nonRange: return "片源使用普通读取"
            }
        }
    }
    let policy = RangeDownloadPolicy()
    private(set) var supportsRanges = false
    private(set) var totalLength: Int64 = 0
    private let queue: DispatchQueue
    private let sourceURL: URL
    private let headers: [String: String]
    private let pool = OriginConnectionPool()
    private var resolved: URL?
    private var validator: String?
    private var version = 0
    private var pending: [OriginRequest] = []
    private var active: [UUID: OriginRequest] = [:]
    private var probe: OriginClient?
    private var closed = false
    private var failure: Error?

    init(url: URL, headers: [String: String], queue: DispatchQueue) {
        sourceURL = url; self.headers = headers; self.queue = queue
    }
    @discardableResult
    func fetch(start: Int64, end: Int64?, pace: @escaping (Int64) -> PaceDecision,
               onMeta: @escaping (OriginClient.Meta) -> Void, onData: @escaping (Data) -> Void,
               onEnd: @escaping (Error?) -> Void) -> OriginRequest {
        let request = OriginRequest(start: start, end: end, pace: pace, onMeta: onMeta, onData: onData, onEnd: onEnd)
        request.cancelAction = { [weak self, weak request] in
            guard let self, let request else { return }
            self.queue.async {
                request.cancelled = true; request.client?.cancel()
                self.pending.removeAll { $0.id == request.id }; self.active.removeValue(forKey: request.id)
                self.pump()
            }
        }
        pending.append(request); pump(); return request
    }
    func stop() {
        closed = true; probe?.cancel(); probe = nil
        for request in active.values { request.cancelled = true; request.client?.cancel() }
        pending.removeAll(); active.removeAll(); pool.close()
    }
    private func pump() {
        guard !closed else { return }
        if let failure {
            let waiting = pending; pending.removeAll()
            waiting.filter { !$0.cancelled }.forEach { $0.onEnd(failure) }; return
        }
        guard !pending.isEmpty else { return }
        if resolved == nil {
            if probe == nil && active.count < policy.concurrency { resolve() }
            return
        }
        guard probe == nil else { return }
        while active.count < policy.concurrency && !pending.isEmpty {
            let request = pending.removeFirst()
            if !request.cancelled { start(request) }
        }
    }
    private func tag(_ meta: OriginClient.Meta) -> String? {
        if let etag = meta.headers["etag"], !etag.hasPrefix("W/") { return etag }
        return meta.headers["last-modified"]
    }
    private func resolve() {
        let client = OriginClient(queue: queue, pool: pool); probe = client
        var bytes = 0
        var next: OriginClient.Meta?
        client.fetch(url: sourceURL, headers: headers, start: 0, end: 1, pace: { _ in .now }, validate: { [weak self] meta in
            guard let self else { return CancellationError() }
            next = meta
            if meta.status == 200 { return self.supportsRanges ? SessionError.changed : SessionError.nonRange }
            guard meta.status == 206, let total = meta.totalLength, total > 0,
                  meta.headers["content-range"] == "bytes 0-0/\(total)", meta.headers["content-length"] == "1" else { return SessionError.rangeMismatch }
            if self.version > 0 && (self.totalLength != total || (self.validator != nil && self.validator != self.tag(meta))) { return SessionError.changed }
            return nil
        }, onMeta: { _ in }, onData: { bytes += $0.count }, onEnd: { [weak self] error in
            guard let self, !self.closed else { return }
            self.probe = nil
            if let meta = next, case SessionError.nonRange? = error {
                self.resolved = meta.url; self.supportsRanges = false
                self.totalLength = meta.totalLength ?? 0; self.version += 1
            } else if let error { self.failure = error }
            else if bytes == 1, let meta = next {
                self.totalLength = meta.totalLength ?? 0; self.validator = self.tag(meta)
                self.resolved = meta.url; self.supportsRanges = true; self.version += 1
            } else { self.failure = SessionError.rangeMismatch }
            self.pump()
        })
    }
    private func start(_ request: OriginRequest) {
        guard let url = resolved else { pending.insert(request, at: 0); return }
        active[request.id] = request
        let leaseVersion = version
        let client = OriginClient(queue: queue, pool: pool); request.client = client
        let started = ProcessInfo.processInfo.systemUptime
        var received: Int64 = 0
        var delivered = false
        var requestHeaders = headers
        if let validator, supportsRanges { requestHeaders["If-Range"] = validator }
        client.fetch(url: url, headers: requestHeaders, start: request.start, end: request.end,
                     pace: request.pace, validate: { [weak self] meta in
            guard let self else { return CancellationError() }
            guard self.supportsRanges else { return nil }
            guard let total = meta.totalLength, total == self.totalLength,
                  self.validator == nil || self.validator == self.tag(meta) else { return SessionError.changed }
            let upper = min(request.end ?? total, total)
            guard meta.status == 206, upper > request.start,
                  meta.headers["content-range"] == "bytes \(request.start)-\(upper - 1)/\(total)",
                  meta.headers["content-length"].flatMap(Int64.init) == upper - request.start else { return SessionError.rangeMismatch }
            return nil
        }, onMeta: { meta in delivered = true; request.onMeta(meta) }, onData: { data in
            received += Int64(data.count); request.onData(data)
        }, onEnd: { [weak self, weak request] error in
            guard let self, let request, !self.closed, !request.cancelled else { return }
            self.active.removeValue(forKey: request.id); request.client = nil
            if let error, !delivered, !request.retried {
                var refresh = false
                if case OriginClient.OriginError.httpStatus(let code) = error { refresh = [401, 403, 410].contains(code) }
                if refresh {
                    if self.version == leaseVersion { self.resolved = nil }
                    request.retried = true; self.pending.insert(request, at: 0); self.pump(); return
                }
                // A pooled keep-alive socket may have been closed by the CDN.
                if error is NWError || error is URLError {
                    request.retried = true; self.pending.insert(request, at: 0); self.pump(); return
                }
            }
            if error == nil { self.policy.completed(bytes: received, seconds: ProcessInfo.processInfo.systemUptime - started) }
            else { self.policy.failed() }
            request.onEnd(error); self.pump()
        })
    }
}
