package top.strmaction.companion

import android.content.Context
import android.net.Uri
import java.net.HttpURLConnection
import java.net.URL
import java.security.SecureRandom
import java.security.cert.X509Certificate
import javax.net.ssl.HostnameVerifier
import javax.net.ssl.HttpsURLConnection
import javax.net.ssl.SSLContext
import javax.net.ssl.SSLSocketFactory
import javax.net.ssl.TrustManager
import javax.net.ssl.X509TrustManager

/**
 * 自签名 HTTPS 的全局逃生口。
 *
 * 一旦用户在设置页明确开启，所有 HTTPS 连接（StrmAction、Alist、片源 CDN）
 * 都会跳过证书链和 hostname 校验。默认关闭；这是有中间人风险的显式选择。
 */
object TlsPolicy {
    const val KEY_ALLOW_SELF_SIGNED = "allow_self_signed"

    data class ClientTls(
        val socketFactory: SSLSocketFactory,
        val trustManager: X509TrustManager,
        val hostnameVerifier: HostnameVerifier,
    )

    /** 只有 HTTPS 地址才需要 TLS 策略。 */
    fun isHttps(url: String): Boolean {
        val uri = runCatching { Uri.parse(url) }.getOrNull() ?: return false
        return uri.scheme?.equals("https", ignoreCase = true) == true && uri.host != null
    }

    fun isEnabled(context: Context): Boolean =
        prefs(context).getBoolean(KEY_ALLOW_SELF_SIGNED, false)

    fun setEnabled(context: Context, enabled: Boolean) {
        prefs(context).edit()
            .putBoolean(KEY_ALLOW_SELF_SIGNED, enabled)
            .remove("self_signed_authority")
            .apply()
    }

    /** 开关打开后对所有 HTTPS 地址放行。 */
    fun isAllowed(context: Context, url: String): Boolean =
        isEnabled(context) && isHttps(url)

    /**
     * 打开连接；默认按全局开关决定是否放行自签名证书。
     * Setup 测试时会显式传入复选框状态，避免必须先把开关写盘。
     */
    fun openConnection(
        context: Context,
        url: String,
        allowSelfSigned: Boolean = isAllowed(context, url),
    ): HttpURLConnection {
        val connection = URL(url).openConnection() as HttpURLConnection
        if (connection is HttpsURLConnection && allowSelfSigned) {
            clientTls(url)?.let { tls ->
                connection.sslSocketFactory = tls.socketFactory
                connection.hostnameVerifier = tls.hostnameVerifier
            }
        }
        return connection
    }

    /** 给 OkHttp 使用的 TLS 配置；调用方需先确认开关已开启。 */
    fun clientTls(url: String): ClientTls? {
        if (!isHttps(url)) return null
        val trustManager = object : X509TrustManager {
            override fun checkClientTrusted(chain: Array<out X509Certificate>?, authType: String?) = Unit
            override fun checkServerTrusted(chain: Array<out X509Certificate>?, authType: String?) = Unit
            override fun getAcceptedIssuers(): Array<X509Certificate> = emptyArray()
        }
        val sslContext = SSLContext.getInstance("TLS")
        sslContext.init(null, arrayOf<TrustManager>(trustManager), SecureRandom())
        return ClientTls(
            socketFactory = sslContext.socketFactory,
            trustManager = trustManager,
            hostnameVerifier = HostnameVerifier { _, _ -> true },
        )
    }

    private fun prefs(context: Context) =
        context.getSharedPreferences(MainActivity.PREFS, Context.MODE_PRIVATE)
}
