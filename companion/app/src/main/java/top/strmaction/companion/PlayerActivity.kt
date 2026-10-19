package top.strmaction.companion

import android.app.PictureInPictureParams
import android.content.Intent
import android.content.res.ColorStateList
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
import android.widget.SeekBar
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
import java.util.Locale
import java.util.concurrent.Executors

/**
 * v0.8 内置播放器：Media3 解码 + 5 秒心跳 + 无缝连播 + mpv 兜底。
 *
 * v0.9 播放控件：全部收拢到屏幕下方（选集 / 倍速 / 全屏），
 * 右侧中间提供锁定按钮；锁定后隐藏其它控件，只保留解锁入口。
 */
class PlayerActivity : AppCompatActivity() {

    companion object {
        const val EXTRA_ITEM_ID = "item_id"
        const val EXTRA_MODE = "mode"
        private const val TAG = "StrmActionPlayer"
        private const val SEEK_MAX = 1000
    }

    private lateinit var root: FrameLayout
    private lateinit var playerView: PlayerView
    private lateinit var controls: FrameLayout
    private lateinit var topBar: LinearLayout
    private lateinit var bottomBar: LinearLayout
    private lateinit var titleView: TextView
    private lateinit var timeView: TextView
    private lateinit var seekBar: SeekBar
    private lateinit var playPauseButton: TextView
    private lateinit var prevButton: TextView
    private lateinit var nextButton: TextView
    private lateinit var playlistButton: TextView
    private lateinit var speedButton: TextView
    private lateinit var fullscreenButton: TextView
    private lateinit var lockButton: TextView
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
    private var nextTicker: Runnable? = null

    private var controlsVisible = true
    private var locked = false
    private var fullscreen = false
    private var currentSpeed = 1f
    private var userSeeking = false

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

    private val progressTicker = object : Runnable {
        override fun run() {
            updateProgressUi()
            main.postDelayed(this, 500L)
        }
    }

    private val hideControls = Runnable {
        if (!locked && player?.isPlaying == true) setControlsVisible(false)
    }

    private val playbackListener = object : Player.Listener {
        override fun onPlaybackStateChanged(state: Int) {
            when (state) {
                Player.STATE_READY -> {
                    loadingView.visibility = View.GONE
                    updateProgressUi()
                    if (player?.isPlaying == true) {
                        startHeartbeat()
                        scheduleHide()
                    }
                }
                Player.STATE_ENDED -> onEnded()
                Player.STATE_BUFFERING -> {
                    // 只有首次准备/明显卡顿时才盖一层 loading，避免每次缓冲都闪
                    if ((player?.currentPosition ?: 0L) <= 0L) {
                        showLoading(getString(R.string.player_loading))
                    }
                }
            }
        }

        override fun onIsPlayingChanged(isPlaying: Boolean) {
            wasPlaying = isPlaying
            if (isPlaying) {
                if (playingSince == 0L) playingSince = SystemClock.elapsedRealtime()
                startHeartbeat()
                scheduleHide()
            } else {
                playingSince = 0L
                stopHeartbeat()
                flushProgressOnce()
                setControlsVisible(true)
            }
            updateProgressUi()
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
        fullscreen = Device.isTelevision(this)
        if (Device.isTelevision(this)) {
            requestedOrientation = android.content.pm.ActivityInfo.SCREEN_ORIENTATION_LANDSCAPE
            WindowCompat.setDecorFitsSystemWindows(window, false)
            hideSystemBars()
        } else {
            // 手机默认带系统栏；点「全屏」再隐藏系统栏并转横屏
            enterWindowedMode()
        }

        buildUi()
        setContentView(root)
        setControlsVisible(true)
        main.post(progressTicker)
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
            useController = false
            controllerAutoShow = false
            setShowBuffering(PlayerView.SHOW_BUFFERING_NEVER)
            setKeepContentOnPlayerReset(true)
            resizeMode = AspectRatioFrameLayout.RESIZE_MODE_FIT
            setBackgroundColor(Color.BLACK)
            setOnClickListener { onSurfaceTap() }
        }
        root.addView(playerView)

        controls = FrameLayout(this).apply {
            layoutParams = FrameLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.MATCH_PARENT,
            )
        }
        root.addView(controls)

