import Foundation

/// Small disk blocks with LRU eviction. A sparse file cannot reclaim old cached
/// bytes when playback moves on; block files keep actual disk usage bounded.
final class RangeStore {
    static let blockSize: Int64 = 1_048_576
    let capacity: Int64
    private let directory: URL
    private var ranges: [Range<Int64>] = []
    private struct Block { let url: URL; var size: Int64; var touch: UInt64 }
    private var blocks: [Int64: Block] = [:]
    private var sequence: UInt64 = 0
    private var allocated: Int64 = 0
    private var closed = false
    private let lock = NSLock()
    init(directory: URL, limitBytes: Int64) { self.directory = directory; capacity = max(0, limitBytes) }
    func prepare() throws { try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true) }
    func close() { lock.lock(); defer { lock.unlock() }; closed = true }
    func removeFiles() {
        lock.lock(); defer { lock.unlock() }; closed = true
        blocks.values.forEach { try? FileManager.default.removeItem(at: $0.url) }
        blocks.removeAll(); ranges.removeAll(); allocated = 0
    }
    var storedBytes: Int64 { lock.lock(); defer { lock.unlock() }; return allocated }
    func snapshot() -> [Range<Int64>] { lock.lock(); defer { lock.unlock() }; return ranges }
    func contains(start: Int64) -> Bool { cachedEnd(from: start) > start }
    func cachedEnd(from start: Int64) -> Int64 {
        lock.lock(); defer { lock.unlock() }
        return ranges.first(where: { $0.contains(start) })?.upperBound ?? start
    }
    /// Speculation may evict consumed blocks, never unread data ahead of focus.
    func reserve(_ bytes: Int64, before focus: Int64) -> Bool {
        lock.lock(); defer { lock.unlock() }
        while allocated + bytes > capacity {
            guard let key = blocks.filter({ ($0.key + 1) * Self.blockSize <= focus })
                .min(by: { $0.value.touch < $1.value.touch })?.key else { return false }
            evict(key)
        }
        return !closed && bytes <= capacity
    }
    @discardableResult
    func write(_ data: Data, at offset: Int64) -> Bool {
        guard !data.isEmpty, offset >= 0, capacity > 0 else { return false }
        lock.lock(); defer { lock.unlock() }
        guard !closed else { return false }
        var written = 0
        while written < data.count {
            let absolute = offset + Int64(written)
            let key = absolute / Self.blockSize
            let local = absolute % Self.blockSize
            let count = min(data.count - written, Int(Self.blockSize - local))
            let old = blocks[key]
            let size = max(old?.size ?? 0, local + Int64(count))
            let growth = size - (old?.size ?? 0)
            while allocated + growth > capacity {
                guard let victim = blocks.filter({ $0.key != key }).min(by: { $0.value.touch < $1.value.touch })?.key else { return false }
                evict(victim)
            }
            let url = old?.url ?? directory.appendingPathComponent("\(key).block")
            do {
                if old == nil { _ = FileManager.default.createFile(atPath: url.path, contents: nil) }
                let handle = try FileHandle(forUpdating: url)
                defer { try? handle.close() }
                try handle.seek(toOffset: UInt64(local))
                try handle.write(contentsOf: data.subdata(in: written..<(written + count)))
            } catch { return false }
            sequence += 1; blocks[key] = Block(url: url, size: size, touch: sequence)
            allocated += growth
            ranges = merge(ranges, adding: absolute..<(absolute + Int64(count)))
            written += count
        }
        return true
    }
    func read(length: Int, at offset: Int64) -> Data? {
        lock.lock(); defer { lock.unlock() }
        guard !closed, length > 0, offset >= 0 else { return nil }
        var result = Data()
        while result.count < length {
            let absolute = offset + Int64(result.count)
            let key = absolute / Self.blockSize
            let local = absolute % Self.blockSize
            guard var block = blocks[key], ranges.contains(where: { $0.contains(absolute) }) else { return nil }
            let count = min(length - result.count, Int(Self.blockSize - local))
            do {
                let handle = try FileHandle(forReadingFrom: block.url)
                defer { try? handle.close() }
                try handle.seek(toOffset: UInt64(local))
                guard let data = try handle.read(upToCount: count), data.count == count else { return nil }
                result.append(data)
            } catch { return nil }
            sequence += 1; block.touch = sequence; blocks[key] = block
        }
        return result
    }
    private func evict(_ key: Int64) {
        guard let block = blocks.removeValue(forKey: key) else { return }
        try? FileManager.default.removeItem(at: block.url); allocated -= block.size
        let removed = key * Self.blockSize..<(key + 1) * Self.blockSize
        ranges = ranges.flatMap { range -> [Range<Int64>] in
            guard range.overlaps(removed) else { return [range] }
            var result: [Range<Int64>] = []
            if range.lowerBound < removed.lowerBound { result.append(range.lowerBound..<removed.lowerBound) }
            if range.upperBound > removed.upperBound { result.append(removed.upperBound..<range.upperBound) }
            return result
        }
    }
    private func merge(_ existing: [Range<Int64>], adding new: Range<Int64>) -> [Range<Int64>] {
        var lower = new.lowerBound; var upper = new.upperBound
        var result: [Range<Int64>] = []
        for range in existing {
            if range.upperBound < lower || range.lowerBound > upper { result.append(range) }
            else { lower = min(lower, range.lowerBound); upper = max(upper, range.upperBound) }
        }
        result.append(lower..<upper); return result.sorted { $0.lowerBound < $1.lowerBound }
    }
}
