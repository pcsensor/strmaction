import Foundation
import Network
import Security

// The transport tests use HTTP loopback. Certificate evaluation below is the
// production implementation; only the app's persisted anchor store/UI log are
// replaced in this standalone harness. App builds compile the real store.
final class TLSTrustStore {
    static let shared = TLSTrustStore()
    func anchorCertificates() -> [SecCertificate] { [] }
}
enum D { static func log(_ tag: String, _ value: String) {} }

func require(_ value: @autoclosure () -> Bool, _ message: String) throws {
    if !value() { throw NSError(domain: "RangeTransportTests", code: 1, userInfo: [NSLocalizedDescriptionKey: message]) }
}

@main struct RangeTransportTests {
    static let headers = ["User-Agent": "pan-fixture", "Referer": "https://pan.example/"]
    static func fetch(_ session: RangeOriginSession, _ queue: DispatchQueue, _ start: Int64, _ end: Int64) async throws -> Data {
        try await withCheckedThrowingContinuation { continuation in
            queue.async {
                var data = Data()
                session.fetch(start: start, end: end, pace: { _ in .now }, onMeta: { _ in },
                    onData: { data.append($0) }, onEnd: { error in
                        if let error { continuation.resume(throwing: error) }
                        else { continuation.resume(returning: data) }
                    })
            }
        }
    }
    static func main() async throws {
        let base = URL(string: ProcessInfo.processInfo.environment["RANGE_FIXTURE_URL"]!)!
        let queue = DispatchQueue(label: "range-tests")
        let session = RangeOriginSession(url: base.appendingPathComponent("entry"), headers: headers, queue: queue)
        let first = try await fetch(session, queue, 0, 4 * 1_048_576)
        try require(first.count == 4 * 1_048_576 && first[99] == 99, "incorrect first segment")
        async let second = fetch(session, queue, 4 * 1_048_576, 8 * 1_048_576)
        async let third = fetch(session, queue, 8 * 1_048_576, 12 * 1_048_576)
        let pair = try await (second, third)
        try require(pair.0.first == UInt8((4 * 1_048_576) % 251), "incorrect parallel offset")
        let before = try JSONSerialization.jsonObject(with: Data(contentsOf: base.appendingPathComponent("stats"))) as! [String: Any]
        try require(before["entries"] as! Int == 1, "repeated AList redirect")
        try require((before["peak"] as! Int) >= 2 && (before["peak"] as! Int) <= 4, "connection limit violated")
        try require((before["ports"] as! Int) <= 3, "bounded responses did not reuse connections")
        _ = try Data(contentsOf: base.appendingPathComponent("expire"))
        async let retryA = fetch(session, queue, 0, 1024)
        async let retryB = fetch(session, queue, 1024, 2048)
        _ = try await (retryA, retryB)
        let after = try JSONSerialization.jsonObject(with: Data(contentsOf: base.appendingPathComponent("stats"))) as! [String: Any]
        try require(after["entries"] as! Int == 2, "refresh was not shared")
        queue.sync { session.stop() }

        let bad = RangeOriginSession(url: base.appendingPathComponent("bad-range"), headers: headers, queue: queue)
        do { _ = try await fetch(bad, queue, 0, 1024); throw NSError(domain: "bad range accepted", code: 1) }
        catch RangeOriginSession.SessionError.rangeMismatch { }
        queue.sync { bad.stop() }
        let stale = RangeOriginSession(url: base.appendingPathComponent("stale"), headers: headers, queue: queue)
        let staleFirst = try await fetch(stale, queue, 0, 1024)
        let staleNext = try await fetch(stale, queue, 1024, 2048)
        try require(staleFirst.count == 1024 && staleNext.first == UInt8(1024 % 251), "stale keep-alive was not retried")
        queue.sync { stale.stop() }
        let plain = RangeOriginSession(url: base.appendingPathComponent("non-range"), headers: headers, queue: queue)
        let plainData = try await fetch(plain, queue, 0, 1024)
        try require(String(data: plainData, encoding: .utf8) == "plain-video", "non-Range fallback failed")
        queue.sync { plain.stop() }

        let recovering = RangeOriginSession(url: base.appendingPathComponent("head-stall"), headers: headers,
            queue: queue, demandStallSeconds: 0.3)
        let recoveryStarted = ProcessInfo.processInfo.systemUptime
        let recovered: Data = try await withCheckedThrowingContinuation { continuation in
            queue.async {
                var data = Data()
                var owner: OriginRequest?
                var metas = 0
                owner = recovering.fetch(start: 0, end: 4 * 1_048_576, demand: false,
                    pace: { _ in .now }, onMeta: { _ in metas += 1 }, onData: { bytes in
                        data.append(bytes)
                        if let owner { recovering.promote(owner) }
                    }, onEnd: { error in
                        owner = nil
                        if let error { continuation.resume(throwing: error) }
                        else if metas != 1 { continuation.resume(throwing: NSError(domain: "duplicate headers", code: 1)) }
                        else { continuation.resume(returning: data) }
                    })
            }
        }
        try require(recovered.count == 4 * 1_048_576 && recovered[65_536] == UInt8(65_536 % 251), "resumed prefix duplicated or lost")
        try require(ProcessInfo.processInfo.systemUptime - recoveryStarted < 3, "promoted slow prefetch was not rescued")
        let recoveryStats = try JSONSerialization.jsonObject(with: Data(contentsOf: base.appendingPathComponent("stats"))) as! [String: Any]
        try require((recoveryStats["head_starts"] as! [Int]) == [0, 65_536], "recovery did not resume at the exact missing byte")
        queue.sync { recovering.stop() }
        let policy = RangeDownloadPolicy()
        for _ in 0..<20 { policy.failed() }
        try require(policy.concurrency == 2, "backoff fell back to a single connection")

        let root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        let store = RangeStore(directory: root, limitBytes: 2 * 1_048_576)
        try store.prepare()
        try require(store.write(Data(repeating: 1, count: 1_048_576), at: 0), "first block write")
        try require(store.write(Data(repeating: 2, count: 1_048_576), at: 1_048_576), "second block write")
        _ = store.read(length: 1, at: 0)
        try require(store.write(Data(repeating: 3, count: 1_048_576), at: 2 * 1_048_576), "LRU write")
        try require(store.read(length: 1, at: 1_048_576) == nil, "LRU did not evict old block")
        try require(store.storedBytes <= 2 * 1_048_576, "disk budget exceeded")
        store.removeFiles(); try? FileManager.default.removeItem(at: root)
        var now: TimeInterval = 0
        let sampler = ThroughputSampler(clock: { now })
        now = 0.5; sampler.add(3 * 1_048_576)
        now = 1; try require(sampler.bytesPerSecond() == 3 * 1_048_576, "burst rate")
        now = 2; try require(sampler.bytesPerSecond() > 0, "burst gap prematurely zero")
        now = 3.5; try require(sampler.bytesPerSecond() == 0, "real stall did not reach zero")

        let cacheStore = RangeStore(directory: root, limitBytes: 8 * 1_048_576); try cacheStore.prepare()
        let cache = try CacheServer(sourceURL: base.appendingPathComponent("entry"), headers: headers, store: cacheStore,
                                    token: "test-token", targetAheadMb: 8, targetAheadSeconds: 10)
        let port = try await cache.start()
        cache.setPacingEnabled(true)
        var request = URLRequest(url: URL(string: "http://127.0.0.1:\(port)/test-token")!)
        request.setValue("bytes=0-999", forHTTPHeaderField: "Range")
        let (localData, response) = try await URLSession.shared.data(for: request)
        try require((response as? HTTPURLResponse)?.statusCode == 206 && localData.count == 1000, "local proxy range framing")
        try require(localData[999] == UInt8(999 % 251), "local proxy data corruption")
        try await Task.sleep(nanoseconds: 500_000_000)
        try require(cacheStore.storedBytes <= 8 * 1_048_576, "proxy prefetch exceeded capacity")
        cache.seek(); cache.stop(); cacheStore.removeFiles(); try? FileManager.default.removeItem(at: root)

        let prefixStore = RangeStore(directory: root, limitBytes: 8 * 1_048_576); try prefixStore.prepare()
        let prefixCache = try CacheServer(sourceURL: base.appendingPathComponent("stream-prefix"), headers: headers,
            store: prefixStore, token: "prefix-token", targetAheadMb: 8, targetAheadSeconds: 10)
        let prefixPort = try await prefixCache.start(); prefixCache.setPacingEnabled(true)
        var prefixRequest = URLRequest(url: URL(string: "http://127.0.0.1:\(prefixPort)/prefix-token")!)
        prefixRequest.setValue("bytes=0-999", forHTTPHeaderField: "Range")
        _ = try await URLSession.shared.data(for: prefixRequest)
        for _ in 0..<100 {
            if prefixStore.cachedEnd(from: 1000) > 1000 { break }
            try await Task.sleep(nanoseconds: 10_000_000)
        }
        try require(prefixStore.cachedEnd(from: 1000) > 1000, "prefetch did not publish its prefix")
        prefixRequest.setValue("bytes=1000-1099", forHTTPHeaderField: "Range"); prefixRequest.timeoutInterval = 1
        let (prefix, _) = try await URLSession.shared.data(for: prefixRequest)
        try require(prefix.count == 100 && prefix[0] == UInt8(1000 % 251), "reader waited for the speculative tail")
        prefixCache.stop(); prefixStore.removeFiles(); try? FileManager.default.removeItem(at: root)
        let slowStore = RangeStore(directory: root, limitBytes: 8 * 1_048_576); try slowStore.prepare()
        let slowCache = try CacheServer(sourceURL: base.appendingPathComponent("slow"), headers: headers,
            store: slowStore, token: "slow-token", targetAheadMb: 8, targetAheadSeconds: 10)
        let slowPort = try await slowCache.start()
        var slowRequest = URLRequest(url: URL(string: "http://127.0.0.1:\(slowPort)/slow-token")!)
        slowRequest.setValue("bytes=0-999", forHTTPHeaderField: "Range"); slowRequest.timeoutInterval = 5
        let pending = Task { try await URLSession.shared.data(for: slowRequest) }
        try await Task.sleep(nanoseconds: 100_000_000)
        let stoppedAt = ProcessInfo.processInfo.systemUptime
        slowCache.stop(); slowStore.removeFiles()
        var cancelled = false
        do { _ = try await pending.value } catch { cancelled = true }
        try require(cancelled && ProcessInfo.processInfo.systemUptime - stoppedAt < 2, "exit left an active local socket")
        try? FileManager.default.removeItem(at: root)
        print("Swift Range transport: URL reuse, shared refresh, pooled connections, parallelism, validation, fallback, LRU, rate and proxy passed")
    }
}
