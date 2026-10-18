package top.strmaction.companion

import android.app.PictureInPictureParams
import android.content.Intent
import android.content.res.Configuration
import android.graphics.Color
import android.graphics.drawable.GradientDrawable
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.os.SystemClock
import android.util.Log
import android.util.Rational
import android.view.Gravity
import android.view.KeyEvent
import android.view.View
import android.view.ViewGroup
import android.view.WindowManager
import android.widget.FrameLayout
import android.widget.LinearLayout
import android.widget.ProgressBar
import android.widget.TextView
import android.widget.Toast
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AlertDialog
import androidx.appcompat.app.AppCompatActivity
import androidx.core.view.WindowCompat
import androidx.core.view.WindowInsetsCompat
import androidx.core.view.WindowInsetsControllerCompat
import androidx.media3.common.C
import androidx.media3.common.MediaItem
import androidx.media3.common.PlaybackException
import androidx.media3.common.Player
import androidx.media3.common.TrackSelectionOverride
import androidx.media3.common.Tracks
import androidx.media3.common.util.UnstableApi
import androidx.media3.datasource.DefaultHttpDataSource
import androidx.media3.exoplayer.DefaultRenderersFactory
import androidx.media3.exoplayer.ExoPlayer
import androidx.media3.exoplayer.source.DefaultMediaSourceFactory
import androidx.media3.ui.AspectRatioFrameLayout
import androidx.media3.ui.PlayerView
import java.util.concurrent.Executors

/**
 * v0.8 内置播放器：Media3 解码 + 5 秒心跳 + 无缝连播 + mpv 兜底。
 * 手机优先，电视遥控器同样可用。
 */
class PlayerActivity : AppCompatActivity() {

    companion object {
        const val EXTRA_ITEM_ID = "item_id"
        const val EXTRA_MODE = "mode"
        private const val TAG = "StrmActionPlayer"
    }

    private lateinit var root: FrameLayout
    private lateinit var playerView: PlayerView
    private lateinit var titleView: TextView
    private lateinit var topBar: LinearLayout
    private lateinit var loadingView: LinearLayout
    private lateinit var loadingText: TextView

    private var player: ExoPlayer? = null
    private var playerHeadersKey: String? = null
    private var info: PlayInfo? = null
    private var currentItemId: Int = 0
    private var loading = false
    private var advancing = false
    private var wasPlaying = false
    private var playingSince = 0L
    private var controllerVisible = true
    private var nextTicker: Runnable? = null

    private val main = Handler(Looper.getMainLooper())
    private val executor = Executors.newSingleThreadExecutor { runnable ->
        Thread(runnable, "strmaction-player").apply { isDaemon = true }
    }

    private val mpvLauncher = registerForActivityResult(
        ActivityResultContracts.StartActivityForResult(),
    ) { result ->
        onMpvResult(result.resultCode, result.data)
    }

    private val heartbeat = object : Runnable {
        override fun run() {
            val active = player?.isPlaying == true
            if (active) {
                reportProgress(finished = false)
                main.postDelayed(this, info?.progressIntervalMs ?: 5000L)
            }
        }
    }
    private var heartbeatRunning = false

