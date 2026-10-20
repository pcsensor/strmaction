package top.strmaction.companion

import android.content.Context
import android.graphics.Color
import android.net.Uri
import android.os.Build
import android.util.DisplayMetrics
import android.view.WindowManager

/** 一次播放所需的全部参数（来自 POST /api/play/{id}）。 */
data class PlayInfo(
    val serverUrl: String,
    val itemId: Int,
    val title: String,
    val playUrl: String,
    val resumeMs: Long,
    val durationMs: Long?,
    val headers: Map<String, String>,
    val playToken: String,
    val nextItemId: Int?,
    val nextTitle: String?,
    val progressIntervalMs: Long,
    val cacheLimitMb: Int,
    val fallbackOnError: Boolean,
    val mpvPackage: String,
    val subtitles: List<SubtitleInfo>,
    val mode: String,
    val seriesTitle: String?,
    val playlist: List<PlayEntry>,
    val currentIndex: Int,
)

/** 播放器「选集」里的一集。 */
data class PlayEntry(
    val id: Int,
    val title: String,
    val seasonNo: Int?,
    val episodeNo: Int?,
    val code: String?,
    val watched: Boolean,
    val current: Boolean,
) {
    fun displayLabel(): String {
        val prefix = code ?: episodeNo?.let { "第 ${it} 集" } ?: ""
        val name = title.takeIf { it.isNotBlank() && it != prefix }
        return listOf(prefix, name).filter { !it.isNullOrBlank() }.joinToString("  ")
            .ifBlank { "第 ${episodeNo ?: id} 集" }
    }
}

data class SubtitleInfo(
    val label: String,
    val lang: String,
    val mime: String,
    val url: String,
)

class PlayApiException(val statusCode: Int, message: String) : Exception(message)

object Device {
    /** 电视 / 盒子：决定是否启用 ?tv=1 与横屏。触摸设备永远按手机处理（手机优先）。 */
    fun isTelevision(context: Context): Boolean {
        val uiMode = context.resources.configuration.uiMode and
            android.content.res.Configuration.UI_MODE_TYPE_MASK
        if (uiMode == android.content.res.Configuration.UI_MODE_TYPE_TELEVISION) return true
        val leanback = context.packageManager.hasSystemFeature("android.software.leanback")
        if (!leanback) return false
        return !isTouchDevice(context)
    }

    fun isTouchDevice(context: Context): Boolean =
        context.packageManager.hasSystemFeature("android.hardware.touchscreen")

    @Suppress("DEPRECATION")
    fun screenWidthDp(context: Context): Int {
        val wm = context.getSystemService(Context.WINDOW_SERVICE) as WindowManager
        val metrics = DisplayMetrics()
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
            val bounds = wm.currentWindowMetrics.bounds
            val density = context.resources.displayMetrics.density
            return (bounds.width() / density).toInt()
        }
        wm.defaultDisplay.getRealMetrics(metrics)
        return (metrics.widthPixels / metrics.density).toInt()
    }
}

/** 把服务器返回的相对字幕地址补成绝对地址。 */
fun absoluteUrl(base: String, path: String): String =
    if (path.startsWith("http://", true) || path.startsWith("https://", true)) {
        path
    } else {
        base.trimEnd('/') + "/" + path.trimStart('/')
    }

fun subtitleMime(format: String, raw: String = ""): String = when {
    raw.startsWith("text/") || raw.contains("subrip") -> raw
    format.equals("ass", true) || format.equals("ssa", true) -> "text/x-ssa"
    format.equals("vtt", true) -> "text/vtt"
    else -> "application/x-subrip"
}

fun statusBarColor(): Int = Color.parseColor("#07080A")

fun parsedHost(url: String): String? = runCatching { Uri.parse(url).host }.getOrNull()
