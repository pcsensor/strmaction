package top.strmaction.companion

import android.content.Context
import android.webkit.CookieManager
import org.json.JSONObject

/** 原生层直接请求 /api/play/{id}，播放地址不经过 JS（§12.8）。 */
object PlayApi {

    fun serverUrl(context: Context): String =
        context.getSharedPreferences(MainActivity.PREFS, Context.MODE_PRIVATE)
            .getString(MainActivity.KEY_SERVER, "")
            ?.trim()
            ?.trimEnd('/')
            ?: ""

    fun mpvPackage(context: Context): String =
        context.getSharedPreferences(MainActivity.PREFS, Context.MODE_PRIVATE)
            .getString(MainActivity.KEY_MPV_PACKAGE, "is.xyz.mpv")
            ?.trim()
            ?.ifBlank { "is.xyz.mpv" }
            ?: "is.xyz.mpv"

    fun fetch(context: Context, itemId: Int, mode: String?): PlayInfo {
        val base = serverUrl(context)
        if (base.isBlank()) throw PlayApiException(0, "尚未配置服务器地址")
        val conn = TlsPolicy.openConnection(context, "$base/api/play/$itemId").apply {
            requestMethod = "POST"
            doOutput = true
            useCaches = false
            connectTimeout = 10_000
            readTimeout = 20_000
            setRequestProperty("Content-Type", "application/json; charset=utf-8")
            setRequestProperty("Accept", "application/json")
            setRequestProperty("X-StrmAction-Companion", "1")
            setRequestProperty(
                "User-Agent",
                "StrmActionCompanion/${BuildConfig.VERSION_NAME} (Android ${android.os.Build.VERSION.RELEASE})",
            )
        }
        val cookie = runCatching { CookieManager.getInstance().getCookie(base) }.getOrNull()
        if (!cookie.isNullOrBlank()) conn.setRequestProperty("Cookie", cookie)

        val payload = JSONObject().apply {
            if (!mode.isNullOrBlank()) put("mode", mode)
        }.toString()
        conn.outputStream.use { it.write(payload.toByteArray(Charsets.UTF_8)) }

        val status = conn.responseCode
        val stream = if (status in 200..299) conn.inputStream else conn.errorStream
        val text = stream?.bufferedReader(Charsets.UTF_8)?.use { it.readText() } ?: ""
        if (status !in 200..299) {
            val parsed = runCatching { JSONObject(text) }.getOrNull()
            val message = parsed?.optJSONObject("error")?.optString("message")
                ?.takeIf { it.isNotBlank() }
                ?: "服务器返回 HTTP $status"
            throw PlayApiException(status, message)
        }
        val json = runCatching { JSONObject(text) }
            .getOrElse { throw PlayApiException(status, "服务器响应不是合法 JSON") }

        val headers = mutableMapOf<String, String>()
        json.optJSONObject("headers")?.let { obj ->
            obj.keys().forEach { key ->
                val value = obj.optString(key)
                if (key.isNotBlank() && value.isNotBlank()) headers[key] = value
            }
        }

        val subtitles = mutableListOf<SubtitleInfo>()
        val subsArray = json.optJSONArray("subtitles")
        if (subsArray != null) {
            for (index in 0 until subsArray.length()) {
                val entry = subsArray.optJSONObject(index) ?: continue
                val url = entry.optString("url")
                if (url.isBlank()) continue
                subtitles += SubtitleInfo(
                    label = entry.optString("label").ifBlank { "字幕 ${index + 1}" },
                    lang = entry.optString("lang").ifBlank { "und" },
                    mime = subtitleMime(entry.optString("format"), entry.optString("mime")),
                    url = absoluteUrl(base, url),
                )
            }
        }

        val nextId = json.optInt("next_item_id", 0)
        val nextTitle = listOf(
            json.optString("next_episode_code"),
            json.optString("next_title"),
        ).filter { it.isNotBlank() }.joinToString(" ")
        val duration = json.optLong("duration_ms", 0L)
        val interval = json.optLong("progress_interval_ms", 5000L)

        val playlist = mutableListOf<PlayEntry>()
        val playlistArray = json.optJSONArray("playlist")
        if (playlistArray != null) {
            for (index in 0 until playlistArray.length()) {
                val entry = playlistArray.optJSONObject(index) ?: continue
                val id = entry.optInt("id", 0)
                if (id <= 0) continue
                playlist += PlayEntry(
                    id = id,
                    title = entry.optString("title"),
                    seasonNo = entry.optInt("season_no", 0).takeIf { it > 0 },
                    episodeNo = entry.optInt("episode_no", 0).takeIf { it > 0 },
                    code = entry.optString("code").takeIf { it.isNotBlank() },
                    watched = entry.optBoolean("watched", false),
                    current = entry.optBoolean("current", false),
                )
            }
        }
        return PlayInfo(
            serverUrl = base,
            itemId = json.optInt("item_id", itemId),
            title = json.optString("title").ifBlank { "正在播放" },
            playUrl = json.optString("play_url"),
            resumeMs = json.optLong("resume_ms", 0L).coerceAtLeast(0L),
            durationMs = duration.takeIf { it > 0 },
            headers = headers,
            playToken = json.optString("play_token"),
            nextItemId = nextId.takeIf { it > 0 },
            nextTitle = nextTitle,
            progressIntervalMs = interval.coerceIn(3000L, 60_000L),
            cacheLimitMb = PlaybackCache.normalize(
                json.optInt("cache_limit_mb", PlaybackCache.DEFAULT_LIMIT_MB),
            ),
            fallbackOnError = json.optBoolean("fallback_on_error", true),
            mpvPackage = json.optString("mpv_package").ifBlank { mpvPackage(context) },
            subtitles = subtitles,
            mode = json.optString("mode").ifBlank { "builtin" },
            seriesTitle = json.optString("series_title").takeIf { it.isNotBlank() },
            playlist = playlist,
            currentIndex = json.optInt("current_index", -1),
        ).also {
            if (it.playUrl.isBlank()) throw PlayApiException(status, "服务器没有返回播放地址")
            if (it.playToken.isBlank()) throw PlayApiException(status, "服务器没有返回播放凭证")
        }
    }
}