    private val playbackListener = object : Player.Listener {
        override fun onPlaybackStateChanged(state: Int) {
            when (state) {
                Player.STATE_READY -> {
                    loadingView.visibility = View.GONE
                    if (player?.isPlaying == true) startHeartbeat()
                }
                Player.STATE_ENDED -> onEnded()
                Player.STATE_BUFFERING -> loadingView.visibility = View.VISIBLE
            }
        }

        override fun onIsPlayingChanged(isPlaying: Boolean) {
            wasPlaying = isPlaying
            if (isPlaying) {
                if (playingSince == 0L) playingSince = SystemClock.elapsedRealtime()
                startHeartbeat()
            } else {
                playingSince = 0L
                stopHeartbeat()
                flushProgressOnce()
            }
        }

        override fun onPlayerError(error: PlaybackException) {
            Log.e(TAG, "playback error: ${error.errorCodeName}", error)
            stopHeartbeat()
            onPlaybackFailed(error)
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        val itemId = intent.getIntExtra(EXTRA_ITEM_ID, 0)
        if (itemId <= 0) {
            finish()
            return
        }
        currentItemId = itemId
        if (Device.isTelevision(this)) {
            requestedOrientation = android.content.pm.ActivityInfo.SCREEN_ORIENTATION_LANDSCAPE
            WindowCompat.setDecorFitsSystemWindows(window, false)
            hideSystemBars()
        } else {
            // 手机：保留状态栏/导航栏，避免全屏引导条干扰播放与画中画
            WindowCompat.setDecorFitsSystemWindows(window, true)
            @Suppress("DEPRECATION")
            run {
                window.statusBarColor = Color.BLACK
                window.navigationBarColor = Color.BLACK
            }
        }

        buildUi()
        setContentView(root)
        load(itemId, intent.getStringExtra(EXTRA_MODE))
    }

    // ------------------------------------------------------------------
    // UI
    // ------------------------------------------------------------------

    private fun buildUi() {
        root = FrameLayout(this).apply { setBackgroundColor(Color.BLACK) }

        playerView = PlayerView(this).apply {
            layoutParams = FrameLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.MATCH_PARENT,
            )
            useController = true
            controllerAutoShow = true
            controllerShowTimeoutMs = 4000
            setShowBuffering(PlayerView.SHOW_BUFFERING_ALWAYS)
            setShowNextButton(false)
            setShowPreviousButton(false)
            setKeepContentOnPlayerReset(true)
            resizeMode = AspectRatioFrameLayout.RESIZE_MODE_FIT
            setBackgroundColor(Color.BLACK)
            setControllerVisibilityListener(
                PlayerView.ControllerVisibilityListener { visibility ->
                    controllerVisible = visibility == View.VISIBLE
                    topBar.visibility = if (controllerVisible) View.VISIBLE else View.GONE
                },
            )
        }
        root.addView(playerView)

        topBar = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER_VERTICAL
            setPadding(dp(20), dp(14), dp(20), dp(14))
            background = GradientDrawable(
                GradientDrawable.Orientation.TOP_BOTTOM,
                intArrayOf(0xCC000000.toInt(), 0x66000000),
            )
            layoutParams = FrameLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.WRAP_CONTENT,
            ).apply { gravity = Gravity.TOP }
        }
        val backButton = TextView(this).apply {
            text = "‹"
            setTextColor(Color.WHITE)
            textSize = 26f
            gravity = Gravity.CENTER
            setPadding(dp(14), 0, dp(16), dp(2))
            isFocusable = true
            isClickable = true
            setOnClickListener { finishWithResult() }
        }
        titleView = TextView(this).apply {
            text = getString(R.string.player_loading)
            setTextColor(Color.WHITE)
            textSize = 16f
            maxLines = 1
            ellipsize = android.text.TextUtils.TruncateAt.END
            layoutParams = LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f)
        }
        val menuButton = TextView(this).apply {
            text = getString(R.string.player_menu)
            setTextColor(Color.WHITE)
            textSize = 14f
            gravity = Gravity.CENTER
            setPadding(dp(16), dp(8), dp(16), dp(8))
            background = rounded(0x33FFFFFF, 999f)
            isFocusable = true
            isClickable = true
            setOnClickListener { showMenu() }
        }
        val pipButton = TextView(this).apply {
            text = "⧉"
            setTextColor(Color.WHITE)
            textSize = 18f
            gravity = Gravity.CENTER
            setPadding(dp(12), dp(6), dp(12), dp(8))
            background = rounded(0x33FFFFFF, 999f)
            isFocusable = true
            isClickable = true
            contentDescription = getString(R.string.player_pip)
            visibility = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O &&
                Device.isTouchDevice(this@PlayerActivity)
            ) {
                View.VISIBLE
            } else {
                View.GONE
            }
            setOnClickListener { enterPip() }
        }
        topBar.addView(backButton)
        topBar.addView(titleView)
        topBar.addView(pipButton)
        topBar.addView(menuButton)
        root.addView(topBar)

        loadingView = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            gravity = Gravity.CENTER
            setBackgroundColor(0x66000000)
            layoutParams = FrameLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.MATCH_PARENT,
            )
        }
        loadingView.addView(
            ProgressBar(this).apply {
                indeterminateTintList = android.content.res.ColorStateList.valueOf(Color.parseColor("#E8B06A"))
            },
        )
        loadingText = TextView(this).apply {
            text = getString(R.string.player_loading)
            setTextColor(Color.parseColor("#C9CFDA"))
            textSize = 14f
            gravity = Gravity.CENTER
            setPadding(0, dp(14), 0, 0)
        }
        loadingView.addView(loadingText)
        loadingView.isClickable = true
        root.addView(loadingView)
    }

    private fun showMenu() {
        if (info == null) return
        data class Entry(val label: String, val action: () -> Unit)
        val entries = mutableListOf(
            Entry(getString(R.string.player_menu_subtitle)) { showSubtitleMenu() },
            Entry(getString(R.string.player_menu_audio)) { showAudioMenu() },
            Entry(getString(R.string.player_menu_speed)) { showSpeedMenu() },
        )
        if (info?.nextItemId != null) {
            val suffix = info?.nextTitle?.takeIf { it.isNotBlank() }?.let { " · $it" }.orEmpty()
            entries.add(
                Entry(getString(R.string.player_menu_next) + suffix) { advanceToNext() },
            )
        }
        entries.add(Entry(getString(R.string.player_menu_mpv)) { info?.let { openMpv(it) } })

        AlertDialog.Builder(this)
            .setTitle(R.string.player_menu)
            .setItems(entries.map { it.label }.toTypedArray()) { _, which ->
                entries.getOrNull(which)?.action?.invoke()
            }
            .show()
    }

    private fun textTracks(): List<Pair<Tracks.Group, Int>> {
        val result = mutableListOf<Pair<Tracks.Group, Int>>()
        val groups = player?.currentTracks?.groups ?: return result
        for (group in groups) {
            if (group.type != C.TRACK_TYPE_TEXT) continue
            for (index in 0 until group.length) {
                if (group.isTrackSupported(index)) result.add(group to index)
            }
        }
        return result
    }

    private fun audioTracks(): List<Pair<Tracks.Group, Int>> {
        val result = mutableListOf<Pair<Tracks.Group, Int>>()
        val groups = player?.currentTracks?.groups ?: return result
        for (group in groups) {
            if (group.type != C.TRACK_TYPE_AUDIO) continue
            for (index in 0 until group.length) {
                if (group.isTrackSupported(index)) result.add(group to index)
            }
        }
        return result
    }

    private fun trackLabel(group: Tracks.Group, index: Int): String {
        val format = group.getTrackFormat(index)
        val label = format.label?.takeIf { it.isNotBlank() }
            ?: format.language?.takeIf { it.isNotBlank() }
            ?: "轨道 ${index + 1}"
        return label
    }

    private fun showSubtitleMenu() {
        val tracks = textTracks()
        if (tracks.isEmpty()) {
            toast(getString(R.string.player_no_track))
            return
        }
        val labels = mutableListOf(getString(R.string.player_subtitle_off))
        tracks.forEach { (group, index) -> labels.add(trackLabel(group, index)) }
        AlertDialog.Builder(this)
            .setTitle(R.string.player_menu_subtitle)
            .setItems(labels.toTypedArray()) { _, which ->
                val exo = player ?: return@setItems
                if (which == 0) {
                    exo.trackSelectionParameters = exo.trackSelectionParameters
                        .buildUpon()
                        .setTrackTypeDisabled(C.TRACK_TYPE_TEXT, true)
                        .build()
                } else {
                    val (group, index) = tracks[which - 1]
                    exo.trackSelectionParameters = exo.trackSelectionParameters
                        .buildUpon()
                        .setTrackTypeDisabled(C.TRACK_TYPE_TEXT, false)
                        .setOverrideForType(TrackSelectionOverride(group.mediaTrackGroup, index))
                        .build()
                }
            }
            .setNegativeButton(android.R.string.cancel, null)
            .show()
    }

    private fun showAudioMenu() {
        val tracks = audioTracks()
        if (tracks.isEmpty()) {
            toast(getString(R.string.player_no_track))
            return
        }
        val labels = tracks.map { (group, index) -> trackLabel(group, index) }
        AlertDialog.Builder(this)
            .setTitle(R.string.player_menu_audio)
            .setItems(labels.toTypedArray()) { _, which ->
                val exo = player ?: return@setItems
                val (group, index) = tracks[which]
                exo.trackSelectionParameters = exo.trackSelectionParameters
                    .buildUpon()
                    .setOverrideForType(TrackSelectionOverride(group.mediaTrackGroup, index))
                    .build()
            }
            .show()
    }

    private fun showSpeedMenu() {
        val speeds = floatArrayOf(0.5f, 0.75f, 1f, 1.25f, 1.5f, 2f)
        val labels = speeds.map { if (it == 1f) "1.0x（正常）" else "${it}x" }.toTypedArray()
        AlertDialog.Builder(this)
            .setTitle(R.string.player_menu_speed)
            .setItems(labels) { _, which ->
                player?.setPlaybackSpeed(speeds[which])
            }
            .show()
    }

    // ------------------------------------------------------------------
    // 加载与播放
    // ------------------------------------------------------------------

    private fun load(itemId: Int, mode: String?) {
        showLoading(getString(R.string.player_loading))
        executor.execute {
            val result = runCatching { PlayApi.fetch(this, itemId, mode) }
            runOnUiThread {
                if (isFinishing || isDestroyed) return@runOnUiThread
                result.onSuccess { playInfo ->
                    currentItemId = playInfo.itemId
                    info = playInfo
                    // 设置页把默认播放器改成“外部 mpv”时，服务端会下发 external_mpv
                    val external = mode == "external_mpv" ||
                        (mode == null && playInfo.mode == "external_mpv")
                    if (external) {
                        openMpv(playInfo)
                    } else {
                        playItem(playInfo, playInfo.resumeMs)
                    }
                }.onFailure { error ->
                    showLoadError(error)
                }
            }
        }
    }

    private fun playItem(playInfo: PlayInfo, startMs: Long) {
        info = playInfo
        currentItemId = playInfo.itemId
        advancing = false
        titleView.text = playInfo.title
        loadingView.visibility = View.GONE

        val exo = ensurePlayer(playInfo)
        val subtitles = playInfo.subtitles.mapIndexed { index, subtitle ->
            MediaItem.SubtitleConfiguration.Builder(Uri.parse(subtitle.url))
                .setMimeType(subtitle.mime)
                .setLanguage(subtitle.lang)
                .setLabel(subtitle.label)
                .setSelectionFlags(if (index == 0) C.SELECTION_FLAG_DEFAULT else 0)
                .build()
        }
        val mediaItem = MediaItem.Builder()
            .setUri(playInfo.playUrl)
            .setMediaId(playInfo.itemId.toString())
            .setSubtitleConfigurations(subtitles)
            .build()
        exo.setMediaItem(mediaItem, startMs.coerceAtLeast(0L))
        exo.prepare()
        exo.playWhenReady = true
        exo.play()
    }

    private fun ensurePlayer(playInfo: PlayInfo): ExoPlayer {
        val headersKey = playInfo.headers.entries
            .sortedBy { it.key.lowercase() }
            .joinToString("|") { "${it.key.lowercase()}=${it.value}" }
        val existing = player
        if (existing != null && playerHeadersKey == headersKey) return existing
        if (existing != null) {
            // 不同媒体库的 UA/Referer 不同：换源时必须重建播放器，否则请求头还是上一集的
            runCatching { existing.release() }
            player = null
            playerView.player = null
        }
        val http = DefaultHttpDataSource.Factory()
            .setDefaultRequestProperties(playInfo.headers)
            .setAllowCrossProtocolRedirects(true)
            .setConnectTimeoutMs(15_000)
            .setReadTimeoutMs(30_000)
        val exo = ExoPlayer.Builder(this)
            .setMediaSourceFactory(DefaultMediaSourceFactory(http))
            .setRenderersFactory(
                DefaultRenderersFactory(this).setEnableDecoderFallback(true),
            )
            .setHandleAudioBecomingNoisy(true)
            .build()
        exo.addListener(playbackListener)
        player = exo
        playerHeadersKey = headersKey
        playerView.player = exo
        return exo
    }

    private fun startHeartbeat() {
        if (heartbeatRunning) return
        heartbeatRunning = true
        main.postDelayed(heartbeat, info?.progressIntervalMs ?: 5000L)
    }

    private fun stopHeartbeat() {
        heartbeatRunning = false
        main.removeCallbacks(heartbeat)
    }

    private fun flushProgressOnce() {
        if (currentItemId > 0 && info != null) reportProgress(finished = false)
    }

    private fun reportProgress(finished: Boolean) {
        val playInfo = info ?: return
        val exo = player ?: return
        val duration = exo.duration.takeIf { it != C.TIME_UNSET && it > 0 }
            ?: playInfo.durationMs
        var position = exo.currentPosition.coerceAtLeast(0L)
        if (duration != null && duration > 0) position = position.coerceAtMost(duration)
        if (position <= 0 && !finished) return
        ProgressReporter.post(
            ProgressReporter.Report(
                serverUrl = playInfo.serverUrl,
                token = playInfo.playToken,
                itemId = currentItemId,
                positionMs = if (finished) 0L else position,
                durationMs = duration,
                finished = finished,
            ),
        ) {
            runOnUiThread {
                toast(getString(R.string.player_token_expired))
            }
        }
    }

    private fun onEnded() {
        stopHeartbeat()
        reportProgress(finished = true)
        val nextId = info?.nextItemId
        if (nextId == null || advancing) {
            main.postDelayed({ finishWithResult() }, 250)
            return
        }
        advancing = true
        showLoading(getString(R.string.player_loading))
        executor.execute {
            val result = runCatching { PlayApi.fetch(this, nextId, "builtin") }
            runOnUiThread {
                if (isFinishing || isDestroyed) return@runOnUiThread
                result.onSuccess { next -> playItem(next, 0L) }
                    .onFailure { advancing = false; finishWithResult() }
            }
        }
    }

    private fun advanceToNext() {
        val nextId = info?.nextItemId ?: return
        advancing = true
        flushProgressOnce()
        showLoading(getString(R.string.player_loading))
        executor.execute {
            val result = runCatching { PlayApi.fetch(this, nextId, "builtin") }
            runOnUiThread {
                if (isFinishing || isDestroyed) return@runOnUiThread
                result.onSuccess { next -> playItem(next, 0L) }
                    .onFailure {
                        advancing = false
                        loadingView.visibility = View.GONE
                        toast(it.message ?: getString(R.string.player_error_title))
                    }
            }
        }
    }

    // ------------------------------------------------------------------
    // 错误与 mpv 兜底
    // ------------------------------------------------------------------

    private fun showLoadError(error: Throwable) {
        Log.e(TAG, "load play info failed", error)
        loadingView.visibility = View.GONE
        val apiError = error as? PlayApiException
        val message = when {
            apiError?.statusCode == 401 -> getString(R.string.player_login_required)
            apiError != null -> apiError.message ?: getString(R.string.player_error_title)
            else -> error.message ?: getString(R.string.player_error_title)
        }
        if (info == null) {
            AlertDialog.Builder(this)
                .setTitle(R.string.player_error_title)
                .setMessage(message)
                .setPositiveButton(R.string.player_error_retry) { _, _ ->
                    load(currentItemId, intent.getStringExtra(EXTRA_MODE))
                }
                .setNegativeButton(R.string.player_error_close) { _, _ -> finish() }
                .setCancelable(false)
                .show()
        } else {
            showPlaybackFallback(message)
        }
    }

    private fun onPlaybackFailed(error: PlaybackException) {
        val message = error.errorCodeName + (error.cause?.message?.let { "：$it" } ?: "")
        showPlaybackFallback(message)
    }

    private fun showPlaybackFallback(message: String) {
        stopHeartbeat()
        AlertDialog.Builder(this)
            .setTitle(R.string.player_fallback_title)
            .setMessage(
                getString(R.string.player_fallback_message) +
                    "\n\n" + message,
            )
            .setPositiveButton(R.string.player_fallback_positive) { _, _ ->
                info?.let { openMpv(it) } ?: finish()
            }
            .setNegativeButton(R.string.player_fallback_negative) { _, _ -> finish() }
            .setCancelable(false)
            .show()
    }

    private fun openMpv(playInfo: PlayInfo) {
        if (!MpvFallback.isInstalled(this, playInfo.mpvPackage)) {
            toast(getString(R.string.player_mpv_missing))
            if (info == null || player == null) finish()
            return
        }
        runCatching { mpvLauncher.launch(MpvFallback.buildIntent(playInfo)) }
            .onFailure {
                toast(getString(R.string.player_mpv_missing))
                if (player == null) finish()
            }
    }

    private fun onMpvResult(resultCode: Int, data: Intent?) {
        if (resultCode != RESULT_OK) {
            finishWithResult()
            return
        }
        val playInfo = info
        if (playInfo == null || currentItemId <= 0) {
            finishWithResult()
            return
        }
        val finished = data?.hasExtra("position") != true
        val rawPosition = data?.getIntExtra("position", -1) ?: -1
        val rawDuration = data?.getIntExtra("duration", -1) ?: -1
        val duration = rawDuration.takeIf { it > 0 }
        val position = when {
            finished -> 0
            duration != null -> rawPosition.coerceIn(0, duration)
            else -> rawPosition.coerceAtLeast(0)
        }
        ProgressReporter.post(
            ProgressReporter.Report(
                serverUrl = playInfo.serverUrl,
                token = playInfo.playToken,
                itemId = currentItemId,
                positionMs = position.toLong(),
                durationMs = duration?.toLong(),
                finished = finished,
            ),
        )
        toast(getString(R.string.progress_saved))
        if (finished && playInfo.nextItemId != null) {
            showExternalNextDialog(playInfo.nextItemId)
            return
        }
        finishWithResult()
    }

    /** 外部 mpv 的连播：5 秒可取消（§12.10）。 */
    private fun showExternalNextDialog(nextId: Int) {
        val label = info?.nextTitle.orEmpty()
        var remaining = 5
        val dialog = AlertDialog.Builder(this)
            .setTitle(R.string.player_auto_next)
            .setMessage(
                getString(R.string.player_auto_next_message, remaining, label),
            )
            .setPositiveButton(R.string.player_play_now) { _, _ -> launchExternal(nextId) }
            .setNegativeButton(android.R.string.cancel) { _, _ -> finishWithResult() }
            .setCancelable(false)
            .create()
        dialog.setOnDismissListener {
            nextTicker?.let { main.removeCallbacks(it) }
            nextTicker = null
        }
        dialog.show()
        val ticker = object : Runnable {
            override fun run() {
                remaining -= 1
                if (remaining <= 0) {
                    nextTicker = null
                    dialog.dismiss()
                    launchExternal(nextId)
                } else {
                    dialog.setMessage(
                        getString(R.string.player_auto_next_message, remaining, label),
                    )
                    main.postDelayed(this, 1000)
                }
            }
        }
        nextTicker = ticker
        main.postDelayed(ticker, 1000)
    }

    private fun launchExternal(nextId: Int) {
        showLoading(getString(R.string.player_loading))
        executor.execute {
            val result = runCatching { PlayApi.fetch(this, nextId, "external_mpv") }
            runOnUiThread {
                if (isFinishing || isDestroyed) return@runOnUiThread
                result.onSuccess { next ->
                    currentItemId = next.itemId
                    info = next
                    openMpv(next)
                }.onFailure {
                    finishWithResult()
                }
            }
        }
    }

    // ------------------------------------------------------------------
    // 生命周期
    // ------------------------------------------------------------------

    private fun finishWithResult() {
        setResult(RESULT_OK, Intent().putExtra(EXTRA_ITEM_ID, currentItemId))
        finish()
    }

    override fun onStop() {
        if (!isInPictureInPictureMode) {
            player?.let { exo ->
                wasPlaying = exo.isPlaying
                if (exo.isPlaying) exo.pause()
            }
            stopHeartbeat()
            flushProgressOnce()
        }
        super.onStop()
    }

    override fun onStart() {
        super.onStart()
        if (wasPlaying && info != null && !isInPictureInPictureMode) {
            player?.play()
        }
    }

    override fun onDestroy() {
        stopHeartbeat()
        main.removeCallbacksAndMessages(null)
        runCatching { player?.release() }
        player = null
        playerView.player = null
        executor.shutdownNow()
        super.onDestroy()
    }

    override fun onUserLeaveHint() {
        super.onUserLeaveHint()
        // 只有「已经真正播放了一会儿」再按 Home 才进画中画；
        // 否则系统全屏提示、来电浮层等也会触发 onUserLeaveHint，导致播放器意外缩成小窗。
        val stable = playingSince > 0 &&
            SystemClock.elapsedRealtime() - playingSince > 1500
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O &&
            Device.isTouchDevice(this) &&
            stable &&
            player?.isPlaying == true &&
            !isInPictureInPictureMode
        ) {
            enterPip()
        }
    }

    override fun onPictureInPictureModeChanged(
        isInPictureInPictureMode: Boolean,
        newConfig: Configuration,
    ) {
        super.onPictureInPictureModeChanged(isInPictureInPictureMode, newConfig)
        topBar.visibility = if (isInPictureInPictureMode) View.GONE else View.VISIBLE
        playerView.useController = !isInPictureInPictureMode
        if (!isInPictureInPictureMode) hideSystemBars()
    }

    private fun enterPip() {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) return
        runCatching {
            enterPictureInPictureMode(
                PictureInPictureParams.Builder()
                    .setAspectRatio(Rational(16, 9))
                    .build(),
            )
        }
    }

    override fun dispatchKeyEvent(event: KeyEvent): Boolean {
        if (event.action == KeyEvent.ACTION_DOWN) {
            when (event.keyCode) {
                KeyEvent.KEYCODE_DPAD_CENTER,
                KeyEvent.KEYCODE_ENTER,
                KeyEvent.KEYCODE_SPACE,
                -> {
                    togglePlay()
                    return true
                }
                KeyEvent.KEYCODE_DPAD_LEFT -> {
                    seekBy(-10_000)
                    return true
                }
                KeyEvent.KEYCODE_DPAD_RIGHT -> {
                    seekBy(10_000)
                    return true
                }
                KeyEvent.KEYCODE_DPAD_UP,
                KeyEvent.KEYCODE_DPAD_DOWN,
                -> {
                    showMenu()
                    return true
                }
                KeyEvent.KEYCODE_MEDIA_PLAY_PAUSE,
                KeyEvent.KEYCODE_HEADSETHOOK,
                -> {
                    togglePlay()
                    return true
                }
                KeyEvent.KEYCODE_MEDIA_NEXT -> {
                    advanceToNext()
                    return true
                }
                KeyEvent.KEYCODE_MEDIA_FAST_FORWARD -> {
                    seekBy(30_000)
                    return true
                }
                KeyEvent.KEYCODE_MEDIA_REWIND -> {
                    seekBy(-30_000)
                    return true
                }
                KeyEvent.KEYCODE_BACK -> {
                    // 手机：一次返回直接退出（符合手机习惯）
                    // 电视：先收起 OSD，再按一次退出
                    if (Device.isTouchDevice(this)) {
                        finishWithResult()
                        return true
                    }
                    if (controllerVisible) {
                        playerView.hideController()
                        return true
                    }
                    finishWithResult()
                    return true
                }
            }
        }
        return super.dispatchKeyEvent(event)
    }

    private fun togglePlay() {
        val exo = player ?: return
        if (exo.isPlaying) exo.pause() else exo.play()
        playerView.showController()
    }

    private fun seekBy(deltaMs: Long) {
        val exo = player ?: return
        val duration = exo.duration.takeIf { it != C.TIME_UNSET && it > 0 }
        val target = (exo.currentPosition + deltaMs).coerceAtLeast(0L)
        exo.seekTo(if (duration != null) target.coerceAtMost(duration) else target)
        playerView.showController()
    }

    private fun hideSystemBars() {
        WindowInsetsControllerCompat(window, window.decorView).apply {
            hide(WindowInsetsCompat.Type.systemBars())
            systemBarsBehavior =
                WindowInsetsControllerCompat.BEHAVIOR_SHOW_TRANSIENT_BARS_BY_SWIPE
        }
    }

    // ------------------------------------------------------------------
    // 小工具
    // ------------------------------------------------------------------

    private fun showLoading(message: String) {
        loadingText.text = message
        loadingView.visibility = View.VISIBLE
    }

    private fun toast(message: String) {
        Toast.makeText(this, message, Toast.LENGTH_SHORT).show()
    }

    private fun dp(value: Int): Int = (value * resources.displayMetrics.density).toInt()

    private fun rounded(color: Int, radiusDp: Float): GradientDrawable =
        GradientDrawable().apply {
            shape = GradientDrawable.RECTANGLE
            cornerRadius = radiusDp * resources.displayMetrics.density
            setColor(color)
        }
}
