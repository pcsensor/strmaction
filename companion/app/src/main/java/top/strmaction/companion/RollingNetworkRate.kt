package top.strmaction.companion

/** Monotonic rolling upstream-byte rate, including quiet time between bursts. */
class RollingNetworkRate(private val clock: () -> Long = { System.nanoTime() / 1_000_000 }) {
    private val samples = java.util.ArrayDeque<Pair<Long, Long>>()
    private var started = clock()
    @Synchronized fun add(bytes: Long) {
        val now = clock()
        if (bytes > 0) {
            if (samples.isNotEmpty() && now - samples.last.first < 100) {
                val last = samples.removeLast(); samples.addLast(Pair(last.first, last.second + bytes))
            } else samples.addLast(Pair(now, bytes))
        }
        trim(now)
    }
    @Synchronized fun sample(): Long {
        val now = clock(); trim(now)
        return (samples.sumOf { it.second } * 1000.0 / (now - started).coerceIn(500, 3000)).toLong()
    }
    @Synchronized fun reset() { samples.clear(); started = clock() }
    private fun trim(now: Long) { while (samples.isNotEmpty() && now - samples.first.first >= 3000) samples.removeFirst() }
}
