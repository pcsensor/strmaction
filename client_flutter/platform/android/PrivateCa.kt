package top.strmaction.companion

import okhttp3.OkHttpClient
import java.io.ByteArrayInputStream
import java.security.KeyStore
import java.security.cert.CertificateException
import java.security.cert.CertificateFactory
import java.security.cert.X509Certificate
import javax.net.ssl.SSLContext
import javax.net.ssl.TrustManagerFactory
import javax.net.ssl.X509TrustManager

/** System roots plus imported private CA roots. Hostname checking stays enabled. */
object PrivateCa {
    var pem: String = ""
    fun configure(builder: OkHttpClient.Builder): OkHttpClient.Builder {
        if (pem.isBlank()) return builder
        val factory = CertificateFactory.getInstance("X.509")
        val certificates = factory.generateCertificates(ByteArrayInputStream(pem.toByteArray()))
        require(certificates.isNotEmpty()) { "没有可用的 CA 证书" }
        val store = KeyStore.getInstance(KeyStore.getDefaultType()).apply { load(null) }
        certificates.forEachIndexed { index, cert ->
            val ca = cert as X509Certificate
            require(ca.basicConstraints >= 0) { "请导入 CA 根证书" }
            ca.checkValidity()
            ca.verify(ca.publicKey)
            store.setCertificateEntry("private-$index", ca)
        }
        fun manager(store: KeyStore?): X509TrustManager = TrustManagerFactory
            .getInstance(TrustManagerFactory.getDefaultAlgorithm()).apply { init(store) }
            .trustManagers.filterIsInstance<X509TrustManager>().first()
        val system = manager(null)
        val custom = manager(store)
        val combined = object : X509TrustManager {
            override fun getAcceptedIssuers() = system.acceptedIssuers + custom.acceptedIssuers
            override fun checkClientTrusted(chain: Array<X509Certificate>, type: String) = system.checkClientTrusted(chain, type)
            override fun checkServerTrusted(chain: Array<X509Certificate>, type: String) {
                try { system.checkServerTrusted(chain, type) }
                catch (_: CertificateException) { custom.checkServerTrusted(chain, type) }
            }
        }
        val context = SSLContext.getInstance("TLS").apply { init(null, arrayOf(combined), null) }
        return builder.sslSocketFactory(context.socketFactory, combined)
    }
}
