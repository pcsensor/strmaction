package top.strmaction.companion

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

    private val rate = RollingNetworkRate()

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
        rate.add(bytesTransferred.toLong())
    }

    override fun onTransferEnd(
        source: DataSource,
        dataSpec: DataSpec,
        isNetwork: Boolean,
    ) = Unit

    fun sample(): Long = rate.sample()
    fun reset() = rate.reset()

    fun format(bps: Long): String = when {
        bps >= 1024L * 1024L -> String.format(Locale.US, "%.1f MB/s", bps / (1024.0 * 1024.0))
        bps >= 1024L -> String.format(Locale.US, "%.0f KB/s", bps / 1024.0)
        else -> "0 KB/s"
    }
}
