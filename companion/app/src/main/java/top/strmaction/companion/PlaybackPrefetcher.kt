package top.strmaction.companion

import android.net.Uri
import android.util.Log
import androidx.media3.common.C
import androidx.media3.common.util.UnstableApi
import androidx.media3.datasource.DataSource
import androidx.media3.datasource.DataSpec
import androidx.media3.datasource.cache.SimpleCache
import java.util.concurrent.Executors

/**
 * 后台磁盘预取：内存缓冲之外，把后续内容提前读到 [SimpleCache]。
 *
 * - 起点 = 缓存里已连续拉到的末尾（不重复播放器已经读过的字节）；
 * - 终点 = 当前播放位置 + 用户设置的预拉取上限（按 Content-Length / 时长折算字节）；
 * - 播放与暂停都继续预取；播放器正在缓冲时让路，先保证不断流；
 * - 换集 / 退出立即中止，缓存由 [PlaybackDiskCache] 在退出时删除。
 *
 * 只支持能拿到 Content-Length 的片源（渐进式 MP4）；HLS 分段没有整片长度，
 * 自动跳过预取，播放器仍然按内存缓冲正常播放。
 */
@UnstableApi
class PlaybackPrefetcher(
    private val cacheProvider: () -> SimpleCache?,
) {
    private companion object {
        const val TAG = "StrmActionPrefetch"
        const val IDLE_POLL_MS = 400L
        const val ERROR_BACKOFF_MS = 2_000L
        const val MIN_CHUNK_BYTES = 1L * 1024L * 1024L
        const val READ_BUFFER_BYTES = 256 * 1024
    }

    private val executor = Executors.newSingleThreadExecutor { runnable ->
        Thread(runnable, "strmaction-prefetch").apply { isDaemon = true }
    }
    private val buffer = ByteArray(READ_BUFFER_BYTES)

    @Volatile private var factory: DataSource.Factory? = null
    @Volatile private var mediaUri: Uri? = null
    @Volatile private var contentLength: Long = 0L
    @Volatile private var durationMs: Long = 0L
    @Volatile private var windowBytes: Long = 0L
    @Volatile private var positionMs: Long = 0L
    @Volatile private var bufferedMs: Long = 0L
    @Volatile private var playerBuffering = false
    @Volatile private var generation: Long = 0L
    @Volatile private var running = false
    @Volatile private var working = false
    @Volatile private var eofReached = false

    fun start() {
        if (running) return
        running = true
        executor.execute { loop() }
    }

    fun stop() {
        running = false
        generation++
        working = false
        executor.shutdownNow()
    }

    /** 换集 / 换源时调用；uri 变化会中止当前预取并重置进度。 */
    fun setSource(factory: DataSource.Factory?, uri: Uri?) {
        if (this.factory === factory && this.mediaUri == uri) return
        this.factory = factory
        this.mediaUri = uri
        contentLength = 0L
        eofReached = false
        generation++
    }

    fun setContentLength(bytes: Long) {
        if (bytes > 0 && bytes != contentLength) {
            contentLength = bytes
            eofReached = false
        }
    }

    fun setWindowMb(mb: Int) {
        windowBytes = mb.coerceAtLeast(0) * 1024L * 1024L
    }

    fun onTick(positionMs: Long, bufferedMs: Long, durationMs: Long, buffering: Boolean) {
        this.positionMs = positionMs.coerceAtLeast(0L)
        this.bufferedMs = bufferedMs.coerceAtLeast(0L)
        if (durationMs > 0) this.durationMs = durationMs
        playerBuffering = buffering
    }

    fun isWorking(): Boolean = working

    fun enabled(): Boolean =
        windowBytes > 0 && factory != null && mediaUri != null && contentLength > 0 && durationMs > 0

    /** 用户设置的上限折算成时长；码率未知返回 0。 */
    fun windowMs(): Long {
        val ratio = bytesPerMs()
        if (ratio <= 0 || windowBytes <= 0) return 0L
        return (windowBytes / ratio).toLong()
    }

    /** 当前已预取到播放位置之后多少字节（从播放器缓冲末端连续计算，遇空洞即停）。 */
    fun prefetchedAheadBytes(): Long {
        val ratio = bytesPerMs()
        if (ratio <= 0) return 0L
        val cache = cacheProvider() ?: return 0L
        val uri = mediaUri ?: return 0L
        val end = cachedEndBytes(cache, uri.toString(), ratio)
        if (end <= 0) return 0L
        val positionBytes = (positionMs * ratio).toLong()
        return (end - positionBytes).coerceAtLeast(0L)
    }

    /**
     * 磁盘里当前视频已缓存的区间（毫秒），按整片字节/时长等比换算。
     * 拿不到 Content-Length 或时长时返回空列表（调用方只看内存缓冲）。
     */
    fun cachedSpansMs(): List<LongRange> {
        val ratio = bytesPerMs()
        val cache = cacheProvider() ?: return emptyList()
        val uri = mediaUri ?: return emptyList()
        if (ratio <= 0) return emptyList()
        return runCatching {
            cache.getCachedSpans(uri.toString())
                .filter { it.isCached && it.length > 0 }
                .sortedBy { it.position }
                .map { span ->
                    val start = (span.position / ratio).toLong()
                    val end = ((span.position + span.length) / ratio).toLong()
                    start..end
                }
        }.getOrDefault(emptyList())
    }

    /** 播放器已缓冲末端之后，连续缓存的末尾（字节）。 */
    private fun cachedEndBytes(cache: SimpleCache, key: String, ratio: Double): Long {
        val positionBytes = (positionMs * ratio).toLong()
        val bufferedBytes = (bufferedMs * ratio).toLong().coerceAtLeast(positionBytes)
        if (bufferedBytes <= 0) return 0L
        return bufferedBytes + contiguousBytesFrom(cache, key, bufferedBytes)
    }

    /** 从 from 开始连续缓存的字节数；中间有洞就返回洞之前的长度。 */
    private fun contiguousBytesFrom(cache: SimpleCache, key: String, from: Long): Long =
        runCatching {
            var cursor = from
            var total = 0L
            for (span in cache.getCachedSpans(key).sortedBy { it.position }) {
                if (!span.isCached || span.length <= 0) continue
                val end = span.position + span.length
                if (end <= cursor) continue
                if (span.position > cursor) break
                total += end - cursor
                cursor = end
            }
            total
        }.getOrDefault(0L)

    fun prefetchedAheadMs(): Long {
        val ratio = bytesPerMs()
        if (ratio <= 0) return 0L
        return (prefetchedAheadBytes() / ratio).toLong()
    }

    /** 字节 / 毫秒，用于把 MB 与秒互相折算。 */
    private fun bytesPerMs(): Double =
        if (contentLength > 0 && durationMs > 0) {
            contentLength.toDouble() / durationMs
        } else {
            0.0
        }

    private fun loop() {
        while (running) {
            try {
                val cache = cacheProvider()
                val sourceFactory = factory
                val uri = mediaUri
                val ratio = bytesPerMs()
                if (cache == null || sourceFactory == null || uri == null ||
                    ratio <= 0 || windowBytes <= 0 || eofReached
                ) {
                    sleep(IDLE_POLL_MS)
                    continue
                }
                if (playerBuffering) {
                    // 让路给播放器，别和起播/追帧抢带宽。
                    sleep(IDLE_POLL_MS)
                    continue
                }

                val gen = generation
                val start = cachedEndBytes(cache, uri.toString(), ratio)
                val target = minOf(contentLength, (positionMs * ratio).toLong() + windowBytes)
                if (start <= 0 || target - start < MIN_CHUNK_BYTES) {
                    sleep(IDLE_POLL_MS)
                    continue
                }

                working = true
                var position = start
                val dataSource = sourceFactory.createDataSource()
                try {
                    dataSource.open(
                        DataSpec.Builder()
                            .setUri(uri)
                            .setPosition(position)
                            // 一次打开覆盖剩余全部内容，由下面的循环按“窗口”随时停；
                            // 避免每秒重开一个 Range 请求。
                            .setLength((contentLength - start).coerceAtLeast(0L))
                            .build(),
                    )
                    while (running && gen == generation) {
                        if (playerBuffering) break
                        val liveTarget = minOf(
                            contentLength,
                            (positionMs * ratio).toLong() + windowBytes,
                        )
                        if (position >= liveTarget) break
                        val read = dataSource.read(buffer, 0, buffer.size)
                        if (read == C.RESULT_END_OF_INPUT) {
                            eofReached = true
                            break
                        }
                        if (read <= 0) break
                        position += read
                    }
                } catch (error: Exception) {
                    if (gen == generation) {
                        Log.w(TAG, "prefetch failed at $position", error)
                        sleep(ERROR_BACKOFF_MS)
                    }
                } finally {
                    runCatching { dataSource.close() }
                    working = false
                }
                sleep(IDLE_POLL_MS)
            } catch (interrupted: InterruptedException) {
                return
            } catch (error: Exception) {
                Log.w(TAG, "prefetch loop error", error)
                runCatching { sleep(ERROR_BACKOFF_MS) }
            }
        }
    }

    private fun sleep(ms: Long) {
        try {
            Thread.sleep(ms)
        } catch (interrupted: InterruptedException) {
            Thread.currentThread().interrupt()
            throw interrupted
        }
    }
}
