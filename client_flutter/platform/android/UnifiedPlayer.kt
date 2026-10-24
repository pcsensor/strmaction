package top.strmaction.companion

import android.content.Context
import android.content.Intent
import android.media.AudioManager
import android.net.Uri
import android.os.Build
import android.os.Handler
import android.os.Looper
import android.view.WindowManager
import androidx.media3.common.AudioAttributes
import androidx.media3.common.C
import androidx.media3.common.MediaItem
import androidx.media3.common.MimeTypes
import androidx.media3.common.PlaybackException
import androidx.media3.common.Player
import androidx.media3.common.TrackSelectionOverride
import androidx.media3.common.Tracks
import androidx.media3.datasource.DataSource
import androidx.media3.datasource.DefaultDataSource
import androidx.media3.datasource.cache.CacheDataSource
import androidx.media3.datasource.okhttp.OkHttpDataSource
import androidx.media3.exoplayer.DefaultLoadControl
import androidx.media3.exoplayer.ExoPlayer
import androidx.media3.exoplayer.source.DefaultMediaSourceFactory
import androidx.media3.ui.PlayerView
import io.flutter.plugin.common.EventChannel
import okhttp3.OkHttpClient
import okhttp3.HttpUrl.Companion.toHttpUrl
import java.util.concurrent.TimeUnit

/** Only transport, decoding, tracks and platform lifecycle live here. */
class UnifiedPlayer(private val activity: MainActivity) {
    companion object { var active: UnifiedPlayer? = null }
    var exo: ExoPlayer? = null
        private set
    var sink: EventChannel.EventSink? = null
    var surface: PlayerView? = null
    var inPiP = false
    var loaded = false
        private set
    var title = "StrmAction"
        private set
    private val handler = Handler(Looper.getMainLooper())
    private var prefetch: PlaybackPrefetcher? = null
    private var transport: OkHttpClient? = null
    private var transferSession: MediaTransferSession? = null
    private var error: String? = null
    private var diskLimit = 0
    private val audio = activity.getSystemService(Context.AUDIO_SERVICE) as AudioManager
    private val originalBrightness = activity.window.attributes.screenBrightness
    private val tick = object : Runnable {
        override fun run() { emit(); handler.postDelayed(this, 500) }
    }
    init { active = this; handler.post(tick) }

    fun command(method: String, value: Any?) {
        when (method) {
            "load" -> load(value as Map<*, *>)
            "play" -> {
                if (exo?.playbackState == Player.STATE_ENDED) exo?.seekTo(0)
                exo?.play(); startService()
            }
            "pause" -> exo?.pause()
            "seek" -> { prefetch?.onSeek(); exo?.seekTo((value as Number).toLong().coerceAtLeast(0)) }
            "speed" -> exo?.setPlaybackSpeed((value as Number).toFloat().coerceIn(0.25f, 4f))
            "volume" -> {
                val max = audio.getStreamMaxVolume(AudioManager.STREAM_MUSIC)
                audio.setStreamVolume(AudioManager.STREAM_MUSIC, ((value as Number).toDouble().coerceIn(0.0, 100.0) * max / 100).toInt(), 0)
            }
            "audio" -> selectTrack(C.TRACK_TYPE_AUDIO, value as? String)
            "subtitle" -> selectTrack(C.TRACK_TYPE_TEXT, value as? String)
            "pip" -> activity.enterPlayerPiP()
            "brightness" -> {
                val params = activity.window.attributes
                val current = if (params.screenBrightness < 0) 0.5f else params.screenBrightness
                params.screenBrightness = (current + (value as Number).toFloat()).coerceIn(0.02f, 1f)
                activity.window.attributes = params
            }
            "settings" -> prefetch?.setWindowMb(((value as Map<*, *>)["buffer_limit_mb"] as Number).toInt().coerceAtMost(diskLimit))
            "dispose" -> clear()
            else -> throw IllegalArgumentException("Unknown player command: $method")
        }
        emit()
    }

