package top.strmaction.companion

import android.content.Context
import android.content.Intent
import android.net.Uri

/**
 * 外部 mpv 兜底（§12.3 / 附录 E.6）。
 *
 * 6 个坑：type=video/any、setPackage、不能加 NEW_TASK、Android 11 queries、
 * 分支包名可配、返回后恢复焦点。
 */
object MpvFallback {
    const val DEFAULT_PACKAGE = "is.xyz.mpv"

    fun buildIntent(info: PlayInfo): Intent = Intent(Intent.ACTION_VIEW).apply {
        setDataAndType(Uri.parse(info.playUrl), "video/any")
        setPackage(info.mpvPackage.ifBlank { DEFAULT_PACKAGE })
        putExtra("title", info.title)
        putExtra("position", info.resumeMs.toInt())
    }

    fun isInstalled(context: Context, packageName: String): Boolean {
        if (packageName.isBlank()) return false
        return runCatching {
            context.packageManager.getPackageInfo(packageName, 0)
            true
        }.getOrDefault(false)
    }
}
