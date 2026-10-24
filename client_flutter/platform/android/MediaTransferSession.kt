package top.strmaction.companion

import okhttp3.HttpUrl
import okhttp3.Interceptor
import okhttp3.Request
import okhttp3.Response
import okhttp3.ResponseBody
import okio.Buffer
import okio.ForwardingSource
import okio.buffer
import java.io.IOException
import java.util.concurrent.Semaphore
import java.util.concurrent.atomic.AtomicBoolean

/** Per-playback signed URL lease, shared by the decoder and prefetch workers. */
class MediaTransferSession(private val origin: HttpUrl) : Interceptor {
    val policy = AutoDownloadPolicy()
    @Volatile var contentLength = 0L
        private set
    @Volatile var supportsRanges = false
        private set
    private val lock = Any()
    private val slots = Semaphore(4, true)
    private var resolved: HttpUrl? = null
    private var version = 0
    private val knownUrls = mutableSetOf(origin)
    fun owns(url: String): Boolean = synchronized(lock) { knownUrls.any { it.toString() == url } }
    private var validator: String? = null

    override fun intercept(chain: Interceptor.Chain): Response {
        val original = chain.request()
        // Manifests, subtitles and adaptive-stream segments have separate URLs.
        if (!owns(original.url.toString())) return chain.proceed(original)
        try { slots.acquire() } catch (error: InterruptedException) {
            Thread.currentThread().interrupt(); throw IOException("播放请求已取消", error)
        }
        val released = AtomicBoolean(false)
        fun release() { if (released.compareAndSet(false, true)) slots.release() }
        try {
            val lease: Pair<HttpUrl, Int>
            var first: Response? = null
            synchronized(lock) {
                if (resolved == null) {
                    first = chain.proceed(original)
                    try { remember(first!!, original) } catch (error: Exception) { first!!.close(); throw error }
                }
                lease = Pair(resolved ?: origin, version)
            }
            var response = first ?: chain.proceed(request(original, lease.first))
            if (response.code in listOf(401, 403, 410) && (lease.first != origin || response.request.url != origin)) {
                response.close()
                synchronized(lock) {
                    if (version == lease.second) {
                        chain.proceed(original.newBuilder().url(origin).header("Range", "bytes=0-0")
                            .removeHeader("If-Range").build()).use { probe ->
                            if (probe.code != 206) throw IOException("直链已失效，重新取链失败：HTTP ${probe.code}")
                            remember(probe, probe.request, refresh = true)
                            if (probe.body?.bytes()?.size != 1) throw IOException("直链探测范围不完整")
                        }
                    }
                }
                response = chain.proceed(request(original, synchronized(lock) { resolved ?: origin }))
            }
            validate(response, original)
            val body = response.body
            if (body == null) { release(); return response }
            val started = System.nanoTime()
            val measured = AtomicBoolean(false)
            fun measure(bytes: Long) {
                if (measured.compareAndSet(false, true)) policy.completed(bytes, System.nanoTime() - started)
            }
            return response.newBuilder().body(object : ResponseBody() {
                private var received = 0L
                private val stream = object : ForwardingSource(body.source()) {
                    override fun read(sink: Buffer, byteCount: Long): Long {
                        try {
                            val count = super.read(sink, byteCount)
                            if (count > 0) {
                                received += count
                                if (body.contentLength() >= 0 && received == body.contentLength()) { measure(received); release() }
                            }
                            if (count == -1L) {
                                val expected = body.contentLength()
                                if (expected >= 0 && received != expected) throw IOException("片源范围读取不完整")
                                measure(received)
                                release()
                            }
                            return count
                        } catch (error: IOException) { policy.failed(); release(); throw error }
                    }
                    override fun close() { try { super.close() } finally { release() } }
                }.buffer()
                override fun contentType() = body.contentType()
                override fun contentLength() = body.contentLength()
                override fun source() = stream
            }).build()
        } catch (error: Exception) { release(); throw error }
    }

    private fun request(original: Request, url: HttpUrl): Request {
        val builder = original.newBuilder().url(url).header("Accept-Encoding", "identity")
        synchronized(lock) { validator?.let { builder.header("If-Range", it) } }
        return builder.build()
    }

    private fun remember(response: Response, request: Request, refresh: Boolean = false) {
        if (!response.isSuccessful) return
        if (response.code == 206) {
            val range = parseRange(response) ?: throw IOException("片源范围响应无效")
            val nextValidator = response.header("ETag")?.takeUnless { it.startsWith("W/") }
                ?: response.header("Last-Modified")
            if (contentLength > 0 && (refresh || supportsRanges) && (range.third != contentLength ||
                    (validator != null && validator != nextValidator))) throw IOException("片源文件已变化，请重新播放")
            contentLength = range.third
            validator = nextValidator
            val mime = response.header("Content-Type") ?: ""
            supportsRanges = !origin.encodedPath.endsWith(".m3u8", true) && !origin.encodedPath.endsWith(".mpd", true) &&
                !mime.contains("mpegurl", true) && !mime.contains("dash", true) && !mime.startsWith("text/") && !mime.contains("xml", true)
        } else if (response.code == 200 && request.header("Range") != null && !supportsRanges) {
            // Keep Media3's normal non-Range transport; never prefetch it.
            contentLength = response.body?.contentLength()?.coerceAtLeast(0) ?: 0
        }
        resolved = response.request.url
        knownUrls.add(response.request.url)
        version++
    }

    private fun parseRange(response: Response): Triple<Long, Long, Long>? {
        val match = Regex("bytes (\\d+)-(\\d+)/(\\d+)").matchEntire(response.header("Content-Range") ?: "") ?: return null
        val (start, end, total) = match.destructured
        return Triple(start.toLong(), end.toLong(), total.toLong())
    }

    private fun validate(response: Response, original: Request) {
        if (!response.isSuccessful) return // Media3 reports the actual HTTP status.
        val requested = Regex("bytes=(\\d+)-(\\d*)").matchEntire(original.header("Range") ?: "") ?: return
        val start = requested.groupValues[1].toLong()
        if (response.code == 200 && supportsRanges) { response.close(); throw IOException("片源已不再支持范围读取") }
        if (response.code != 206) return
        val range = parseRange(response)
        val end = requested.groupValues[2].toLongOrNull()
        val expected = if (range != null) minOf(end ?: (range.third - 1), range.third - 1) else -1
        val nextValidator = response.header("ETag")?.takeUnless { it.startsWith("W/") } ?: response.header("Last-Modified")
        if (range == null || range.first != start || range.second != expected || range.third != contentLength ||
            (validator != null && nextValidator != validator) ||
            (response.body?.contentLength()?.let { it >= 0 && it != range.second - start + 1 } == true)) {
            response.close(); throw IOException("片源范围或文件身份不一致")
        }
    }
}
