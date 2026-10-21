package top.strmaction.companion

import android.content.Context
import android.os.Handler
import android.os.Looper
import org.json.JSONObject
import java.net.HttpURLConnection
import java.util.ArrayDeque
import java.util.concurrent.Executors

/**
 * 5 秒心跳 + 暂停/退后台补写（§12.7）。
 *
 * - 使用 play_token（Bearer），原生层不碰会话 Cookie；
 * - 失败不阻塞播放：最多缓存 3 条，下次成功时补发最新；
 * - 401 时回调 UI 提示「请重新播放」。
 */
object ProgressReporter {

    data class Report(
        val serverUrl: String,
        val token: String,
        val itemId: Int,
        val positionMs: Long,
        val durationMs: Long?,
        val finished: Boolean,
    )

    private val queue = ArrayDeque<Report>()
    private val lock = Any()
    private val main = Handler(Looper.getMainLooper())
    private val executor = Executors.newSingleThreadExecutor { runnable ->
        Thread(runnable, "strmaction-progress").apply { isDaemon = true }
    }

    fun post(context: Context, report: Report, onTokenExpired: (() -> Unit)? = null) {
        synchronized(lock) {
            queue.addLast(report)
            while (queue.size > 3) queue.removeFirst()
        }
        val appContext = context.applicationContext
        executor.execute { drain(appContext, onTokenExpired) }
    }

    private fun drain(context: Context, onTokenExpired: (() -> Unit)?) {
        while (true) {
            val report = synchronized(lock) { queue.firstOrNull() } ?: return
            val status = try {
                send(context, report)
            } catch (_: Exception) {
                // 网络错误：保留队列，等下一次心跳补发
                return
            }
            synchronized(lock) {
                if (queue.firstOrNull() === report) queue.removeFirst()
            }
            if (status == HttpURLConnection.HTTP_UNAUTHORIZED) {
                main.post { onTokenExpired?.invoke() }
            } else if (status !in 200..299) {
                return
            }
        }
    }

    private fun send(context: Context, report: Report): Int {
        val url = "${report.serverUrl.trimEnd('/')}/api/items/${report.itemId}/progress"
        val position = report.positionMs.coerceAtLeast(0L)
        val body = JSONObject().apply {
            put("position_ms", position)
            put("duration_ms", report.durationMs ?: 0L)
            put("finished", report.finished)
        }.toString()

        val conn = TlsPolicy.openConnection(context, url).apply {
            requestMethod = "POST"
            doOutput = true
            useCaches = false
            connectTimeout = 5_000
            readTimeout = 5_000
            setRequestProperty("Content-Type", "application/json; charset=utf-8")
            setRequestProperty("Authorization", "Bearer ${report.token}")
            setRequestProperty("X-StrmAction-Companion", "1")
        }
        return try {
            conn.outputStream.use { it.write(body.toByteArray(Charsets.UTF_8)) }
            val code = conn.responseCode
            // 读掉响应，避免连接复用异常
            runCatching {
                (if (code in 200..299) conn.inputStream else conn.errorStream)
                    ?.use { it.readBytes() }
            }
            code
        } finally {
            conn.disconnect()
        }
    }
}
