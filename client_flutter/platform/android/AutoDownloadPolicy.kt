package top.strmaction.companion

/** Automatic settings; cache budgets remain controlled by the user. */
class AutoDownloadPolicy {
    @Volatile var concurrency = 2
        private set
    @Volatile var segmentBytes = 4L * 1024 * 1024
        private set
    private var healthy = 0
    private var lastRate = 0.0

    @Synchronized fun completed(bytes: Long, elapsedNanos: Long) {
        val seconds = elapsedNanos / 1_000_000_000.0
        if (seconds <= 0) return
        val rate = bytes / seconds
        if (seconds > 15 || (lastRate > 0 && rate < lastRate * 0.5)) failed()
        else if (++healthy >= 2) {
            concurrency = (concurrency + 1).coerceAtMost(4)
            if (rate >= 2 * 1024 * 1024) segmentBytes = 8L * 1024 * 1024
            healthy = 0
        }
        lastRate = rate
    }
    @Synchronized fun failed() {
        concurrency = (concurrency - 1).coerceAtLeast(2)
        segmentBytes = 4L * 1024 * 1024
        healthy = 0
        lastRate = 0.0
    }
}
