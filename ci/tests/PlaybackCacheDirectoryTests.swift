import Foundation

@main
struct PlaybackCacheDirectoryTests {
    static func main() throws {
        let root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        defer { try? FileManager.default.removeItem(at: root) }
        let source = URL(string: "https://media.invalid/video.mp4")!
        let first = try PlaybackCacheDirectory(sourceURL: source, root: root)
        let second = try PlaybackCacheDirectory(sourceURL: source, root: root)
        precondition(first.url != second.url, "Repeated playback must not share a cache directory")
        let currentFile = second.url.appendingPathComponent("video.bin")
        try Data([1, 2, 3]).write(to: currentFile)
        var cleanups = 0
        first.remove { cleanups += 1 }
        first.remove { cleanups += 1 }
        precondition(cleanups == 1, "Repeated disposal must be idempotent")
        let contents = try Data(contentsOf: currentFile)
        precondition(contents == Data([1, 2, 3]), "Late cleanup removed the new session")
        second.remove()
        let remaining = try FileManager.default.contentsOfDirectory(atPath: root.path)
        precondition(remaining.isEmpty)
        print("PASS: same-source reentry, late cleanup isolation, idempotent disposal")

        let sessions = try (0..<20).map { _ in try PlaybackCacheDirectory(sourceURL: source, root: root) }
        precondition(Set(sessions.map { $0.url }).count == sessions.count)
        for session in sessions.reversed() { session.remove() }
        let finalContents = try FileManager.default.contentsOfDirectory(atPath: root.path)
        precondition(finalContents.isEmpty)
        print("PASS: repeated same-source sessions leave no cache files")
    }
}
