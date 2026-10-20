package top.strmaction.companion

import android.content.Context

/**
 * 播放缓存上限：本机设置优先，未设置时跟随服务端下发的默认值。
 *
 * 0 表示“最小预读”。Media3 无法真正关闭缓冲，因此执行时最低按 16MB 处理；
 * 同时按进程可用堆内存做上限钳制，避免低端电视 OOM。
 */
object PlaybackCache {
    const val PREFS = "player_prefs"
    const val KEY_LIMIT_MB = "cache_limit_mb"
    const val DEFAULT_LIMIT_MB = 128
    const val MIN_EFFECTIVE_LIMIT_MB = 16
    const val MAX_LIMIT_MB = 2048
    /** 时间窗口不随 MB 缩小，否则长剧集的缓冲段只有几个像素。 */
    private const val BUFFER_WINDOW_MS = 60_000
    /** 当前集内回看：保留最近 60 秒已播数据。 */
    private const val BACK_BUFFER_MS = 60_000

    /** 播放器菜单里的快捷档位；0 = 最小预读。 */
    val PRESETS = listOf(0, 64, 128, 256, 512)

    fun savedLimitMb(context: Context): Int? {
        val prefs = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
        if (!prefs.contains(KEY_LIMIT_MB)) return null
        return normalize(prefs.getInt(KEY_LIMIT_MB, DEFAULT_LIMIT_MB))
    }

    fun limitMb(context: Context, serverDefault: Int = DEFAULT_LIMIT_MB): Int =
        savedLimitMb(context) ?: normalize(serverDefault)

    fun normalize(value: Int): Int = when {
        value <= 0 -> 0
        else -> value.coerceIn(MIN_EFFECTIVE_LIMIT_MB, MAX_LIMIT_MB)
    }

    fun parse(text: String?): Int? {
        val value = text?.trim()?.takeIf { it.isNotEmpty() }?.toIntOrNull() ?: return null
        if (value == 0) return 0
        if (value < MIN_EFFECTIVE_LIMIT_MB || value > MAX_LIMIT_MB) return null
        return value
    }

    fun save(context: Context, value: Int) {
        context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
            .edit()
            .putInt(KEY_LIMIT_MB, normalize(value))
            .apply()
    }

    fun clear(context: Context) {
        context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
            .edit()
            .remove(KEY_LIMIT_MB)
            .apply()
    }

    /** 实际执行值：0 映射到 16MB，并限制在当前进程堆内存的 1/4 以内。 */
    fun effectiveLimitMb(context: Context, serverDefault: Int = DEFAULT_LIMIT_MB): Int {
        val requested = limitMb(context, serverDefault)
            .let { if (it <= 0) MIN_EFFECTIVE_LIMIT_MB else it }
        val heapMb = (Runtime.getRuntime().maxMemory() / (1024L * 1024L)).toInt()
        val heapCap = (heapMb / 4).coerceAtLeast(32).coerceAtMost(MAX_LIMIT_MB)
        return requested.coerceIn(MIN_EFFECTIVE_LIMIT_MB, heapCap)
    }

    fun targetBufferBytes(context: Context, serverDefault: Int = DEFAULT_LIMIT_MB): Int {
        val bytes = effectiveLimitMb(context, serverDefault) * 1024L * 1024L
        return bytes.coerceAtMost(Int.MAX_VALUE.toLong()).toInt()
    }

    /** 固定前向缓冲时间窗口；字节上限由 targetBufferBytes 单独控制。 */
    fun maxBufferMs(): Int = BUFFER_WINDOW_MS

    /** 已播放内容的回看缓存时长。 */
    fun backBufferMs(): Int = BACK_BUFFER_MS

    fun label(value: Int): String =
        if (value <= 0) "最小" else "${normalize(value)}MB"
}
