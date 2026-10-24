package top.strmaction.companion

import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import okhttp3.tls.HandshakeCertificates
import okhttp3.tls.HeldCertificate
import org.junit.After
import org.junit.Assert.*
import org.junit.Test
import javax.net.ssl.SSLException

class PrivateCaTest {
    @After fun reset() { PrivateCa.pem = "" }
    private fun fixture(): Pair<HeldCertificate, MockWebServer> {
        val root = HeldCertificate.Builder().commonName("StrmAction Test CA").certificateAuthority(0).build()
        val leaf = HeldCertificate.Builder().commonName("localhost").addSubjectAlternativeName("localhost").signedBy(root).build()
        val server = MockWebServer()
        server.useHttps(HandshakeCertificates.Builder().heldCertificate(leaf, root.certificate).build().sslSocketFactory(), false)
        server.start()
        return Pair(root, server)
    }
    @Test fun privateCaIsRequiredAndHostnameStillChecked() {
        val (root, server) = fixture()
        try {
            server.enqueue(MockResponse().setBody("ok"))
            val request = Request.Builder().url(server.url("/")).build()
            try { OkHttpClient().newCall(request).execute().close(); fail("Untrusted CA accepted") }
            catch (_: SSLException) { }
            PrivateCa.pem = root.certificatePem()
            val trusted = PrivateCa.configure(OkHttpClient.Builder()).build()
            trusted.newCall(request).execute().use { assertEquals("ok", it.body!!.string()) }
            val wrong = request.newBuilder().url(server.url("/").newBuilder().host("127.0.0.1").build()).build()
            try { trusted.newCall(wrong).execute().close(); fail("Wrong hostname accepted") }
            catch (_: SSLException) { }
        } finally { server.shutdown() }
    }
    @Test fun rejectsLeafAsCa() {
        PrivateCa.pem = HeldCertificate.Builder().commonName("leaf").build().certificatePem()
        try { PrivateCa.configure(OkHttpClient.Builder()); fail("Leaf accepted as CA") }
        catch (_: IllegalArgumentException) { }
    }
    @Test fun headersSurviveRedirect() {
        val first = MockWebServer(); val second = MockWebServer()
        first.start(); second.start()
        try {
            first.enqueue(MockResponse().setResponseCode(302).setHeader("Location", second.url("/stream")))
            second.enqueue(MockResponse().setBody("video"))
            val client = PrivateCa.configure(OkHttpClient.Builder()).build()
            client.newCall(Request.Builder().url(first.url("/video")).header("User-Agent", "pan-test").header("Referer", "https://pan.example/").build()).execute().use {
                assertEquals("video", it.body!!.string())
            }
            val redirected = second.takeRequest()
            assertEquals("pan-test", redirected.getHeader("User-Agent"))
            assertEquals("https://pan.example/", redirected.getHeader("Referer"))
        } finally { first.shutdown(); second.shutdown() }
    }
}
