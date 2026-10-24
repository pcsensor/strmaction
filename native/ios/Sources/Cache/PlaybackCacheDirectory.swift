import CryptoKit
import Foundation

/// A playback session owns one directory; late cleanup must never touch its successor.
final class PlaybackCacheDirectory {
    private static let defaultRoot: URL = {
        let root = FileManager.default.urls(for: .cachesDirectory, in: .userDomainMask)[0]
            .appendingPathComponent("strmaction", isDirectory: true)
            .appendingPathComponent("session", isDirectory: true)
        // Remove crash leftovers once per process, before any live session exists.
        try? FileManager.default.removeItem(at: root)
        return root
    }()

    let url: URL
    private let lock = NSLock()
    private var removed = false

    init(sourceURL: URL, root: URL? = nil) throws {
        let digest = SHA256.hash(data: Data(sourceURL.absoluteString.utf8))
        let key = digest.prefix(8).map { String(format: "%02x", $0) }.joined()
        url = (root ?? Self.defaultRoot)
            .appendingPathComponent("\(key)-\(UUID().uuidString)", isDirectory: true)
        try FileManager.default.createDirectory(at: url, withIntermediateDirectories: true)
    }

    func remove(after cleanup: () -> Void = {}) {
        lock.lock()
        guard !removed else { lock.unlock(); return }
        removed = true
        lock.unlock()
        cleanup()
        try? FileManager.default.removeItem(at: url)
    }
}
