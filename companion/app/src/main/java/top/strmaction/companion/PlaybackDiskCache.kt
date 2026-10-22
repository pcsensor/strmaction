package top.strmaction.companion

import android.content.Context
import android.os.StatFs
import android.util.Log
import androidx.media3.database.StandaloneDatabaseProvider
import androidx.media3.datasource.cache.LeastRecentlyUsedCacheEvictor
import androidx.media3.datasource.cache.SimpleCache
import java.io.File
import java.util.concurrent.Executors

/**
 * 本次播放会话的磁盘缓存。
 *
 * - 进入播放：新建会话目录 `<externalCacheDir>/playback/s-<ts>/`，上限取用户设置；
 * - 播放中：拉取过的字节由 CacheDataSink 落盘，seek 回已拉取区间直接读盘；
 * - 切集：按 Cache key 删掉上一集的数据（只缓存当前视频）；
 * - 退出播放：release 后在后台线程删掉会话目录；
 * - 进程被杀没走到 onDestroy：下次进入时清理残留会话目录。
 *
 * 磁盘上限还会按“可用空间 − 1GB”收敛；收敛后不足 256MB 时直接关闭缓存，
 * 避免把设备存储写满。
 */
object PlaybackDiskCache {
    private const val TAG = "StrmActionCache"
    private const val ROOT_DIR = "playback"
    private const val SESSION_PREFIX = "s-"
    private const val FREE_SPACE_RESERVE_BYTES = 1024L * 1024L * 1024L
    private const val MB = 1024L * 1024L

    private val lock = Any()
    private val io = Executors.newSingleThreadExecutor { runnable ->
        Thread(runnable, "strmaction-cache").apply { isDaemon = true }
    }

    @Volatile
    private var cache: SimpleCache? = null
    private var database: StandaloneDatabaseProvider? = null
    private var sessionDir: File? = null
    @Volatile
    private var activeLimitMb: Int = 0
    private var sessionSeq: Long = 0
    private var appContext: Context? = null

    /** 打开（或复用）本次播放的磁盘缓存；关闭或不可用时返回 null。 */
    fun open(context: Context): SimpleCache? = synchronized(lock) {
        cache?.let { return it }
        appContext = context.applicationContext
        val requestedMb = PlaybackCache.diskLimitMb(context)
        if (requestedMb <= 0) return null

        val root = rootDir(context) ?: return null
        try {
            root.mkdirs()
            val availableMb = (StatFs(root.absolutePath).availableBytes / MB).toInt()
            val usableMb = availableMb - (FREE_SPACE_RESERVE_BYTES / MB).toInt()
            val effectiveMb = requestedMb.coerceAtMost(usableMb)
            if (effectiveMb < PlaybackCache.MIN_DISK_MB) {
                Log.w(TAG, "disk cache disabled: only ${availableMb}MB free")
                return null
            }

            val seq = ++sessionSeq
            val dir = File(root, "$SESSION_PREFIX${System.currentTimeMillis()}-$seq")
            dir.mkdirs()
            val db = StandaloneDatabaseProvider(context.applicationContext)
            val simpleCache = SimpleCache(
                dir,
                LeastRecentlyUsedCacheEvictor(PlaybackCache.bytesOf(effectiveMb)),
                db,
            )
            cache = simpleCache
            database = db
            sessionDir = dir
            activeLimitMb = effectiveMb
            cleanupOtherSessions(root, keep = dir)
            Log.d(TAG, "disk cache opened: ${dir.name} limit=${effectiveMb}MB (requested=${requestedMb}MB)")
            simpleCache
        } catch (error: Exception) {
            Log.w(TAG, "disk cache unavailable, fallback to network", error)
            runCatching { database?.close() }
            database = null
            sessionDir?.deleteRecursively()
            sessionDir = null
            activeLimitMb = 0
            null
        }
    }

    fun usedBytes(): Long = runCatching { cache?.cacheSpace ?: 0L }.getOrDefault(0L)

    fun current(): SimpleCache? = cache

    fun limitMb(): Int = activeLimitMb

    /** 切集时删除上一集的缓存数据（按播放地址作为 Cache key）。 */
    fun removeItem(key: String?) {
        if (key.isNullOrBlank()) return
        io.execute {
            runCatching { cache?.removeResource(key) }
                .onFailure { Log.w(TAG, "remove cached item failed", it) }
        }
    }

    /** 释放并删除本次会话目录；删除放在后台线程，几 GB 也不卡退出。 */
    fun close(clear: Boolean = true) = synchronized(lock) {
        val simpleCache = cache
        val dir = sessionDir
        cache = null
        sessionDir = null
        activeLimitMb = 0
        runCatching { simpleCache?.release() }
        runCatching { database?.close() }
        database = null
        if (dir != null) {
            io.execute {
                if (clear) deleteSession(dir)
            }
        }
    }

    private fun rootDir(context: Context): File? {
        val base = context.getExternalCacheDir() ?: context.cacheDir ?: return null
        return File(base, ROOT_DIR)
    }

    /** 进程被杀留下的旧会话目录：不影响当前会话，后台清掉。 */
    private fun cleanupOtherSessions(root: File, keep: File) {
        val stale = root.listFiles()
            ?.filter { it.isDirectory && it != keep && it.name.startsWith(SESSION_PREFIX) }
            ?.toList()
            .orEmpty()
        if (stale.isEmpty()) return
        io.execute {
            stale.forEach { dir -> deleteSession(dir) }
        }
    }

    /** 删除目录连同 SimpleCache 在 SQLite 里的索引记录，避免元数据越积越多。 */
    private fun deleteSession(dir: File) {
        val context = appContext
        if (context == null) {
            dir.deleteRecursively()
            return
        }
        runCatching {
            val provider = StandaloneDatabaseProvider(context)
            try {
                SimpleCache.delete(dir, provider)
            } finally {
                provider.close()
            }
        }.onFailure {
            Log.w(TAG, "delete disk cache failed, fallback to recursive delete", it)
            dir.deleteRecursively()
        }
    }
}
