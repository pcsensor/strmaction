package top.strmaction.companion

import android.content.Context

/**
 * 播放缓存配置。
 *
 * 三个概念分开：
 * - 内存缓冲：固定 64MB（小内存设备按堆一半兜底），播放器解码用的抖动缓冲，不可调；
 * - 缓冲大小：实时预拉取窗口（MB），决定「往后提前拉多少」，播放与暂停都生效；
 * - 磁盘缓存上限：落盘数据的容量上限（MB），超出后按 LRU 淘汰，决定「拉过的能留多久」。
 *
 * 预拉取的实际窗口取「缓冲大小」与「磁盘上限」的较小值（落不了盘就白拉）；
 * 两者都为 0 时退化成只有 64MB 内存缓冲。
 */
object PlaybackCache {
    const val PREFS = "player_prefs"

    /** 内存缓冲固定值。 */
    const val MEMORY_BUFFER_MB = 64
    private const val MIN_MEMORY_BUFFER_MB = 16

    /** 服务端 player.cache_limit_mb 的默认值，仅用于解析与展示。 */
    const val DEFAULT_LIMIT_MB = 128
    const val MIN_EFFECTIVE_LIMIT_MB = 16
    const val MAX_LIMIT_MB = 2048

    /** 缓冲大小：实时预拉取窗口（MB），与磁盘容量无关。 */
    const val KEY_BUFFER_MB = "prefetch_mb"
    const val DEFAULT_BUFFER_MB = 512
    const val MIN_BUFFER_MB = 64
    const val MAX_BUFFER_MB = 8192

    /** 磁盘缓存上限（MB），决定落盘数据能留多少。 */
    const val KEY_DISK_MB = "disk_cache_mb"
    const val DEFAULT_DISK_MB = 2048
    const val MIN_DISK_MB = 256
    const val MAX_DISK_MB = 16384

    /** 时间阈值不再参与决定缓冲量，只作为兜底值，避免出现 0 或非法配置。 */
    private const val TIME_HARD_CAP_MS = 6 * 60 * 60 * 1000

    /** 起播 / 重缓冲只需要很少数据。 */
    private const val BUFFER_FOR_PLAYBACK_MS = 2_000
    private const val BUFFER_FOR_PLAYBACK_AFTER_REBUFFER_MS = 3_000

    /** 回看缓存会占用同一份字节预算，关闭后 MB 全部用于前向缓冲。 */
    private const val BACK_BUFFER_MS = 0

    fun normalize(value: Int): Int = when {
        value <= 0 -> 0
        else -> value.coerceIn(MIN_EFFECTIVE_LIMIT_MB, MAX_LIMIT_MB)
    }

    /** 内存缓冲实际值：固定 64MB，堆内存过小时按一半收敛。 */
    fun memoryLimitMb(): Int {
        val heapMb = (Runtime.getRuntime().maxMemory() / (1024L * 1024L)).toInt()
        val heapCap = (heapMb / 2).coerceAtLeast(MIN_MEMORY_BUFFER_MB)
        return MEMORY_BUFFER_MB.coerceAtMost(heapCap)
    }

    fun bytesOf(limitMb: Int): Long = limitMb.toLong() * 1024L * 1024L

    fun targetBufferBytes(): Int =
        bytesOf(memoryLimitMb()).coerceAtMost(Int.MAX_VALUE.toLong()).toInt()

    /** min/max 缓冲时长：同一个兜底值，实际由字节上限决定停在哪里。 */
    fun bufferTimeCapMs(): Int = TIME_HARD_CAP_MS

    fun bufferForPlaybackMs(): Int = BUFFER_FOR_PLAYBACK_MS

    fun bufferForPlaybackAfterRebufferMs(): Int = BUFFER_FOR_PLAYBACK_AFTER_REBUFFER_MS

    /** 回看缓存时长（0 = 关闭，MB 全部用于前向缓冲）。 */
    fun backBufferMs(): Int = BACK_BUFFER_MS

    // ------------------------------------------------------------------
    // 缓冲大小（实时预拉取窗口）
    // ------------------------------------------------------------------

    fun savedBufferLimitMb(context: Context): Int? {
        val prefs = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
        if (!prefs.contains(KEY_BUFFER_MB)) return null
        return normalizeBuffer(prefs.getInt(KEY_BUFFER_MB, DEFAULT_BUFFER_MB))
    }

    fun bufferLimitMb(context: Context): Int =
        savedBufferLimitMb(context) ?: DEFAULT_BUFFER_MB

    /** 0 = 关闭预拉取；其余钳制到 64MB–8GB。 */
    fun normalizeBuffer(value: Int): Int =
        if (value <= 0) 0 else value.coerceIn(MIN_BUFFER_MB, MAX_BUFFER_MB)

    fun parseBuffer(text: String?): Int? {
        val value = text?.trim()?.takeIf { it.isNotEmpty() }?.toIntOrNull() ?: return null
        if (value == 0) return 0
        if (value < MIN_BUFFER_MB || value > MAX_BUFFER_MB) return null
        return value
    }

    fun saveBuffer(context: Context, value: Int) {
        context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
            .edit()
            .putInt(KEY_BUFFER_MB, normalizeBuffer(value))
            .apply()
    }

    fun clearBuffer(context: Context) {
        context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
            .edit()
            .remove(KEY_BUFFER_MB)
            .apply()
    }

    // ------------------------------------------------------------------
    // 磁盘缓存上限
    // ------------------------------------------------------------------

    fun savedDiskLimitMb(context: Context): Int? {
        val prefs = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
        if (!prefs.contains(KEY_DISK_MB)) return null
        return normalizeDisk(prefs.getInt(KEY_DISK_MB, DEFAULT_DISK_MB))
    }

    fun diskLimitMb(context: Context): Int =
        savedDiskLimitMb(context) ?: DEFAULT_DISK_MB

    /** 0 = 关闭磁盘缓存；其余钳制到 256MB–16GB。 */
    fun normalizeDisk(value: Int): Int =
        if (value <= 0) 0 else value.coerceIn(MIN_DISK_MB, MAX_DISK_MB)

    fun parseDisk(text: String?): Int? {
        val value = text?.trim()?.takeIf { it.isNotEmpty() }?.toIntOrNull() ?: return null
        if (value == 0) return 0
        if (value < MIN_DISK_MB || value > MAX_DISK_MB) return null
        return value
    }

    fun saveDisk(context: Context, value: Int) {
        context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
            .edit()
            .putInt(KEY_DISK_MB, normalizeDisk(value))
            .apply()
    }

    fun clearDisk(context: Context) {
        context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
            .edit()
            .remove(KEY_DISK_MB)
            .apply()
    }

    fun diskEnabled(context: Context): Boolean = diskLimitMb(context) > 0

    /**
     * 预取实际能用的窗口：不能超过磁盘上限，否则拉下来立刻被 LRU 淘汰。
     * 磁盘关闭时返回 0（预取也随之关闭）。
     */
    fun prefetchWindowMb(context: Context, activeDiskMb: Int): Int {
        val buffer = bufferLimitMb(context)
        if (buffer <= 0 || activeDiskMb <= 0) return 0
        return buffer.coerceAtMost(activeDiskMb)
    }
}