    private fun load(data: Map<*, *>) {
        clear()
        loaded = true
        active = this
        error = null
        title = data["title"] as? String ?: "StrmAction"
        val uri = Uri.parse(data["play_url"] as String)
        val headers = (data["headers"] as? Map<*, *>)?.entries?.associate { it.key.toString() to it.value.toString() } ?: emptyMap()
        diskLimit = (data["disk_cache_limit_mb"] as? Number)?.toInt()?.coerceIn(0, 32768) ?: 2048
        val buffer = (data["buffer_limit_mb"] as? Number)?.toInt()?.coerceIn(0, 8192) ?: 512
        val cache = PlaybackDiskCache.open(activity, diskLimit)
        val session = MediaTransferSession(uri.toString().toHttpUrl())
        transferSession = session
        prefetch = PlaybackPrefetcher({ PlaybackDiskCache.current() }, session.policy).also {
            it.setWindowMb(if (cache == null) 0 else buffer.coerceAtMost(PlaybackDiskCache.limitMb()))
        }
        val client = PrivateCa.configure(OkHttpClient.Builder())
            .connectTimeout(15, TimeUnit.SECONDS).readTimeout(30, TimeUnit.SECONDS)
            .followRedirects(true).followSslRedirects(true)
            .addInterceptor(session)
            .build()
        transport = client
        val http = OkHttpDataSource.Factory(client).setDefaultRequestProperties(headers).setTransferListener(NetworkSpeedMeter)
        headers.entries.firstOrNull { it.key.equals("User-Agent", true) }?.let { http.setUserAgent(it.value) }
        val upstream = DefaultDataSource.Factory(activity, http)
        val factory: DataSource.Factory = if (cache != null) CacheDataSource.Factory()
            .setCache(cache).setUpstreamDataSourceFactory(upstream)
            .setFlags(CacheDataSource.FLAG_BLOCK_ON_CACHE or CacheDataSource.FLAG_IGNORE_CACHE_ON_ERROR) else upstream
        val loadControl = DefaultLoadControl.Builder()
            .setTargetBufferBytes(PlaybackCache.targetBufferBytes())
            .setBufferDurationsMs(PlaybackCache.bufferTimeCapMs(), PlaybackCache.bufferTimeCapMs(), 2000, 3000)
            .setPrioritizeTimeOverSizeThresholds(false).build()
        val player = ExoPlayer.Builder(activity).setMediaSourceFactory(DefaultMediaSourceFactory(DataSource.Factory { SegmentedDataSource(factory, session) }))
            .setLoadControl(loadControl).build()
        exo = player
        surface?.player = player
        player.setAudioAttributes(AudioAttributes.Builder().setUsage(C.USAGE_MEDIA).setContentType(C.AUDIO_CONTENT_TYPE_MOVIE).build(), true)
        player.setHandleAudioBecomingNoisy(true)
        player.setWakeMode(C.WAKE_MODE_LOCAL)
        player.addListener(object : Player.Listener {
            override fun onPlayerError(exception: PlaybackException) { error = exception.localizedMessage ?: "播放失败"; emit() }
            override fun onEvents(player: Player, events: Player.Events) { emit() }
        })
        val subtitles = (data["subtitles"] as? List<*>)?.mapIndexedNotNull { index, entry ->
            val sub = entry as? Map<*, *> ?: return@mapIndexedNotNull null
            val url = sub["url"] as? String ?: return@mapIndexedNotNull null
            val ext = (sub["format"] as? String) ?: Uri.parse(url).getQueryParameter("format") ?: Uri.parse(url).path?.substringAfterLast('.')
            val mime = sub["mime"] as? String ?: when (ext?.lowercase()) { "vtt" -> MimeTypes.TEXT_VTT; "ass", "ssa" -> MimeTypes.TEXT_SSA; else -> MimeTypes.APPLICATION_SUBRIP }
            MediaItem.SubtitleConfiguration.Builder(Uri.parse(url)).setMimeType(mime)
                .setLabel(sub["label"] as? String ?: "字幕 ${index + 1}")
                .setSelectionFlags(if (index == 0) C.SELECTION_FLAG_DEFAULT else 0).build()
        } ?: emptyList()
        player.setMediaItem(MediaItem.Builder().setUri(uri).setSubtitleConfigurations(subtitles).build(), (data["resume_ms"] as? Number)?.toLong() ?: 0)
        // setSource resets the length: set it before the first HTTP request.
        prefetch?.setSource(factory, uri)
        prefetch?.start()
        player.prepare(); player.play()
        activity.window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        startService()
    }
    private fun startService() {
        if (!loaded) return
        val intent = Intent(activity, PlaybackService::class.java)
        if (Build.VERSION.SDK_INT >= 26) activity.startForegroundService(intent) else activity.startService(intent)
    }
    private fun selectTrack(type: Int, id: String?) {
        val player = exo ?: return
        val builder = player.trackSelectionParameters.buildUpon().clearOverridesOfType(type).setTrackTypeDisabled(type, id == null)
        if (id != null) {
            val parts = id.split(':').map { it.toInt() }
            val group = player.currentTracks.groups.getOrNull(parts[0]) ?: return
            if (group.type != type || parts[1] >= group.length) return
            builder.setOverrideForType(TrackSelectionOverride(group.mediaTrackGroup, listOf(parts[1])))
        }
        player.trackSelectionParameters = builder.build()
    }
    private fun trackState(type: Int): Pair<List<Map<String, Any>>, String?> {
        val entries = mutableListOf<Map<String, Any>>()
        var selected: String? = null
        exo?.currentTracks?.groups?.forEachIndexed { gi, group ->
            if (group.type == type) for (ti in 0 until group.length) {
                if (!group.isTrackSupported(ti)) continue
                val format = group.getTrackFormat(ti)
                val id = "$gi:$ti"
                entries.add(mapOf("id" to id, "title" to (format.label ?: format.language ?: "${if (type == C.TRACK_TYPE_AUDIO) "音轨" else "字幕"} ${entries.size + 1}")))
                if (group.isTrackSelected(ti)) selected = id
            }
        }
        return Pair(entries, selected)
    }
    fun emit() {
        val player = exo
        val duration = player?.duration?.coerceAtLeast(0) ?: 0
        transferSession?.takeIf { it.supportsRanges }?.let { prefetch?.setContentLength(it.contentLength) }
        prefetch?.onTick(player?.currentPosition ?: 0, player?.bufferedPosition ?: 0, duration, player?.playbackState == Player.STATE_BUFFERING)
        val tracks = trackState(C.TRACK_TYPE_AUDIO)
        val subtitles = trackState(C.TRACK_TYPE_TEXT)
        val max = audio.getStreamMaxVolume(AudioManager.STREAM_MUSIC).coerceAtLeast(1)
        sink?.success(mapOf(
            "position_ms" to (player?.currentPosition ?: 0), "duration_ms" to duration,
            "buffered_ms" to (player?.bufferedPosition ?: 0),
            "playing" to (player?.isPlaying == true), "loading" to (loaded && player?.playbackState == Player.STATE_IDLE),
            "buffering" to (player?.playbackState == Player.STATE_BUFFERING),
            "completed" to (player?.playbackState == Player.STATE_ENDED),
            "speed" to (player?.playbackParameters?.speed ?: 1f), "error" to error,
            "volume" to (audio.getStreamVolume(AudioManager.STREAM_MUSIC) * 100.0 / max),
            "network_speed" to NetworkSpeedMeter.sample(), "audio_tracks" to tracks.first, "audio_id" to tracks.second,
            "subtitle_tracks" to subtitles.first, "subtitle_id" to subtitles.second, "pip" to inPiP,
            "cached_ranges" to (prefetch?.cachedSpansMs()?.map { mapOf("start_ms" to it.first, "end_ms" to it.last) } ?: emptyList<Map<String, Long>>()),
        ))
        PlaybackService.instance?.updateSession()
    }
    private fun clear() {
        loaded = false
        surface?.player = null
        transport?.dispatcher?.cancelAll()
        exo?.release(); exo = null
        prefetch?.stop(); prefetch = null
        transport?.connectionPool?.evictAll(); transport = null; transferSession = null
        PlaybackDiskCache.close(clear = true)
        NetworkSpeedMeter.reset()
        activity.stopService(Intent(activity, PlaybackService::class.java))
        activity.window.clearFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        val params = activity.window.attributes
        params.screenBrightness = originalBrightness
        activity.window.attributes = params
    }
    fun close() {
        clear(); handler.removeCallbacks(tick); sink = null
        if (active === this) active = null
    }
}
