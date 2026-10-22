package top.strmaction.companion

import android.util.Log
import android.webkit.JavascriptInterface

/**
 * 网页 ↔ 原生桥（§12.8）。
 *
 * 页面只传 itemId，URL / 请求头 / play_token 全部由原生层向服务端请求，
 * 避免把播放凭证暴露在 JS 层。
 *
 * 注意：`@JavascriptInterface` 方法运行在 JavaBridge 线程，而 WebView 的所有方法
 * （包括读取 `webView.url`）必须在主线程调用。因此这里只做线程切换，
 * 来源校验也在主线程完成——否则会抛 "A WebView method was called on thread
 * 'JavaBridge'"，网页侧表现为「播放失败：Java exception...」。
 */
class JsBridge(
    private val activity: MainActivity,
    private val allowedHost: String,
) {
    @JavascriptInterface
    fun play(itemId: Int) = onUiThread { activity.openPlayer(itemId) }

    @JavascriptInterface
    fun openSettings() = onUiThread { activity.openSetup() }

    @JavascriptInterface
    fun version(): String = BuildConfig.VERSION_NAME

    @JavascriptInterface
    fun isCompanion(): Boolean = true

    @JavascriptInterface
    fun isTV(): Boolean = Device.isTelevision(activity)

    @JavascriptInterface
    fun serverHost(): String = allowedHost

    private fun onUiThread(action: () -> Unit) {
        activity.runOnUiThread {
            try {
                val host = activity.currentWebHost()
                if (host != null && host.equals(allowedHost, ignoreCase = true)) {
                    action()
                } else {
                    Log.w(TAG, "bridge call rejected: origin host=$host")
                }
            } catch (error: Throwable) {
                // 桥接方法绝不能把异常抛回 JS，否则网页侧无法恢复
                Log.w(TAG, "bridge call failed", error)
            }
        }
    }

    private companion object {
        const val TAG = "StrmActionBridge"
    }
}
