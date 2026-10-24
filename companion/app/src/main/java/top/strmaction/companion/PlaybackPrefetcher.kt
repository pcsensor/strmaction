package top.strmaction.companion

import android.net.Uri
import android.util.Log
import androidx.media3.common.C
import androidx.media3.common.util.UnstableApi
import androidx.media3.datasource.DataSource
import androidx.media3.datasource.DataSpec
import androidx.media3.datasource.cache.SimpleCache
import java.util.concurrent.Executors
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.atomic.AtomicLong

/** Carries cancellation across CacheDataSource.open() into the HTTP factory. */
internal object PrefetchCancellation { val current = ThreadLocal<() -> Boolean>() }

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
    private val policy: AutoDownloadPolicy = AutoDownloadPolicy(),
    private val cancelRequest: ((Long, Long) -> Unit)? = null,
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
    private val workers = Executors.newFixedThreadPool(3) { runnable ->
        Thread(runnable, "strmaction-range").apply { isDaemon = true }
    }
    private data class Work(val start: Long, val end: Long, val source: DataSource, val generation: Long,
                            @Volatile var cancelled: Boolean = false)
    private val jobs = ConcurrentHashMap<Long, Work>()
    private val sequence = AtomicLong()

    @Volatile private var factory: DataSource.Factory? = null
    @Volatile private var mediaUri: Uri? = null
    @Volatile private var contentLength: Long = 0L
    @Volatile private var durationMs: Long = 0L
    @Volatile private var windowBytes: Long = 0L
    @Volatile private var positionMs: Long = 0L
    @Volatile private var bufferedMs: Long = 0L
    @Volatile private var playbackUrgent = false
    @Volatile private var demandOffset: Long? = null
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
        cancelDownloads()
        workers.shutdownNow()
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
        val next = mb.coerceAtLeast(0) * 1024L * 1024L
        if (next < windowBytes) onSeek()
        windowBytes = next
    }

    fun onTick(positionMs: Long, bufferedMs: Long, durationMs: Long, buffering: Boolean) {
        this.positionMs = positionMs.coerceAtLeast(0L)
        this.bufferedMs = bufferedMs.coerceAtLeast(0L)
        if (durationMs > 0) this.durationMs = durationMs
        playbackUrgent = buffering || this.bufferedMs - this.positionMs < 10_000
    }

    fun isWorking(): Boolean = jobs.isNotEmpty()

    fun onSeek() { generation++; demandOffset = null; cancelDownloads() }

    fun onDemand(offset: Long) { demandOffset = offset.coerceAtLeast(0) }

    private fun cancel(work: Work) {
        work.cancelled = true
        // OkHttp cancellation interrupts the owning worker. CacheDataSource
        // must close on that worker, never concurrently with its read().
        if (cancelRequest != null) cancelRequest.invoke(work.start, work.end)
        else runCatching { work.source.close() }
    }

    private fun cancelDownloads() {
        jobs.values.toList().forEach { cancel(it) }
        jobs.clear()
    }

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
                if (cache != null && sourceFactory != null && uri != null && ratio > 0 && windowBytes > 0) {
                    val key = uri.toString()
                    val target = minOf(contentLength, (positionMs * ratio).toLong() + windowBytes)
                    var cursor = cachedEndBytes(cache, key, ratio)
                    demandOffset?.takeIf { it < target }?.let {
                        cursor = it + contiguousBytesFrom(cache, key, it)
                    }
                    // Reserve one transport slot for the decoder; total is at most four.
                    val limit = (if (playbackUrgent) 1 else policy.concurrency - 1).coerceIn(1, 3)
                    val pending = jobs.entries.filter { !it.value.cancelled }
                        .sortedBy { kotlin.math.abs(it.value.start - (demandOffset ?: cursor)) }
                    for (entry in pending.drop(limit)) { cancel(entry.value) }
                    while (running && cursor < target && jobs.size < limit) {
                        val covering = jobs.values.firstOrNull { cursor >= it.start && cursor < it.end }
                        if (covering != null) { cursor = covering.end; continue }
                        val cached = cache.getCachedLength(key, cursor, target - cursor)
                        if (cached > 0) { cursor += cached; continue }
                        val end = minOf(target, cursor + policy.segmentBytes, cursor - cached)
                        if (end <= cursor) break
                        // Do not queue behind the decoder's active cache-hole lock.
                        val span = cache.startReadWriteNonBlocking(key, cursor, end - cursor)
                        if (span == null) { cursor = end; continue }
                        if (span.isHoleSpan) cache.releaseHoleSpan(span)
                        else { cursor = end; continue }
                        val id = sequence.incrementAndGet()
                        val work = Work(cursor, end, sourceFactory.createDataSource(), generation)
                        jobs[id] = work
                        workers.execute { download(id, work, uri) }
                        cursor = end
                    }
                }
                sleep(100)
            } catch (interrupted: InterruptedException) { return }
            catch (error: Exception) {
                Log.w(TAG, "prefetch scheduler failed", error)
                runCatching { sleep(ERROR_BACKOFF_MS) }
            }
        }
    }

    private fun download(id: Long, work: Work, uri: Uri) {
        val buffer = ByteArray(READ_BUFFER_BYTES)
        PrefetchCancellation.current.set { !running || work.cancelled || work.generation != generation }
        try {
            if (!running || work.cancelled || work.generation != generation) return
            work.source.open(DataSpec.Builder().setUri(uri).setPosition(work.start)
                .setLength(work.end - work.start).setFlags(DataSpec.FLAG_ALLOW_CACHE_FRAGMENTATION).build())
            var position = work.start
            while (running && !work.cancelled && work.generation == generation && position < work.end) {
                val read = work.source.read(buffer, 0, minOf(buffer.size.toLong(), work.end - position).toInt())
                if (read == C.RESULT_END_OF_INPUT) break
                if (read <= 0) break
                position += read
            }
        } catch (error: Exception) {
            if (running && !work.cancelled && work.generation == generation) {
                policy.failed()
                Log.w(TAG, "range prefetch failed", error)
                runCatching { sleep(ERROR_BACKOFF_MS) }
            }
        } finally {
            runCatching { work.source.close() }
            jobs.remove(id)
            PrefetchCancellation.current.remove()
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
