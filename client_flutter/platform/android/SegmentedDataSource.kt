package top.strmaction.companion

import android.net.Uri
import androidx.media3.common.C
import androidx.media3.datasource.DataSource
import androidx.media3.datasource.DataSpec
import androidx.media3.datasource.TransferListener
import java.io.EOFException
import java.io.IOException

/** Release CacheDataSource's hole lock every 4–8 MiB so prefetch can fill ahead. */
class SegmentedDataSource(private val factory: DataSource.Factory, private val session: MediaTransferSession,
                          private val onDemand: (Long) -> Unit = {}) : DataSource {
    private var source: DataSource? = null
    private var spec: DataSpec? = null
    private var offset = 0L
    private var remaining = C.LENGTH_UNSET.toLong()
    private var partRemaining = 0L
    private var segmented = false
    private var retries = 0
    private val listeners = mutableListOf<TransferListener>()
    override fun addTransferListener(listener: TransferListener) { listeners.add(listener) }
    override fun getUri(): Uri? = spec?.uri
    override fun getResponseHeaders(): Map<String, List<String>> = source?.responseHeaders ?: emptyMap()
    override fun open(dataSpec: DataSpec): Long {
        spec = dataSpec; offset = 0; retries = 0
        remaining = dataSpec.length
        segmented = session.owns(dataSpec.uri.toString()) && dataSpec.uri.scheme in listOf("http", "https") &&
            !Regex("\\.(m3u8|mpd)$", RegexOption.IGNORE_CASE).containsMatchIn(dataSpec.uri.path ?: "")
        openWithRetry()
        if (segmented && !session.supportsRanges) {
            source?.close(); source = null
            segmented = false
            openPart()
        }
        if (session.owns(dataSpec.uri.toString()) && remaining == C.LENGTH_UNSET.toLong() && session.contentLength > 0) {
            remaining = (session.contentLength - dataSpec.position).coerceAtLeast(0)
        }
        return remaining
    }
    private fun openPart() {
        val original = spec ?: return
        onDemand(original.position + offset)
        val length = if (segmented) minOf(session.policy.segmentBytes,
            if (remaining < 0) Long.MAX_VALUE else remaining) else remaining
        val next = original.subrange(offset, length).buildUpon()
            .setFlags(original.flags or DataSpec.FLAG_ALLOW_CACHE_FRAGMENTATION).build()
        val dataSource = factory.createDataSource()
        source = dataSource
        listeners.forEach { dataSource.addTransferListener(it) }
        val opened = dataSource.open(next)
        partRemaining = if (length >= 0) length else opened
        if (session.owns(original.uri.toString()) && session.contentLength > 0) partRemaining = minOf(partRemaining,
            session.contentLength - original.position - offset)
    }
    private fun openWithRetry() {
        while (true) {
            try { openPart(); return }
            catch (error: IOException) {
                runCatching { source?.close() }; source = null
                if (!segmented || retries++ >= 2) throw error
            }
        }
    }
    override fun read(buffer: ByteArray, offset: Int, length: Int): Int {
        if (length == 0) return 0
        if (remaining == 0L) return C.RESULT_END_OF_INPUT
        if (partRemaining == 0L && !segmented) return C.RESULT_END_OF_INPUT
        if (partRemaining == 0L && segmented) {
            source?.close(); source = null; openWithRetry()
        }
        val read = try {
            source?.read(buffer, offset, if (partRemaining >= 0) minOf(length.toLong(), partRemaining).toInt() else length)
                ?: return C.RESULT_END_OF_INPUT
        } catch (error: IOException) {
            if (!segmented || retries++ >= 2) throw error
            runCatching { source?.close() }; source = null
            openWithRetry()
            return read(buffer, offset, length)
        }
        if (read == C.RESULT_END_OF_INPUT) {
            if (partRemaining > 0 && session.supportsRanges) throw EOFException("片源范围读取不完整")
            if (!segmented || !session.supportsRanges) return C.RESULT_END_OF_INPUT
            source?.close(); source = null; openWithRetry()
            return read(buffer, offset, length)
        }
        this.offset += read
        retries = 0
        if (remaining >= 0) remaining -= read
        if (partRemaining >= 0) partRemaining -= read
        return read
    }
    override fun close() { source?.close(); source = null; spec = null }
}
