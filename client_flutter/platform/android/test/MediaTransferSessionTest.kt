package top.strmaction.companion

import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.mockwebserver.Dispatcher
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import okhttp3.mockwebserver.RecordedRequest
import org.junit.Assert.*
import org.junit.Test
import okio.Buffer
import java.io.IOException
import java.util.concurrent.CountDownLatch
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicInteger

class MediaTransferSessionTest {
    private class Fixture : AutoCloseable {
        val entry = MockWebServer()
        val cdn = MockWebServer()
        val entries = AtomicInteger()
        val ticket = AtomicInteger()
        @Volatile var expired = false
        @Volatile var badRange = false
        @Volatile var changed = false
        init {
            cdn.start(); entry.start()
            entry.dispatcher = object : Dispatcher() {
                override fun dispatch(request: RecordedRequest): MockResponse {
                    entries.incrementAndGet(); val next = ticket.incrementAndGet(); expired = false
                    return MockResponse().setResponseCode(302).setHeader("Location", cdn.url("/file?ticket=$next"))
                }
            }
            cdn.dispatcher = object : Dispatcher() {
                override fun dispatch(request: RecordedRequest): MockResponse {
                    if (request.getHeader("User-Agent") != "pan-fixture" || request.getHeader("Referer") != "https://pan.example/") return MockResponse().setResponseCode(400)
                    if (expired || request.requestUrl!!.queryParameter("ticket") != ticket.get().toString()) return MockResponse().setResponseCode(403)
                    val match = Regex("bytes=(\\d+)-(\\d+)").matchEntire(request.getHeader("Range")!!)!!
                    val start = match.groupValues[1].toInt(); val end = match.groupValues[2].toInt()
                    return MockResponse().setResponseCode(206).setBody("abcdefghijklmnop".substring(start, end + 1))
                        .setHeader("Content-Type", "video/mp4").setHeader("ETag", if (changed) "\"changed\"" else "\"original\"")
                        .setHeader("Content-Range", "bytes ${if (badRange && end > 0) start + 1 else start}-$end/16")
                }
            }
        }
        override fun close() { entry.shutdown(); cdn.shutdown() }
        fun request(start: Int = 0, end: Int = 3) = Request.Builder().url(entry.url("/entry"))
            .header("User-Agent", "pan-fixture").header("Referer", "https://pan.example/")
            .header("Range", "bytes=$start-$end").build()
        fun client(session: MediaTransferSession) = OkHttpClient.Builder().addInterceptor(session).readTimeout(5, TimeUnit.SECONDS).build()
    }
    @Test fun reusesResolvedUrlAndRequiredHeaders() {
        Fixture().use { fixture ->
            val session = MediaTransferSession(fixture.entry.url("/entry")); val client = fixture.client(session)
            client.newCall(fixture.request()).execute().use { assertEquals("abcd", it.body!!.string()) }
            client.newCall(fixture.request(4, 7)).execute().use { assertEquals("efgh", it.body!!.string()) }
            assertEquals(1, fixture.entries.get()); assertTrue(session.supportsRanges); assertEquals(16L, session.contentLength)
        }
    }
    @Test fun expiredReadersShareOneRefresh() {
        Fixture().use { fixture ->
            val session = MediaTransferSession(fixture.entry.url("/entry")); val client = fixture.client(session)
            client.newCall(fixture.request()).execute().use { it.body!!.bytes() }
            fixture.expired = true
            val pool = Executors.newFixedThreadPool(4)
            try {
                val jobs = (0..3).map { pool.submit<String> { client.newCall(fixture.request(4, 7)).execute().use { it.body!!.string() } } }
                jobs.forEach { assertEquals("efgh", it.get(10, TimeUnit.SECONDS)) }
                assertEquals(2, fixture.entries.get())
            } finally { pool.shutdownNow() }
        }
    }
    @Test fun holdsAtMostFourResponseBodies() {
        Fixture().use { fixture ->
            val session = MediaTransferSession(fixture.entry.url("/entry")); val client = fixture.client(session)
            val ready = AtomicInteger(); val four = CountDownLatch(4); val release = CountDownLatch(1)
            val pool = Executors.newFixedThreadPool(6)
            try {
                val jobs = (0..5).map { pool.submit {
                    client.newCall(fixture.request()).execute().use { response ->
                        ready.incrementAndGet(); four.countDown(); release.await(5, TimeUnit.SECONDS); response.body!!.bytes()
                    }
                } }
                assertTrue(four.await(5, TimeUnit.SECONDS)); Thread.sleep(100)
                assertEquals(4, ready.get()); release.countDown()
                jobs.forEach { it.get(10, TimeUnit.SECONDS) }
            } finally { release.countDown(); pool.shutdownNow() }
        }
    }
    @Test fun rejectsWrongRangesAndChangedFile() {
        Fixture().use { fixture ->
            val session = MediaTransferSession(fixture.entry.url("/entry")); val client = fixture.client(session)
            client.newCall(fixture.request()).execute().use { it.body!!.bytes() }
            fixture.badRange = true
            try { client.newCall(fixture.request(4, 7)).execute().close(); fail("bad Range accepted") } catch (_: IOException) { }
            fixture.badRange = false; fixture.expired = true; fixture.changed = true
            try { client.newCall(fixture.request(4, 7)).execute().close(); fail("changed file accepted") } catch (_: IOException) { }
        }
    }
    @Test fun keepsOrdinaryTransportForNonRangeServers() {
        val server = MockWebServer(); server.start()
        try {
            server.enqueue(MockResponse().setBody("plain-video"))
            val session = MediaTransferSession(server.url("/video"))
            OkHttpClient.Builder().addInterceptor(session).build().newCall(Request.Builder().url(server.url("/video"))
                .header("Range", "bytes=0-3").build()).execute().use { assertEquals("plain-video", it.body!!.string()) }
            assertFalse(session.supportsRanges)
        } finally { server.shutdown() }
    }
    @Test fun rollingRateSurvivesBurstGapsAndActuallyExpires() {
        var now = 0L
        val rate = RollingNetworkRate { now }
        now = 500; rate.add(3L * 1024 * 1024)
        now = 1000; assertEquals(3L * 1024 * 1024, rate.sample())
        now = 2000; assertTrue(rate.sample() > 0)
        now = 3500; assertEquals(0L, rate.sample())
    }
    @Test fun automaticallyTunesWithinBounds() {
        val policy = AutoDownloadPolicy(); assertEquals(2, policy.concurrency)
        repeat(20) { policy.completed(4L * 1024 * 1024, 1_000_000_000) }
        assertEquals(4, policy.concurrency); assertEquals(8L * 1024 * 1024, policy.segmentBytes)
        repeat(10) { policy.failed() }; assertEquals(2, policy.concurrency)
    }

