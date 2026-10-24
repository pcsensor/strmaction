import Foundation

/// Upstream bytes in a monotonic rolling window. Disk/loopback reads do not
/// contribute, and expired samples are removed so a stall becomes exactly zero.
final class ThroughputSampler {
    private let lock = NSLock()
    private var samples: [(TimeInterval, Int64)] = []
    private let window: TimeInterval
    private let minimumElapsed: TimeInterval
    private let clock: () -> TimeInterval
    private var started: TimeInterval
    init(window: TimeInterval = 3, minimumElapsed: TimeInterval = 0.5,
         clock: @escaping () -> TimeInterval = { ProcessInfo.processInfo.systemUptime }) {
        self.window = window; self.minimumElapsed = minimumElapsed; self.clock = clock; started = clock()
    }
    func add(_ bytes: Int64) {
        guard bytes > 0 else { return }
        lock.lock(); defer { lock.unlock() }
        let now = clock()
        if let last = samples.last, now - last.0 < 0.1 { samples[samples.count - 1].1 += bytes }
        else { samples.append((now, bytes)) }
        trim(now)
    }
    func bytesPerSecond() -> Double {
        lock.lock(); defer { lock.unlock() }
        let now = clock(); trim(now)
        return Double(samples.reduce(Int64(0)) { $0 + $1.1 }) / max(minimumElapsed, min(window, now - started))
    }
    func reset() { lock.lock(); defer { lock.unlock() }; samples.removeAll(); started = clock() }
    private func trim(_ now: TimeInterval) { samples.removeAll { now - $0.0 >= window } }
}