        topBar = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER_VERTICAL
            setPadding(dp(16), dp(12), dp(16), dp(12))
            background = GradientDrawable(
                GradientDrawable.Orientation.TOP_BOTTOM,
                intArrayOf(0xCC000000.toInt(), 0x00000000),
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
            setPadding(dp(12), 0, dp(14), dp(2))
            isFocusable = true
            isClickable = true
            contentDescription = getString(R.string.common_back)
            setOnClickListener { handleBack() }
        }
        titleView = TextView(this).apply {
            text = getString(R.string.player_loading)
            setTextColor(Color.WHITE)
            textSize = 16f
            maxLines = 1
            ellipsize = android.text.TextUtils.TruncateAt.END
            layoutParams = LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f)
        }
        val menuButton = pillButton(getString(R.string.player_menu), 12f) { showMenu() }
        val pipButton = pillButton("画中画", 12f) { enterPip() }.apply {
            visibility = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O &&
                Device.isTouchDevice(this@PlayerActivity)
            ) {
                View.VISIBLE
            } else {
                View.GONE
            }
        }
        topBar.addView(backButton)
        topBar.addView(titleView)
        topBar.addView(pipButton)
        topBar.addView(menuButton)
        controls.addView(topBar)

        bottomBar = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(dp(16), dp(8), dp(16), dp(16))
            background = GradientDrawable(
                GradientDrawable.Orientation.BOTTOM_TOP,
                intArrayOf(0xE6000000.toInt(), 0xAA000000.toInt(), 0x00000000),
            )
            layoutParams = FrameLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.WRAP_CONTENT,
            ).apply { gravity = Gravity.BOTTOM }
        }

        timeView = TextView(this).apply {
            text = "00:00 / 00:00"
            setTextColor(Color.parseColor("#D6DCE6"))
            textSize = 11.5f
            gravity = Gravity.START
            setPadding(dp(2), 0, 0, dp(2))
            layoutParams = LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.WRAP_CONTENT,
            )
        }
        bottomBar.addView(timeView)

        seekBar = SeekBar(this).apply {
            max = SEEK_MAX
            progress = 0
            progressTintList = ColorStateList.valueOf(Color.parseColor("#E8B06A"))
            progressBackgroundTintList = ColorStateList.valueOf(0x55FFFFFF)
            thumbTintList = ColorStateList.valueOf(Color.parseColor("#E8B06A"))
            setPadding(0, 0, 0, 0)
            layoutParams = LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.WRAP_CONTENT,
            )
        }
        seekBar.setOnSeekBarChangeListener(object : SeekBar.OnSeekBarChangeListener {
            override fun onProgressChanged(bar: SeekBar?, progress: Int, fromUser: Boolean) {
                if (!fromUser) return
                userSeeking = true
                val duration = currentDuration()
                if (duration > 0) {
                    timeView.text = "${formatTime(duration * progress / SEEK_MAX)} / ${formatTime(duration)}"
                }
            }

            override fun onStartTrackingTouch(bar: SeekBar?) {
                userSeeking = true
                main.removeCallbacks(hideControls)
            }

            override fun onStopTrackingTouch(bar: SeekBar?) {
                val duration = currentDuration()
                if (bar != null && duration > 0) {
                    player?.seekTo(duration * bar.progress / SEEK_MAX)
                }
                userSeeking = false
                scheduleHide()
            }
        })
        bottomBar.addView(seekBar)

        val actionRow = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER_VERTICAL
            setPadding(0, dp(2), 0, 0)
            layoutParams = LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.WRAP_CONTENT,
            )
        }
        prevButton = actionButton("上一集", 10.5f, dp(46)) { playPrevEpisode() }
        playPauseButton = actionButton("暂停", 10.5f, dp(42)) { togglePlay() }
        nextButton = actionButton("下一集", 10.5f, dp(46)) { playNextEpisode() }
        actionRow.addView(prevButton)
        actionRow.addView(playPauseButton, rowParams(dp(42), dp(34)))
        actionRow.addView(nextButton)

        actionRow.addView(View(this), LinearLayout.LayoutParams(0, 1, 1f))

        playlistButton = actionButton("选集", 10.5f, dp(44)) { showPlaylist() }
        speedButton = actionButton(speedLabel(), 10.5f, dp(44)) { showSpeedMenu() }
        fullscreenButton = actionButton(fullscreenLabel(), 10.5f, dp(64)) {
            toggleFullscreen()
        }
        actionRow.addView(playlistButton)
        actionRow.addView(speedButton)
        actionRow.addView(fullscreenButton)
        bottomBar.addView(actionRow)
        controls.addView(bottomBar)

        lockButton = TextView(this).apply {
            text = getString(R.string.player_lock)
            setTextColor(Color.WHITE)
            textSize = 12f
            gravity = Gravity.CENTER
            background = rounded(0x99000000.toInt(), 999f)
            setPadding(dp(12), dp(10), dp(12), dp(10))
            isFocusable = true
            isClickable = true
            contentDescription = getString(R.string.player_lock_hint)
            layoutParams = FrameLayout.LayoutParams(
                ViewGroup.LayoutParams.WRAP_CONTENT,
                ViewGroup.LayoutParams.WRAP_CONTENT,
            ).apply {
                gravity = Gravity.END or Gravity.CENTER_VERTICAL
                rightMargin = dp(10)
            }
            setOnClickListener { toggleLock() }
        }
        root.addView(lockButton)

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
                indeterminateTintList = ColorStateList.valueOf(Color.parseColor("#E8B06A"))
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

    private fun pillButton(label: String, size: Float, action: () -> Unit): TextView =
        TextView(this).apply {
            text = label
            setTextColor(Color.WHITE)
            textSize = size
            gravity = Gravity.CENTER
            background = rounded(0x33FFFFFF, 999f)
            setPadding(dp(14), dp(7), dp(14), dp(7))
            isFocusable = true
            isClickable = true
            setOnClickListener { action() }
        }

    private fun actionButton(label: String, size: Float, width: Int, action: () -> Unit): TextView =
        TextView(this).apply {
            text = label
            setTextColor(Color.WHITE)
            textSize = size
            gravity = Gravity.CENTER
            background = rounded(0x33FFFFFF, 10f)
            setPadding(dp(6), dp(8), dp(6), dp(8))
            isFocusable = true
            isClickable = true
            layoutParams = rowParams(width, dp(34))
            setOnClickListener { action() }
        }

    private fun rowParams(width: Int, height: Int): LinearLayout.LayoutParams =
        LinearLayout.LayoutParams(width, height).apply {
            leftMargin = dp(3)
            rightMargin = dp(3)
        }

    private fun onSurfaceTap() {
        if (locked) {
            // 锁定状态下只保留右侧解锁按钮
            lockButton.visibility = View.VISIBLE
            return
        }
        setControlsVisible(!controlsVisible)
    }

    private fun setControlsVisible(visible: Boolean) {
        controlsVisible = visible
        if (locked) {
            controls.visibility = View.GONE
            lockButton.visibility = View.VISIBLE
            return
        }
        controls.visibility = if (visible) View.VISIBLE else View.GONE
        lockButton.visibility = if (visible) View.VISIBLE else View.GONE
        if (visible) {
            updateProgressUi()
            scheduleHide()
        } else {
            main.removeCallbacks(hideControls)
        }
    }

    private fun scheduleHide() {
        main.removeCallbacks(hideControls)
        if (!locked && controlsVisible && player?.isPlaying == true) {
            main.postDelayed(hideControls, 4500L)
        }
    }

    private fun toggleLock() {
        locked = !locked
        if (locked) {
            lockButton.text = getString(R.string.player_unlock)
            lockButton.contentDescription = getString(R.string.player_unlock_hint)
            controls.visibility = View.GONE
            lockButton.visibility = View.VISIBLE
            toast(getString(R.string.player_locked))
        } else {
            lockButton.text = getString(R.string.player_lock)
            lockButton.contentDescription = getString(R.string.player_lock_hint)
            setControlsVisible(true)
            toast(getString(R.string.player_unlocked))
        }
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
                Entry(getString(R.string.player_menu_next) + suffix) { playNextEpisode() },
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
        val speeds = floatArrayOf(0.5f, 0.75f, 1f, 1.25f, 1.5f, 2f, 3f)
        val labels = speeds.map { speed ->
            if (speed == 1f) "1.0x（正常）" else "${trimSpeed(speed)}x"
        }.toTypedArray()
        val checked = speeds.indexOfFirst { it == currentSpeed }.coerceAtLeast(0)
        AlertDialog.Builder(this)
            .setTitle(R.string.player_menu_speed)
            .setSingleChoiceItems(labels, checked) { dialog, which ->
                applySpeed(speeds[which])
                dialog.dismiss()
            }
            .setNegativeButton(android.R.string.cancel, null)
            .show()
    }

    private fun applySpeed(speed: Float) {
        currentSpeed = speed
        player?.setPlaybackSpeed(speed)
        speedButton.text = speedLabel()
        toast(getString(R.string.player_speed_toast, "${trimSpeed(speed)}x"))
        scheduleHide()
    }

    private fun trimSpeed(speed: Float): String =
        if (speed % 1f == 0f) String.format(Locale.US, "%.1f", speed)
        else String.format(Locale.US, "%.2f", speed).trimEnd('0').trimEnd('.')

    private fun speedLabel(): String =
        if (currentSpeed == 1f) "倍速" else "${trimSpeed(currentSpeed)}x"

    private fun showPlaylist() {
        val playInfo = info ?: return
        val entries = playInfo.playlist
        if (entries.isEmpty()) {
            toast(getString(R.string.player_no_playlist))
            return
        }
        val labels = entries.map { entry ->
            buildString {
                append(entry.displayLabel())
                if (entry.watched) append("  ✓")
                if (entry.current) append("  ▶")
            }
        }.toTypedArray()
        val checked = entries.indexOfFirst { it.current || it.id == currentItemId }
        AlertDialog.Builder(this)
            .setTitle(
                getString(
                    R.string.player_playlist_title,
                    playInfo.seriesTitle ?: playInfo.title,
                ),
            )
            .setSingleChoiceItems(labels, checked) { dialog, which ->
                dialog.dismiss()
                val entry = entries.getOrNull(which) ?: return@setSingleChoiceItems
                if (entry.id != currentItemId) switchToEpisode(entry.id)
                else setControlsVisible(true)
            }
            .setNegativeButton(android.R.string.cancel, null)
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
        exo.setPlaybackSpeed(currentSpeed)
        exo.setMediaItem(mediaItem, startMs.coerceAtLeast(0L))
        exo.prepare()
        exo.playWhenReady = true
        exo.play()
        updateProgressUi()
        updateEpisodeButtons()
        setControlsVisible(true)
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

    private fun playNextEpisode() {
        val nextId = info?.nextItemId ?: run {
            toast(getString(R.string.player_no_next))
            return
        }
        switchToEpisode(nextId)
    }

    private fun playPrevEpisode() {
        val entries = info?.playlist.orEmpty()
        val index = entries.indexOfFirst { it.id == currentItemId }
        val prev = entries.getOrNull(index - 1) ?: run {
            toast(getString(R.string.player_no_prev))
            return
        }
        switchToEpisode(prev.id)
    }

    private fun switchToEpisode(itemId: Int) {
        if (advancing || itemId == currentItemId) return
        advancing = true
        flushProgressOnce()
        showLoading(getString(R.string.player_loading))
        setControlsVisible(false)
        executor.execute {
            val result = runCatching { PlayApi.fetch(this, itemId, "builtin") }
            runOnUiThread {
                if (isFinishing || isDestroyed) return@runOnUiThread
                result.onSuccess { next -> playItem(next, 0L) }
                    .onFailure {
                        advancing = false
                        loadingView.visibility = View.GONE
                        toast(it.message ?: getString(R.string.player_error_title))
                        setControlsVisible(true)
                    }
            }
        }
    }

    // ------------------------------------------------------------------
    // 进度条 / 全屏 / 画中画
    // ------------------------------------------------------------------

    private fun currentDuration(): Long {
        val exo = player ?: return info?.durationMs ?: 0L
        return exo.duration.takeIf { it != C.TIME_UNSET && it > 0 }
            ?: info?.durationMs
            ?: 0L
    }

    private fun updateProgressUi() {
        val exo = player ?: return
        val duration = currentDuration()
        if (!userSeeking) {
            if (duration > 0) {
                val progress = (exo.currentPosition.coerceAtLeast(0L) * SEEK_MAX / duration)
                    .toInt()
                    .coerceIn(0, SEEK_MAX)
                seekBar.progress = progress
            }
            timeView.text = "${formatTime(exo.currentPosition)} / ${formatTime(duration)}"
        }
        playPauseButton.text =
            if (exo.isPlaying) getString(R.string.player_pause) else getString(R.string.player_play)
        updateEpisodeButtons()
    }

    private fun updateEpisodeButtons() {
        val entries = info?.playlist.orEmpty()
        val index = entries.indexOfFirst { it.id == currentItemId }
        prevButton.isEnabled = index > 0
        prevButton.alpha = if (prevButton.isEnabled) 1f else 0.4f
        nextButton.isEnabled = info?.nextItemId != null
        nextButton.alpha = if (nextButton.isEnabled) 1f else 0.4f
        playlistButton.isEnabled = entries.isNotEmpty()
        playlistButton.alpha = if (playlistButton.isEnabled) 1f else 0.4f
    }

    private fun formatTime(ms: Long): String {
        val total = (ms.coerceAtLeast(0L) / 1000L).toInt()
        val hours = total / 3600
        val minutes = (total % 3600) / 60
        val seconds = total % 60
        return if (hours > 0) {
            String.format(Locale.US, "%d:%02d:%02d", hours, minutes, seconds)
        } else {
            String.format(Locale.US, "%02d:%02d", minutes, seconds)
        }
    }

    private fun toggleFullscreen() {
        fullscreen = !fullscreen
        if (fullscreen) {
            window.addFlags(WindowManager.LayoutParams.FLAG_FULLSCREEN)
            WindowCompat.setDecorFitsSystemWindows(window, false)
            hideSystemBars()
            requestedOrientation = if (Device.isTelevision(this)) {
                android.content.pm.ActivityInfo.SCREEN_ORIENTATION_LANDSCAPE
            } else {
                android.content.pm.ActivityInfo.SCREEN_ORIENTATION_SENSOR_LANDSCAPE
            }
        } else {
            enterWindowedMode()
        }
        fullscreenButton.text = fullscreenLabel()
        setControlsVisible(true)
    }

    private fun fullscreenLabel(): String =
        if (fullscreen) getString(R.string.player_exit_fullscreen)
        else getString(R.string.player_fullscreen)

    private fun enterWindowedMode() {
        fullscreen = false
        window.clearFlags(WindowManager.LayoutParams.FLAG_FULLSCREEN)
        WindowCompat.setDecorFitsSystemWindows(window, true)
        showSystemBars()
        if (this::fullscreenButton.isInitialized) {
            fullscreenButton.text = fullscreenLabel()
        }
        requestedOrientation =
            android.content.pm.ActivityInfo.SCREEN_ORIENTATION_UNSPECIFIED
        @Suppress("DEPRECATION")
        run {
            window.statusBarColor = Color.BLACK
            window.navigationBarColor = Color.BLACK
        }
    }

    private fun hideSystemBars() {
        WindowInsetsControllerCompat(window, window.decorView).apply {
            hide(WindowInsetsCompat.Type.systemBars())
            systemBarsBehavior =
                WindowInsetsControllerCompat.BEHAVIOR_SHOW_TRANSIENT_BARS_BY_SWIPE
        }
    }

    private fun showSystemBars() {
        WindowInsetsControllerCompat(window, window.decorView)
            .show(WindowInsetsCompat.Type.systemBars())
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
        if (isInPictureInPictureMode) {
            controls.visibility = View.GONE
            lockButton.visibility = View.GONE
        } else {
            setControlsVisible(true)
            if (fullscreen) hideSystemBars() else showSystemBars()
        }
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
                    playNextEpisode()
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
                    handleBack()
                    return true
                }
            }
        }
        return super.dispatchKeyEvent(event)
    }

    /** 手势返回 / 遥控器返回：先退全屏、解锁、收起控件，最后才退出。 */
    override fun onBackPressed() {
        handleBack()
    }

    private fun handleBack() {
        when {
            locked -> toggleLock()
            fullscreen -> toggleFullscreen()
            controlsVisible -> setControlsVisible(false)
            else -> finishWithResult()
        }
    }

    private fun togglePlay() {
        val exo = player ?: return
        if (exo.isPlaying) exo.pause() else exo.play()
        setControlsVisible(true)
    }

    private fun seekBy(deltaMs: Long) {
        val exo = player ?: return
        val duration = exo.duration.takeIf { it != C.TIME_UNSET && it > 0 }
        val target = (exo.currentPosition + deltaMs).coerceAtLeast(0L)
        exo.seekTo(if (duration != null) target.coerceAtMost(duration) else target)
        setControlsVisible(true)
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
