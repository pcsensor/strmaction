import Foundation
import Network
import Security

enum PaceDecision { case now, after(TimeInterval), suspend }

/// HTTP/1.1 byte transport. A session-owned pool reuses fully consumed bounded
/// responses; decoder/backpressure sockets are never returned to the pool early.
final class OriginConnectionPool {
    private var idle: [(String, NWConnection, TimeInterval)] = []
    private func key(_ url: URL) -> String { "\(url.scheme ?? "")://\(url.host ?? ""):\(url.port ?? (url.scheme == "https" ? 443 : 80))" }
    func take(_ url: URL) -> NWConnection? {
        let now = ProcessInfo.processInfo.systemUptime
        idle.removeAll { item in
            if now - item.2 > 15 { item.1.cancel(); return true }
            return false
        }
        guard let index = idle.firstIndex(where: { $0.0 == key(url) }) else { return nil }
        return idle.remove(at: index).1
    }
    func put(_ connection: NWConnection, url: URL) {
        connection.stateUpdateHandler = nil
        if idle.count >= 4 { idle.removeFirst().1.cancel() }
        idle.append((key(url), connection, ProcessInfo.processInfo.systemUptime))
    }
    func close() { idle.forEach { $0.1.cancel() }; idle.removeAll() }
}

final class OriginClient {
    struct Meta {
        let status: Int
        let headers: [String: String]
        let totalLength: Int64?
        let url: URL
    }
    enum OriginError: LocalizedError {
        case invalidURL, malformedResponse, tooManyRedirects, incomplete, timedOut
        case httpStatus(Int)
        var errorDescription: String? {
            switch self {
            case .invalidURL: return "回源地址无效"
            case .malformedResponse: return "回源响应无法解析"
            case .tooManyRedirects: return "回源重定向次数过多"
            case .incomplete: return "片源范围读取不完整"
            case .timedOut: return "回源读取超时"
            case .httpStatus(let code): return "回源返回 HTTP \(code)"
            }
        }
    }
    private let queue: DispatchQueue
    private let pool: OriginConnectionPool?
    private var connection: NWConnection?
    private var cancelled = false
    private var resumeHandler: (() -> Void)?
    init(queue: DispatchQueue, pool: OriginConnectionPool? = nil) { self.queue = queue; self.pool = pool }
    func cancel() {
        queue.async {
            self.cancelled = true
            self.resumeHandler = nil
            self.connection?.cancel(); self.connection = nil
        }
    }
    func resume() { queue.async { let handler = self.resumeHandler; self.resumeHandler = nil; if !self.cancelled { handler?() } } }

    func fetch(url: URL, headers: [String: String], start: Int64, end: Int64?,
               redirectsLeft: Int = 6, pace: @escaping (Int64) -> PaceDecision,
               validate: @escaping (Meta) -> Error? = { _ in nil },
               onMeta: @escaping (Meta) -> Void, onData: @escaping (Data) -> Void,
               onEnd: @escaping (Error?) -> Void) {
        queue.async {
            self.start(url: url, headers: headers, start: start, end: end, redirectsLeft: redirectsLeft,
                       pace: pace, validate: validate, onMeta: onMeta, onData: onData, onEnd: onEnd)
        }
    }