    @Test fun decoderCanCancelAnOverlappingSlowPrefetchWithoutCancellingTheNextSegment() {
        Fixture().use { fixture ->
            val session = MediaTransferSession(fixture.entry.url("/entry")); val client = fixture.client(session)
            client.newCall(fixture.request()).execute().use { it.body!!.bytes() }
            val prefetch = session.callFactory(client, true)
            val slow = prefetch.newCall(fixture.request(4, 7))
            val next = prefetch.newCall(fixture.request(8, 11))
            slow.execute().use { slowResponse ->
                next.execute().use { nextResponse ->
                    session.onDemand(5)
                    assertTrue(slow.isCanceled()); assertFalse(next.isCanceled())
                    assertEquals("ijkl", nextResponse.body!!.string())
                    session.callFactory(client, false).newCall(fixture.request(4, 7)).execute().use {
                        assertEquals("efgh", it.body!!.string())
                    }
                    // Closing the cancelled owner still releases its transport slot.
                    runCatching { slowResponse.body!!.source().read(Buffer(), 4) }
                }
            }
            assertEquals(1, fixture.entries.get())
        }
    }

    @Test fun aPrefetchCancelledBeforeOpeningNeverStartsANetworkRequest() {
        Fixture().use { fixture ->
            val session = MediaTransferSession(fixture.entry.url("/entry"))
            PrefetchCancellation.current.set { true }
            try {
                val call = session.callFactory(fixture.client(session), true).newCall(fixture.request())
                assertTrue(call.isCanceled())
                try { call.execute().close(); fail("cancelled prefetch ran") } catch (_: IOException) { }
                assertEquals(0, fixture.entries.get())
            } finally { PrefetchCancellation.current.remove() }
        }
    }
}
