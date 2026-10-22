package top.strmaction.companion

import android.os.SystemClock
import androidx.media3.datasource.DataSource
import androidx.media3.datasource.DataSpec
import androidx.media3.datasource.TransferListener
import java.util.Locale

/**
 * 实时网速统计。
 *
 * 挂在 OkHttp 数据源工厂上（缓存层之下），所以统计到的都是真正的网络流量，
 * 命中磁盘缓存不会把网速算高。播放器与预取器共用同一个工厂，因此显示的是
 * 「这条流当前实际吃掉的带宽」。
 */
object NetworkSpeedMeter : TransferListener {

    private val lock = Any()
    private var totalBytes = 0L
    private var lastBytes = 0L
    private var lastSampleAt = 0L
    private var smoothedBps = 0.0

    override fun onTransferInitializing(
        source: DataSource,
        dataSpec: DataSpec,
        isNetwork: Boolean,
    ) = Unit

    override fun onTransferStart(
        source: DataSource,
        dataSpec: DataSpec,
        isNetwork: Boolean,
    ) = Unit

    override fun onBytesTransferred(
        source: DataSource,
        dataSpec: DataSpec,
        isNetwork: Boolean,
        bytesTransferred: Int,
    ) {
        if (!isNetwork || bytesTransferred <= 0) return
        synchronized(lock) { totalBytes += bytesTransferred }
    }

    override fun onTransferEnd(
        source: DataSource,
        dataSpec: DataSpec,
        isNetwork: Boolean,
    ) = Unit

    /** 采样一次，返回平滑后的 B/s；间隔太短时返回上次结果。 */
    fun sample(): Long = synchronized(lock) {
        val now = SystemClock.elapsedRealtime()
        if (lastSampleAt == 0L) {
            lastSampleAt = now
            lastBytes = totalBytes
            return 0L
        }
        val elapsed = now - lastSampleAt
        if (elapsed < 200L) return smoothedBps.toLong()

        val delta = (totalBytes - lastBytes).coerceAtLeast(0L)
        val instant = delta * 1000.0 / elapsed
        // 上升快一点、下降慢一点，避免数字剧烈跳动。
        val weight = if (instant >= smoothedBps) 0.45 else 0.3
        smoothedBps = smoothedBps * (1 - weight) + instant * weight
        if (smoothedBps < 512.0) smoothedBps = 0.0
        lastBytes = totalBytes
        lastSampleAt = now
        smoothedBps.toLong()
    }

    /** 页面离开时清零，避免下次进来从旧速率开始衰减。 */
    fun reset() = synchronized(lock) {
        totalBytes = 0L
        lastBytes = 0L
        lastSampleAt = 0L
        smoothedBps = 0.0
    }

    fun format(bps: Long): String = when {
        bps >= 1024L * 1024L -> String.format(Locale.US, "%.1f MB/s", bps / (1024.0 * 1024.0))
        bps >= 1024L -> String.format(Locale.US, "%.0f KB/s", bps / 1024.0)
        else -> "0 KB/s"
    }
}