    private func start(url: URL, headers: [String: String], start: Int64, end: Int64?, redirectsLeft: Int,
                       pace: @escaping (Int64) -> PaceDecision, validate: @escaping (Meta) -> Error?,
                       onMeta: @escaping (Meta) -> Void, onData: @escaping (Data) -> Void,
                       onEnd: @escaping (Error?) -> Void) {
        guard !cancelled else { return }
        guard let host = url.host, let scheme = url.scheme?.lowercased(), ["http", "https"].contains(scheme),
              let port = NWEndpoint.Port(rawValue: UInt16(clamping: url.port ?? (scheme == "https" ? 443 : 80))) else {
            onEnd(OriginError.invalidURL); return
        }
        let reused = pool?.take(url)
        let connection: NWConnection
        if let reused { connection = reused }
        else {
            let tcp = NWProtocolTCP.Options(); tcp.noDelay = true; tcp.connectionTimeout = 15
            let parameters: NWParameters
            if scheme == "https" {
                let tls = NWProtocolTLS.Options()
                sec_protocol_options_set_verify_block(tls.securityProtocolOptions, { _, trustRef, complete in
                    let trust = sec_trust_copy_ref(trustRef).takeRetainedValue()
                    let chain = CertificateTools.chain(from: trust)
                    let anchors = TLSTrustStore.shared.anchorCertificates()
                    let verdict = CertificateTools.evaluates(chain: chain, host: host, anchors: anchors)
                    complete(verdict.isTrusted || CertificateTools.isPubliclyTrusted(trust))
                }, queue)
                sec_protocol_options_set_tls_server_name(tls.securityProtocolOptions, host)
                parameters = NWParameters(tls: tls, tcp: tcp)
            } else { parameters = NWParameters(tls: nil, tcp: tcp) }
            connection = NWConnection(host: NWEndpoint.Host(host), port: port, using: parameters)
        }
        self.connection = connection
        let state = StreamState()
        let finish: (Error?, Bool) -> Void = { [weak self] error, reusable in
            guard let self, !state.finished else { return }
            state.finished = true
            self.resumeHandler = nil
            if self.connection === connection { self.connection = nil }
            if reusable, let pool = self.pool { pool.put(connection, url: url) }
            else { connection.cancel() }
            if !self.cancelled { onEnd(error) }
        }
        let send: () -> Void = { [weak self] in
            guard let self, !self.cancelled else { connection.cancel(); return }
            connection.send(content: Self.buildRequest(url: url, headers: headers, start: start, end: end),
                            completion: .contentProcessed { error in if let error { finish(error, false) } })
            self.receive(connection, url: url, headers: headers, start: start, end: end,
                         redirectsLeft: redirectsLeft, state: state, pace: pace, validate: validate,
                         onMeta: onMeta, onData: onData, onEnd: onEnd, finish: finish)
        }
        connection.stateUpdateHandler = { [weak self] value in
            guard let self, !self.cancelled, !state.finished else { return }
            switch value {
            case .ready: if reused == nil { send() }
            case .failed(let error): finish(error, false)
            default: break
            }
        }
        if reused != nil { send() } else { connection.start(queue: queue) }
        queue.asyncAfter(deadline: .now() + 30) { [weak self] in
            guard let self, !self.cancelled, !state.finished, state.lastRead == 0 else { return }
            finish(OriginError.timedOut, false)
        }
    }
    private final class StreamState {
        var buffer = Data()
        var meta: Meta?
        var expected: Int64?
        var received: Int64 = 0
        var finished = false
        var lastRead: UInt64 = 0
    }
    private func receive(_ connection: NWConnection, url: URL, headers: [String: String], start: Int64, end: Int64?,
                         redirectsLeft: Int, state: StreamState, pace: @escaping (Int64) -> PaceDecision,
                         validate: @escaping (Meta) -> Error?, onMeta: @escaping (Meta) -> Void,
                         onData: @escaping (Data) -> Void, onEnd: @escaping (Error?) -> Void,
                         finish: @escaping (Error?, Bool) -> Void) {
        guard !cancelled, !state.finished else { return }
        let tick = state.lastRead
        queue.asyncAfter(deadline: .now() + 30) { [weak self] in
            guard let self, !self.cancelled, !state.finished, state.lastRead == tick else { return }
            finish(OriginError.timedOut, false)
        }
        connection.receive(minimumIncompleteLength: 1, maximumLength: 256 * 1024) { [weak self] data, _, complete, error in
            guard let self, !self.cancelled, !state.finished else { connection.cancel(); return }
            state.lastRead += 1
            var body = data ?? Data()
            if state.meta == nil {
                state.buffer.append(body)
                guard let headerEnd = state.buffer.range(of: Data([13, 10, 13, 10])) else {
                    if state.buffer.count > 65536 || complete || error != nil { finish(error ?? OriginError.malformedResponse, false) }
                    else { self.receive(connection, url: url, headers: headers, start: start, end: end, redirectsLeft: redirectsLeft,
                                        state: state, pace: pace, validate: validate, onMeta: onMeta, onData: onData, onEnd: onEnd, finish: finish) }
                    return
                }
                guard let meta = Self.parseMeta(Data(state.buffer[..<headerEnd.lowerBound]), url: url) else {
                    finish(OriginError.malformedResponse, false); return
                }
                body = Data(state.buffer[headerEnd.upperBound...]); state.buffer.removeAll()
                if [301, 302, 303, 307, 308].contains(meta.status) {
                    state.finished = true; connection.cancel()
                    guard redirectsLeft > 0, let location = meta.headers["location"],
                          let next = URL(string: location, relativeTo: url)?.absoluteURL else {
                        onEnd(OriginError.tooManyRedirects); return
                    }
                    self.start(url: next, headers: headers, start: start, end: end, redirectsLeft: redirectsLeft - 1,
                               pace: pace, validate: validate, onMeta: onMeta, onData: onData, onEnd: onEnd)
                    return
                }
                guard (200...299).contains(meta.status) else { finish(OriginError.httpStatus(meta.status), false); return }
                if let error = validate(meta) { finish(error, false); return }
                // CDN Range responses must be framed. Do not forward chunk markers
                // or compressed bytes as offsets into the original media file.
                if meta.headers["transfer-encoding"] != nil ||
                    (meta.headers["content-encoding"].map { $0 != "identity" } ?? false) {
                    finish(OriginError.malformedResponse, false); return
                }
                state.meta = meta
                state.expected = meta.headers["content-length"].flatMap(Int64.init)
                onMeta(meta)
            }
            if !body.isEmpty {
                if let expected = state.expected, state.received + Int64(body.count) > expected {
                    finish(OriginError.malformedResponse, false); return
                }
                state.received += Int64(body.count); onData(body)
            }
            if let expected = state.expected, state.received == expected {
                finish(nil, !complete && state.meta?.headers["connection"]?.lowercased() != "close"); return
            }
            if complete || error != nil {
                let failure: Error? = error ?? (state.expected.map { $0 != state.received } == true ? OriginError.incomplete : nil)
                finish(failure, false); return
            }
            let again: () -> Void = { [weak self] in self?.receive(connection, url: url, headers: headers, start: start, end: end,
                redirectsLeft: redirectsLeft, state: state, pace: pace, validate: validate,
                onMeta: onMeta, onData: onData, onEnd: onEnd, finish: finish) }
            switch pace(Int64(body.count)) {
            case .now: again()
            case .after(let seconds): self.queue.asyncAfter(deadline: .now() + seconds) { again() }
            case .suspend: self.resumeHandler = { again() }
            }
        }
    }
    private static func buildRequest(url: URL, headers: [String: String], start: Int64, end: Int64?) -> Data {
        let components = URLComponents(url: url, resolvingAgainstBaseURL: false)
        var path = components?.percentEncodedPath ?? "/"; if path.isEmpty { path = "/" }
        if let query = components?.percentEncodedQuery { path += "?" + query }
        var host = url.host ?? ""; if host.contains(":") && !host.hasPrefix("[") { host = "[\(host)]" }
        if let port = url.port { host += ":\(port)" }
        var lines = ["GET \(path) HTTP/1.1", "Host: \(host)"]
        for (key, value) in headers where !["host", "range", "connection", "accept-encoding"].contains(key.lowercased()) {
            if !key.contains("\r") && !key.contains("\n") && !value.contains("\r") && !value.contains("\n") { lines.append("\(key): \(value)") }
        }
        if !headers.keys.contains(where: { $0.lowercased() == "user-agent" }) { lines.append("User-Agent: StrmAction/1.0") }
        lines += ["Accept-Encoding: identity", "Range: " + (end.map { "bytes=\(start)-\($0 - 1)" } ?? "bytes=\(start)-"),
                  "Connection: keep-alive", "", ""]
        return Data(lines.joined(separator: "\r\n").utf8)
    }
    private static func parseMeta(_ data: Data, url: URL) -> Meta? {
        guard let text = String(data: data, encoding: .isoLatin1) else { return nil }
        let lines = text.components(separatedBy: "\r\n")
        guard let first = lines.first, let status = Int(first.split(separator: " ").dropFirst().first ?? "") else { return nil }
        var headers: [String: String] = [:]
        for line in lines.dropFirst() {
            guard let colon = line.firstIndex(of: ":") else { continue }
            headers[String(line[..<colon]).lowercased()] = line[line.index(after: colon)...].trimmingCharacters(in: .whitespaces)
        }
        let total = headers["content-range"]?.split(separator: "/").last.flatMap { Int64($0) }
            ?? (status == 200 ? headers["content-length"].flatMap(Int64.init) : nil)
        return Meta(status: status, headers: headers, totalLength: total, url: url)
    }
}
