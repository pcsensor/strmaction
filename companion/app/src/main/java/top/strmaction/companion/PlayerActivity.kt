package top.strmaction.companion

import android.app.PictureInPictureParams
import android.content.Context
import android.content.Intent
import android.content.res.ColorStateList
import android.content.res.Configuration
import android.graphics.Color
import android.graphics.drawable.GradientDrawable
import android.media.AudioManager
import android.net.Uri
import android.provider.Settings
import android.os.Build
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.os.SystemClock
import android.util.Log
import android.util.Rational
import android.view.GestureDetector
import android.view.Gravity
import android.view.HapticFeedbackConstants
import android.view.KeyEvent
import android.view.MotionEvent
import android.view.View
import android.view.ViewGroup
import android.view.WindowManager
import android.widget.FrameLayout
import android.widget.ImageView
import android.widget.LinearLayout
import android.widget.ProgressBar
import android.widget.ScrollView
import android.widget.SeekBar
import android.widget.TextView
import android.widget.Toast
import androidx.annotation.DrawableRes
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AlertDialog
import androidx.appcompat.app.AppCompatActivity
import top.strmaction.companion.player.BufferedSeekBar
import top.strmaction.companion.player.PlayerDrawer
import top.strmaction.companion.player.PlayerSpeedHelper
import top.strmaction.companion.player.PlayerTrackHelper
import top.strmaction.companion.player.dp
import top.strmaction.companion.player.formatTime
import top.strmaction.companion.player.rounded
import kotlin.math.abs
import kotlin.math.min
import androidx.core.view.WindowCompat
import androidx.core.view.WindowInsetsCompat
import androidx.core.view.WindowInsetsControllerCompat
import androidx.media3.common.C
import androidx.media3.common.MediaItem
import androidx.media3.common.PlaybackException
import androidx.media3.common.Player
import androidx.media3.common.Tracks
import androidx.media3.common.util.UnstableApi
import androidx.media3.datasource.DataSource
import androidx.media3.datasource.DataSpec
import androidx.media3.datasource.DefaultDataSource
import androidx.media3.datasource.TransferListener
import androidx.media3.datasource.cache.CacheDataSink
import androidx.media3.datasource.cache.CacheDataSource
import androidx.media3.datasource.okhttp.OkHttpDataSource
import androidx.media3.exoplayer.DefaultLoadControl
import androidx.media3.exoplayer.DefaultRenderersFactory
import androidx.media3.exoplayer.ExoPlayer
import androidx.media3.exoplayer.source.DefaultMediaSourceFactory
import androidx.media3.ui.AspectRatioFrameLayout
import androidx.media3.ui.PlayerView
import java.util.Locale
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit
import okhttp3.OkHttpClient
import okhttp3.Protocol

/**
 * v0.8 内置播放器：Media3 解码 + 5 秒心跳 + 无缝连播 + mpv 兜底。
 *
 * v0.9 播放控件：全部收拢到屏幕下方（选集 / 倍速 / 全屏），
 * 右侧中间提供锁定按钮；锁定后隐藏其它控件，只保留解锁入口。
 */
@androidx.annotation.OptIn(UnstableApi::class)
class PlayerActivity : AppCompatActivity() {

    companion object {
        const val EXTRA_ITEM_ID = "item_id"
        const val EXTRA_MODE = "mode"
        private const val TAG = "StrmActionPlayer"
        private const val SEEK_MAX = 1000
        /** 落盘按 5MB 分片，减少小文件数量与写放大。 */
        private const val CACHE_FRAGMENT_SIZE = 5L * 1024L * 1024L
    }

    private lateinit var root: FrameLayout
    private lateinit var playerView: PlayerView
    private lateinit var controls: FrameLayout
    private lateinit var topBar: LinearLayout
    private lateinit var bottomBar: LinearLayout
    private lateinit var titleView: TextView
    private lateinit var timeView: TextView
    private lateinit var speedView: TextView
    private lateinit var seekBar: BufferedSeekBar
    private lateinit var backButton: ImageView
    private lateinit var pipButton: ImageView
    private lateinit var menuButton: ImageView
    private lateinit var centerPlayButton: ImageView
    private lateinit var playPauseButton: ImageView
    private lateinit var prevButton: ImageView
    private lateinit var nextButton: ImageView
    private lateinit var playlistButton: TextView
    private lateinit var speedButton: TextView
    private lateinit var fullscreenButton: ImageView
    private lateinit var lockButton: ImageView
    private lateinit var fastForwardBadge: TextView
    private lateinit var seekFeedbackBadge: TextView
    private lateinit var loadingView: LinearLayout
    private lateinit var loadingText: TextView
    private lateinit var bufferingView: LinearLayout
    private lateinit var drawer: PlayerDrawer

    private enum class GestureMode {
        NONE,
        BRIGHTNESS,
        VOLUME,
        PROGRESS,
    }
    private var activeGesture = GestureMode.NONE
    private var gestureSuppressed = false
    private var gesturePreviewActive = false
    private var gestureStartX = 0f
    private var gestureStartY = 0f
    private var gestureStartProgressMs = 0L
    private var gestureTargetProgressMs = 0L
    private var gestureStartBrightness = 0.5f
    private var gestureStartVolume = 0

    private val audioManager by lazy {
        getSystemService(Context.AUDIO_SERVICE) as AudioManager
    }

    private var player: ExoPlayer? = null
    private var playerHeadersKey: String? = null
    private var info: PlayInfo? = null
    private var currentItemId: Int = 0
    private var loading = false
    private var advancing = false
    private var playbackAttempt = 0
    private var wasPlaying = false
    private var playingSince = 0L
    private var nextTicker: Runnable? = null

    private var controlsVisible = true
    private var locked = false
    private var fullscreen = false
    private var currentSpeed = 1f
    private var longPressSpeed = 2.0f
    private var speedBeforeLongPress: Float? = null
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
    private var currentPlayUri: Uri? = null
    private var resolvedMediaUri: Uri? = null

    /** 切集后要删除的上一集缓存 key；等新片源 READY 再删，避免打断旧数据源。 */
    private var pendingCacheRemoval: String? = null

    /** 后台磁盘预取：内存缓冲之外提前把后续内容拉到磁盘。 */
    private val prefetcher = PlaybackPrefetcher { PlaybackDiskCache.current() }

    /** 预取专用的数据源工厂（OkHttp + CacheDataSource，独立于播放器那条链）。 */
    private var prefetchSourceFactory: DataSource.Factory? = null

    /** 拖动/跳转后等待播放器追上目标：期间进度条钉在目标值，避免回弹闪动。 */
    private var pendingSeekProgress = -1
    private var pendingSeekAtMs = 0L

    /**
     * 当前视频已确认缓存过的区间（进度单位，升序不重叠）。
     * 只做并集、从不删减，所以进度条上的缓存线只增不减，不会因为 seek 闪跳。
     */
    private var cachedRanges: List<IntRange> = emptyList()

    private val progressTicker = object : Runnable {
        override fun run() {
            updateProgressUi()
            updatePrefetcherState()
            updateSpeedUi()
            main.postDelayed(this, 500L)
        }
    }

    private val hideControls = Runnable {
        if (!locked && player?.isPlaying == true) setControlsVisible(false)
    }

    private val hideLockButton = Runnable {
        if (locked) {
            lockButton.animate().alpha(0f).setDuration(250).withEndAction {
                lockButton.visibility = View.GONE
                lockButton.alpha = 1f
            }.start()
        }
    }

    private fun scheduleLockHide(delayMs: Long = 3000L) {
        main.removeCallbacks(hideLockButton)
        if (locked) {
            main.postDelayed(hideLockButton, delayMs)
        }
    }

    private fun showLockButton() {
        main.removeCallbacks(hideLockButton)
        lockButton.animate().cancel()
        lockButton.alpha = 1f
        lockButton.visibility = View.VISIBLE
        scheduleLockHide(3000L)
    }

    private fun hideLockButtonImmediately() {
        main.removeCallbacks(hideLockButton)
        lockButton.animate().cancel()
        lockButton.visibility = View.GONE
        lockButton.alpha = 1f
    }

    private val playbackListener = object : Player.Listener {
        override fun onPlaybackStateChanged(state: Int) {
            when (state) {
                Player.STATE_READY -> {
                    loadingView.visibility = View.GONE
                    bufferingView.visibility = View.GONE
                    updateProgressUi()
                    flushCacheRemoval()
                    if (player?.isPlaying == true) {
                        startHeartbeat()
                        scheduleHide()
                    }
                }
                Player.STATE_ENDED -> onEnded()
                Player.STATE_BUFFERING -> {
                    if ((player?.currentPosition ?: 0L) <= 0L) {
                        showLoading(getString(R.string.player_loading))
                    } else {
                        bufferingView.visibility = View.VISIBLE
                        centerPlayButton.visibility = View.GONE
                    }
                }
            }
        }

        override fun onIsPlayingChanged(isPlaying: Boolean) {
            wasPlaying = isPlaying
            if (isPlaying) {
                if (playingSince == 0L) playingSince = SystemClock.elapsedRealtime()
                bufferingView.visibility = View.GONE
                startHeartbeat()
                scheduleHide()
            } else {
                playingSince = 0L
                stopHeartbeat()
                flushProgressOnce()
                val isBuffering = player?.playbackState == Player.STATE_BUFFERING
                if (!isBuffering) {
                    setControlsVisible(true)
                }
            }
            updateProgressUi()
        }

        override fun onPlayerError(error: PlaybackException) {
            Log.e(TAG, "playback error: ${error.errorCodeName}", error)
            stopHeartbeat()
            if (playbackAttempt < 2 && info != null) {
                val next = playbackAttempt + 1
                toast(getString(R.string.player_compat_retry))
                val playInfo = info!!
                val resumePos = player?.currentPosition?.takeIf { it > 0 } ?: playInfo.resumeMs
                main.post {
                    playItem(playInfo, resumePos, attempt = next)
                }
            } else {
                onPlaybackFailed(error)
            }
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

        longPressSpeed = getSharedPreferences("player_prefs", MODE_PRIVATE)
            .getFloat("long_press_speed", 2.0f)

        buildUi()
        setContentView(root)
        setControlsVisible(true)
        prefetcher.start()
        NetworkSpeedMeter.reset()
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
        }
        setupPlayerGestures(playerView)
        root.addView(playerView)

        controls = FrameLayout(this).apply {
            layoutParams = FrameLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.MATCH_PARENT,
            )
        }
        root.addView(controls)

        // 顶部操作栏
        topBar = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER_VERTICAL
            setPadding(dp(12), dp(8), dp(12), dp(8))
            background = GradientDrawable(
                GradientDrawable.Orientation.TOP_BOTTOM,
                intArrayOf(0xCC000000.toInt(), 0x00000000),
            )
            layoutParams = FrameLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.WRAP_CONTENT,
            ).apply { gravity = Gravity.TOP }
        }

        backButton = iconButton(R.drawable.ic_back, getString(R.string.common_back), dp(40), dp(8)) {
            if (isDrawerOpen()) {
                closeDrawer()
            } else {
                finishWithResult()
            }
        }
        topBar.addView(backButton)

        titleView = TextView(this).apply {
            text = getString(R.string.player_loading)
            setTextColor(Color.WHITE)
            textSize = 15f
            maxLines = 1
            ellipsize = android.text.TextUtils.TruncateAt.END
            setPadding(dp(8), 0, dp(8), 0)
            layoutParams = LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f)
        }
        topBar.addView(titleView)

        pipButton = iconButton(R.drawable.ic_pip, "画中画", dp(40), dp(9)) {
            enterPip()
        }.apply {
            visibility = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O &&
                Device.isTouchDevice(this@PlayerActivity)
            ) {
                View.VISIBLE
            } else {
                View.GONE
            }
        }
        topBar.addView(pipButton)

        menuButton = iconButton(R.drawable.ic_more, getString(R.string.player_menu), dp(40), dp(8)) {
            showMenu()
        }
        topBar.addView(menuButton)
        controls.addView(topBar)

        // 屏幕中心大播放/暂停按钮
        centerPlayButton = iconButton(R.drawable.ic_play, getString(R.string.player_play), dp(56), dp(14)) {
            togglePlay()
        }.apply {
            background = rounded(0x55000000, 999f)
            layoutParams = FrameLayout.LayoutParams(dp(56), dp(56)).apply {
                gravity = Gravity.CENTER
            }
        }
        controls.addView(centerPlayButton)

        // 屏幕中心缓冲加载指示器
        bufferingView = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            gravity = Gravity.CENTER
            visibility = View.GONE
            background = rounded(0x88000000.toInt(), 16f)
            setPadding(dp(22), dp(16), dp(22), dp(16))
            layoutParams = FrameLayout.LayoutParams(
                ViewGroup.LayoutParams.WRAP_CONTENT,
                ViewGroup.LayoutParams.WRAP_CONTENT,
            ).apply {
                gravity = Gravity.CENTER
            }
            addView(
                ProgressBar(this@PlayerActivity).apply {
                    indeterminateTintList = ColorStateList.valueOf(Color.parseColor("#E8B06A"))
                    layoutParams = LinearLayout.LayoutParams(dp(44), dp(44))
                }
            )
            addView(
                TextView(this@PlayerActivity).apply {
                    text = "正在缓冲..."
                    setTextColor(Color.parseColor("#E2E8F0"))
                    textSize = 13f
                    gravity = Gravity.CENTER
                    setPadding(0, dp(8), 0, 0)
                }
            )
        }
        root.addView(bufferingView)

        // 浮层：长按倍速提示徽标
        fastForwardBadge = TextView(this).apply {
            text = "▶▶ ${trimSpeed(longPressSpeed)}x 快速播放中"
            setTextColor(Color.WHITE)
            textSize = 13f
            typeface = android.graphics.Typeface.DEFAULT_BOLD
            gravity = Gravity.CENTER
            background = rounded(0xB3181818.toInt(), 999f)
            setPadding(dp(16), dp(8), dp(16), dp(8))
            visibility = View.GONE
            layoutParams = FrameLayout.LayoutParams(
                ViewGroup.LayoutParams.WRAP_CONTENT,
                ViewGroup.LayoutParams.WRAP_CONTENT,
            ).apply {
                gravity = Gravity.TOP or Gravity.CENTER_HORIZONTAL
                topMargin = dp(56)
            }
        }
        root.addView(fastForwardBadge)

        // 浮层：双击快进快退反馈徽标
        seekFeedbackBadge = TextView(this).apply {
            setTextColor(Color.WHITE)
            textSize = 14f
            gravity = Gravity.CENTER
            background = rounded(0xCC000000.toInt(), 999f)
            setPadding(dp(18), dp(10), dp(18), dp(10))
            visibility = View.GONE
            layoutParams = FrameLayout.LayoutParams(
                ViewGroup.LayoutParams.WRAP_CONTENT,
                ViewGroup.LayoutParams.WRAP_CONTENT,
            ).apply {
                gravity = Gravity.CENTER
            }
        }
        root.addView(seekFeedbackBadge)

        // 右侧锁屏悬浮按钮
        lockButton = iconButton(R.drawable.ic_unlock, getString(R.string.player_lock), dp(40), dp(9)) {
            toggleLock()
        }.apply {
            background = rounded(0x66000000, 999f)
            layoutParams = FrameLayout.LayoutParams(dp(40), dp(40)).apply {
                gravity = Gravity.END or Gravity.CENTER_VERTICAL
                rightMargin = dp(16)
            }
        }
        root.addView(lockButton)

        buildBottomBar()

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

        initDrawer()
    }

    /** 构建底部控制栏；横竖屏切换时整体重建，保证按钮不会被挤出屏幕。 */
    private fun buildBottomBar() {
        // 竖屏手机宽度不够，把操作按钮拆成两行，避免右侧按钮被裁到屏幕外。
        val narrow = resources.configuration.screenWidthDp < 600

        // 底部控制栏
        bottomBar = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            val hPad = if (narrow) dp(8) else dp(12)
            setPadding(hPad, dp(8), hPad, if (narrow) dp(10) else dp(12))
            background = GradientDrawable(
                GradientDrawable.Orientation.BOTTOM_TOP,
                intArrayOf(0xE6000000.toInt(), 0xAA000000.toInt(), 0x00000000),
            )
            layoutParams = FrameLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.WRAP_CONTENT,
            ).apply { gravity = Gravity.BOTTOM }
        }

        // 进度条：8dp 轨道 + 中间细线表示已缓存；触摸区 32dp。
        seekBar = BufferedSeekBar(this).apply {
            max = SEEK_MAX
            progress = 0
            layoutParams = LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                dp(32),
            )
        }
        seekBar.setOnSeekBarChangeListener(object : SeekBar.OnSeekBarChangeListener {
            override fun onProgressChanged(bar: SeekBar?, progress: Int, fromUser: Boolean) {
                if (!fromUser) return
                userSeeking = true
                val duration = currentDuration()
                if (duration > 0) {
                    previewSeekPosition(duration * progress / SEEK_MAX)
                }
            }

            override fun onStartTrackingTouch(bar: SeekBar?) {
                userSeeking = true
                main.removeCallbacks(hideControls)
            }

            override fun onStopTrackingTouch(bar: SeekBar?) {
                val duration = currentDuration()
                if (bar != null && duration > 0) {
                    markPendingSeek(bar.progress)
                    player?.seekTo(duration * bar.progress / SEEK_MAX)
                }
                userSeeking = false
                scheduleHide()
            }
        })
        bottomBar.addView(seekBar)

        // 底部操作按钮行
        val actionRow = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER_VERTICAL
            setPadding(dp(4), dp(4), dp(4), 0)
            layoutParams = LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.WRAP_CONTENT,
            )
        }

        playPauseButton = iconButton(R.drawable.ic_play, getString(R.string.player_play), dp(36), dp(6)) {
            togglePlay()
        }
        prevButton = iconButton(R.drawable.ic_prev, getString(R.string.player_prev), dp(36), dp(7)) {
            playPrevEpisode()
        }
        nextButton = iconButton(R.drawable.ic_next, getString(R.string.player_next), dp(36), dp(7)) {
            playNextEpisode()
        }

        actionRow.addView(playPauseButton)
        actionRow.addView(prevButton)
        actionRow.addView(nextButton)

        timeView = TextView(this).apply {
            text = "00:00 / 00:00"
            setTextColor(Color.parseColor("#D6DCE6"))
            textSize = if (narrow) 11.5f else 12f
            setPadding(dp(8), 0, dp(4), 0)
            layoutParams = LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.WRAP_CONTENT,
                ViewGroup.LayoutParams.WRAP_CONTENT,
            )
        }
        actionRow.addView(timeView)

        // 实时网速：只统计真正走网络的流量（命中磁盘缓存时归零）。
        speedView = TextView(this).apply {
            text = "0 KB/s"
            setTextColor(Color.parseColor("#8C93A3"))
            textSize = 11f
            includeFontPadding = false
            gravity = Gravity.START
            minWidth = dp(if (narrow) 52 else 62)
            setPadding(dp(8), 0, 0, 0)
            layoutParams = LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.WRAP_CONTENT,
                ViewGroup.LayoutParams.WRAP_CONTENT,
            )
        }
        actionRow.addView(speedView)

        // 弹性占位，将右侧功能区推至最右
        actionRow.addView(View(this), LinearLayout.LayoutParams(0, 1, 1f))

        playlistButton = pillButton(getString(R.string.player_playlist), 11.5f) { showPlaylist() }
        speedButton = pillButton(speedLabel(), 11.5f) { showSpeedMenu() }
        fullscreenButton = iconButton(
            if (fullscreen) R.drawable.ic_fullscreen_exit else R.drawable.ic_fullscreen,
            fullscreenLabel(),
            dp(36),
            dp(7),
        ) {
            toggleFullscreen()
        }

        if (narrow) {
            // 窄屏：第一行只放播放/选集/时间/网速/全屏，选集与倍速放到第二行，
            // 否则一行排不下会把全屏按钮推到屏幕外。
            actionRow.addView(fullscreenButton)
            bottomBar.addView(actionRow)

            val optionRow = LinearLayout(this).apply {
                orientation = LinearLayout.HORIZONTAL
                gravity = Gravity.CENTER_VERTICAL
                setPadding(dp(4), dp(2), dp(4), 0)
                layoutParams = LinearLayout.LayoutParams(
                    ViewGroup.LayoutParams.MATCH_PARENT,
                    ViewGroup.LayoutParams.WRAP_CONTENT,
                )
                addView(View(this@PlayerActivity), LinearLayout.LayoutParams(0, 1, 1f))
                addView(playlistButton)
                addView(speedButton)
            }
            bottomBar.addView(optionRow)
        } else {
            actionRow.addView(playlistButton)
            actionRow.addView(speedButton)
            actionRow.addView(fullscreenButton)
            bottomBar.addView(actionRow)
        }

        controls.addView(bottomBar)
    }

    private fun initDrawer() {
        drawer = PlayerDrawer(this, root) { isOpening ->
            if (isOpening) {
                main.removeCallbacks(hideControls)
                setControlsVisible(false)
            }
        }
    }

    private fun isDrawerOpen(): Boolean =
        this::drawer.isInitialized && drawer.isOpen()

    private fun openDrawer(
        title: String,
        subtitle: String? = null,
        onBack: (() -> Unit)? = null,
        setupBody: (FrameLayout) -> Unit,
    ) {
        main.removeCallbacks(hideControls)
        setControlsVisible(false)
        drawer.open(title, subtitle, onBack, setupBody)
    }

    private fun closeDrawer() {
        if (this::drawer.isInitialized) {
            drawer.close()
        }
    }

    /** 抽屉 body 本身固定高度；菜单必须自己套 ScrollView 才能上下滑动。 */
    private fun addScrollableDrawerContent(container: FrameLayout, content: View) {
        val scroll = ScrollView(this).apply {
            layoutParams = FrameLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.MATCH_PARENT,
            )
            isFillViewport = true
            isVerticalScrollBarEnabled = false
            overScrollMode = View.OVER_SCROLL_NEVER
            clipToPadding = false
        }
        content.layoutParams = FrameLayout.LayoutParams(
            ViewGroup.LayoutParams.MATCH_PARENT,
            ViewGroup.LayoutParams.WRAP_CONTENT,
        )
        scroll.addView(content)
        container.addView(scroll)
    }

    private fun resetGestureState() {
        activeGesture = GestureMode.NONE
        gestureSuppressed = false
        gesturePreviewActive = false
    }

    private fun setupPlayerGestures(view: View) {
        val gestureDetector = GestureDetector(this, object : GestureDetector.SimpleOnGestureListener() {
            override fun onDown(e: MotionEvent): Boolean {
                gestureStartX = e.x
                gestureStartY = e.y
                resetGestureState()
                gestureStartProgressMs = player?.currentPosition ?: 0L
                gestureTargetProgressMs = gestureStartProgressMs
                gestureStartBrightness = getCurrentBrightness()
                gestureStartVolume = getAudioVolume()
                if (controlsVisible) {
                    // 手势期间不要被 4.5 秒自动隐藏打断
                    main.removeCallbacks(hideControls)
                }
                return true
            }

            override fun onSingleTapConfirmed(e: MotionEvent): Boolean {
                onSurfaceTap()
                return true
            }

            override fun onDoubleTap(e: MotionEvent): Boolean {
                if (locked) return false
                val width = view.width
                if (width <= 0) return false
                val x = e.x
                when {
                    x < width * 0.35f -> {
                        seekRelative(-10_000L)
                        showSeekFeedback("⏪ 快退 10 秒")
                    }
                    x > width * 0.65f -> {
                        seekRelative(10_000L)
                        showSeekFeedback("⏩ 快进 10 秒")
                    }
                    else -> togglePlay()
                }
                return true
            }

            override fun onLongPress(e: MotionEvent) {
                if (locked) return
                if (gestureSuppressed) return
                if (activeGesture != GestureMode.NONE) return
                if (player?.isPlaying == true) {
                    view.performHapticFeedback(HapticFeedbackConstants.LONG_PRESS)
                    startLongPressSpeed()
                }
            }

            override fun onScroll(
                e1: MotionEvent?,
                e2: MotionEvent,
                distanceX: Float,
                distanceY: Float,
            ): Boolean {
                if (locked) return false
                if (speedBeforeLongPress != null) return false
                if (gestureSuppressed) return true
                val width = view.width.toFloat()
                val height = view.height.toFloat()
                if (width <= 0f || height <= 0f) return false

                val startX = e1?.x ?: gestureStartX
                val startY = e1?.y ?: gestureStartY
                val deltaX = e2.x - startX
                val deltaY = e2.y - startY

                if (activeGesture == GestureMode.NONE) {
                    val absDx = abs(deltaX)
                    val absDy = abs(deltaY)
                    val touchSlop = dp(14).toFloat()
                    if (absDx < touchSlop && absDy < touchSlop) {
                        return false
                    }
                    if (absDx > absDy) {
                        activeGesture = GestureMode.PROGRESS
                        gesturePreviewActive = true
                        main.removeCallbacks(hideControls)
                    } else if (controlsVisible) {
                        // 控件已呼出时，纵向滑动不再调节亮度/音量。
                        gestureSuppressed = true
                        return true
                    } else {
                        activeGesture = if (startX < width * 0.5f) {
                            GestureMode.BRIGHTNESS
                        } else {
                            GestureMode.VOLUME
                        }
                    }
                }

                when (activeGesture) {
                    GestureMode.BRIGHTNESS -> {
                        if (controlsVisible) {
                            gestureSuppressed = true
                            activeGesture = GestureMode.NONE
                            return true
                        }
                        val deltaPercent = -deltaY / (height * 0.85f)
                        val newBrightness = (gestureStartBrightness + deltaPercent).coerceIn(0.01f, 1.0f)
                        applyBrightness(newBrightness)
                        showGestureFeedback("☀️ 亮度 ${(newBrightness * 100).toInt()}%")
                    }
                    GestureMode.VOLUME -> {
                        if (controlsVisible) {
                            gestureSuppressed = true
                            activeGesture = GestureMode.NONE
                            return true
                        }
                        val maxVol = getMaxAudioVolume()
                        val deltaSteps = (-deltaY / (height * 0.85f)) * maxVol
                        val newVol = (gestureStartVolume + deltaSteps).toInt().coerceIn(0, maxVol)
                        setAudioVolume(newVol)
                        val percent = if (maxVol > 0) (newVol * 100 / maxVol) else 0
                        val icon = if (newVol == 0) "🔇" else "🔊"
                        showGestureFeedback("$icon 音量 $percent%")
                    }
                    GestureMode.PROGRESS -> {
                        gesturePreviewActive = true
                        val duration = currentDuration()
                        val scrubRangeMs = if (duration > 0) min(duration, 180_000L) else 180_000L
                        val deltaMs = (deltaX / width * scrubRangeMs).toLong()
                        gestureTargetProgressMs = (gestureStartProgressMs + deltaMs).coerceIn(
                            0L,
                            if (duration > 0) duration else Long.MAX_VALUE,
                        )
                        val diffSec = (gestureTargetProgressMs - gestureStartProgressMs) / 1000
                        val sign = if (diffSec >= 0) "+${diffSec}s" else "${diffSec}s"
                        val icon = if (diffSec >= 0) "⏩" else "⏪"
                        showGestureFeedback("$icon ${formatTime(gestureTargetProgressMs)} / ${formatTime(duration)} ($sign)")
                        previewSeekPosition(gestureTargetProgressMs)
                    }
                    GestureMode.NONE -> {}
                }
                return true
            }
        })

        view.setOnTouchListener { _, event ->
            val handled = gestureDetector.onTouchEvent(event)
            if (event.action == MotionEvent.ACTION_UP || event.action == MotionEvent.ACTION_CANCEL) {
                if (speedBeforeLongPress != null) {
                    stopLongPressSpeed()
                }
                val wasProgress = activeGesture == GestureMode.PROGRESS || gesturePreviewActive
                if (wasProgress) {
                    val duration = currentDuration()
                    if (duration > 0) {
                        markPendingSeek((gestureTargetProgressMs * SEEK_MAX / duration).toInt())
                    }
                    player?.seekTo(gestureTargetProgressMs)
                }
                if (activeGesture != GestureMode.NONE) {
                    hideGestureFeedbackDelayed(600L)
                }
                resetGestureState()
                if (wasProgress) {
                    updateProgressUi()
                }
                if (controlsVisible) {
                    scheduleHide()
                }
            }
            handled
        }
    }

    private fun getCurrentBrightness(): Float {
        var b = window.attributes.screenBrightness
        if (b < 0f) {
            try {
                val sysVal = Settings.System.getInt(contentResolver, Settings.System.SCREEN_BRIGHTNESS)
                b = sysVal / 255f
            } catch (e: Exception) {
                b = 0.5f
            }
        }
        return b.coerceIn(0.01f, 1.0f)
    }

    private fun applyBrightness(brightness: Float) {
        val clamped = brightness.coerceIn(0.01f, 1.0f)
        val lp = window.attributes
        lp.screenBrightness = clamped
        window.attributes = lp
    }

    private fun getMaxAudioVolume(): Int {
        return runCatching { audioManager.getStreamMaxVolume(AudioManager.STREAM_MUSIC) }.getOrDefault(15)
    }

    private fun getAudioVolume(): Int {
        return runCatching { audioManager.getStreamVolume(AudioManager.STREAM_MUSIC) }.getOrDefault(0)
    }

    private fun setAudioVolume(volume: Int) {
        val max = getMaxAudioVolume()
        val clamped = volume.coerceIn(0, max)
        runCatching {
            audioManager.setStreamVolume(AudioManager.STREAM_MUSIC, clamped, 0)
        }
    }

    private fun showGestureFeedback(text: String) {
        seekFeedbackBadge.text = text
        seekFeedbackBadge.visibility = View.VISIBLE
        main.removeCallbacks(hideSeekFeedback)
    }

    private fun hideGestureFeedbackDelayed(delayMs: Long = 600L) {
        main.removeCallbacks(hideSeekFeedback)
        main.postDelayed(hideSeekFeedback, delayMs)
    }

    private fun startLongPressSpeed() {
        if (speedBeforeLongPress != null) return
        val exo = player ?: return
        speedBeforeLongPress = currentSpeed
        val targetSpeed = longPressSpeed
        exo.setPlaybackSpeed(targetSpeed)
        fastForwardBadge.text = "▶▶ ${trimSpeed(targetSpeed)}x 快速播放中"
        fastForwardBadge.visibility = View.VISIBLE
    }

    private fun stopLongPressSpeed() {
        val prev = speedBeforeLongPress ?: return
        speedBeforeLongPress = null
        player?.setPlaybackSpeed(prev)
        fastForwardBadge.visibility = View.GONE
    }

    private fun seekRelative(deltaMs: Long) {
        val exo = player ?: return
        val duration = currentDuration()
        val current = exo.currentPosition
        val target = (current + deltaMs).coerceIn(0L, if (duration > 0) duration else Long.MAX_VALUE)
        exo.seekTo(target)
        updateProgressUi()
    }

    private val hideSeekFeedback = Runnable {
        seekFeedbackBadge.visibility = View.GONE
    }

    private fun showSeekFeedback(text: String) {
        seekFeedbackBadge.text = text
        seekFeedbackBadge.visibility = View.VISIBLE
        main.removeCallbacks(hideSeekFeedback)
        main.postDelayed(hideSeekFeedback, 800L)
    }

    private fun iconButton(
        @DrawableRes resId: Int,
        contentDesc: String,
        sizeDp: Int,
        iconPaddingDp: Int,
        action: () -> Unit,
    ): ImageView =
        ImageView(this).apply {
            setImageResource(resId)
            contentDescription = contentDesc
            scaleType = ImageView.ScaleType.FIT_CENTER
            setPadding(iconPaddingDp, iconPaddingDp, iconPaddingDp, iconPaddingDp)
            isFocusable = true
            isClickable = true
            val outValue = android.util.TypedValue()
            if (context.theme.resolveAttribute(android.R.attr.selectableItemBackgroundBorderless, outValue, true)) {
                setBackgroundResource(outValue.resourceId)
            }
            layoutParams = LinearLayout.LayoutParams(sizeDp, sizeDp).apply {
                leftMargin = dp(2)
                rightMargin = dp(2)
            }
            setOnClickListener { action() }
        }

    private fun pillButton(label: String, size: Float, action: () -> Unit): TextView =
        TextView(this).apply {
            text = label
            setTextColor(Color.WHITE)
            textSize = size
            gravity = Gravity.CENTER
            background = rounded(0x33FFFFFF, 999f)
            setPadding(dp(12), dp(6), dp(12), dp(6))
            isFocusable = true
            isClickable = true
            layoutParams = LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.WRAP_CONTENT,
                dp(32),
            ).apply {
                leftMargin = dp(4)
                rightMargin = dp(4)
            }
            setOnClickListener { action() }
        }

    private fun onSurfaceTap() {
        if (isDrawerOpen()) {
            closeDrawer()
            return
        }
        if (locked) {
            // 锁定状态下：触摸屏幕呼出解锁按钮，再次触摸直接隐藏
            if (lockButton.visibility == View.VISIBLE && lockButton.alpha > 0.5f) {
                hideLockButtonImmediately()
            } else {
                showLockButton()
            }
            return
        }
        setControlsVisible(!controlsVisible)
    }

    private fun setControlsVisible(visible: Boolean) {
        if (isDrawerOpen() && visible) return
        controlsVisible = visible
        if (locked) {
            controls.visibility = View.GONE
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
        if (!locked && controlsVisible && player?.isPlaying == true && !isDrawerOpen()) {
            main.postDelayed(hideControls, 4500L)
        }
    }

    private fun toggleLock() {
        locked = !locked
        if (locked) {
            if (isDrawerOpen()) closeDrawer()
            lockButton.setImageResource(R.drawable.ic_lock)
            lockButton.contentDescription = getString(R.string.player_unlock_hint)
            controls.visibility = View.GONE
            toast(getString(R.string.player_locked))
            showLockButton()
        } else {
            hideLockButtonImmediately()
            lockButton.setImageResource(R.drawable.ic_unlock)
            lockButton.contentDescription = getString(R.string.player_lock_hint)
            setControlsVisible(true)
            toast(getString(R.string.player_unlocked))
        }
    }

    private fun showMenu() {
        if (info == null) return
        openDrawer(getString(R.string.player_menu)) { container ->
            val layout = LinearLayout(this).apply {
                orientation = LinearLayout.VERTICAL
                layoutParams = FrameLayout.LayoutParams(
                    ViewGroup.LayoutParams.MATCH_PARENT,
                    ViewGroup.LayoutParams.WRAP_CONTENT,
                )
            }

            val subCount = textTracks().size
            val subDesc = if (subCount > 0) "${subCount} 条可选" else "无字幕"
            layout.addView(drawerActionRow("💬 " + getString(R.string.player_menu_subtitle), subDesc) {
                showSubtitleMenu()
            })

            val audioCount = audioTracks().size
            val audioDesc = if (audioCount > 0) "${audioCount} 个音轨" else "默认"
            layout.addView(drawerActionRow("🎵 " + getString(R.string.player_menu_audio), audioDesc) {
                showAudioMenu()
            })

            layout.addView(drawerActionRow("⚡ " + getString(R.string.player_menu_speed), "${trimSpeed(currentSpeed)}x") {
                showSpeedMenu()
            })

            if (info?.nextItemId != null) {
                val suffix = info?.nextTitle?.takeIf { it.isNotBlank() }?.let { " · $it" }.orEmpty()
                layout.addView(drawerActionRow("⏭️ " + getString(R.string.player_menu_next), suffix.trimStart(' ', '·')) {
                    closeDrawer()
                    playNextEpisode()
                })
            }

            layout.addView(drawerActionRow("📺 " + getString(R.string.player_menu_mpv), null) {
                closeDrawer()
                info?.let { openMpv(it) }
            })

            addScrollableDrawerContent(container, layout)
        }
    }

    private fun updatePrefetcherState() {
        val exo = player ?: return
        val duration = exo.duration.takeIf { it != C.TIME_UNSET && it > 0 } ?: 0L
        prefetcher.setWindowMb(
            PlaybackCache.prefetchWindowMb(this, PlaybackDiskCache.limitMb()),
        )
        prefetcher.onTick(
            positionMs = exo.currentPosition.coerceAtLeast(0L),
            bufferedMs = exo.bufferedPosition.coerceAtLeast(0L),
            durationMs = duration,
            buffering = exo.playbackState == Player.STATE_BUFFERING && exo.playWhenReady,
        )
    }

    /** 实时网速：只统计真正走网络的字节，命中磁盘时自然归零。 */
    private fun updateSpeedUi() {
        if (!this::speedView.isInitialized) return
        val bps = NetworkSpeedMeter.sample()
        speedView.text = NetworkSpeedMeter.format(bps)
    }

    /** 新片源 READY 后清理上一集的磁盘缓存。 */
    private fun flushCacheRemoval() {
        val key = pendingCacheRemoval ?: return
        pendingCacheRemoval = null
        PlaybackDiskCache.removeItem(key)
    }

    private fun textTracks(): List<Pair<Tracks.Group, Int>> =
        PlayerTrackHelper.textTracks(player)

    private fun audioTracks(): List<Pair<Tracks.Group, Int>> =
        PlayerTrackHelper.audioTracks(player)

    private fun showSubtitleMenu() {
        PlayerTrackHelper.showSubtitleMenu(this, drawer, player, { showMenu() }) { toast(it) }
    }

    private fun showAudioMenu() {
        PlayerTrackHelper.showAudioMenu(this, drawer, player, { showMenu() }) { toast(it) }
    }

    private fun showSpeedMenu() {
        PlayerSpeedHelper.showSpeedMenu(
            context = this,
            drawer = drawer,
            currentSpeed = currentSpeed,
            longPressSpeed = longPressSpeed,
            onApplySpeed = { applySpeed(it) },
            onApplyLongPressSpeed = { speed ->
                longPressSpeed = speed
                getSharedPreferences("player_prefs", MODE_PRIVATE)
                    .edit()
                    .putFloat("long_press_speed", speed)
                    .apply()
                toast(getString(R.string.player_speed_long_press_set, "${trimSpeed(speed)}x"))
            },
        )
    }

    private fun applySpeed(speed: Float) {
        currentSpeed = speed
        player?.setPlaybackSpeed(speed)
        speedButton.text = speedLabel()
        toast(getString(R.string.player_speed_toast, "${trimSpeed(speed)}x"))
        scheduleHide()
    }

    private fun trimSpeed(speed: Float): String =
        PlayerSpeedHelper.trimSpeed(speed)

    private fun speedLabel(): String =
        PlayerSpeedHelper.speedLabel(currentSpeed)

    private fun showPlaylist() {
        val playInfo = info ?: return
        val entries = playInfo.playlist
        if (entries.isEmpty()) {
            toast(getString(R.string.player_no_playlist))
            return
        }
        val title = getString(R.string.player_playlist)
        val subtitle = "${playInfo.seriesTitle ?: playInfo.title} · 共 ${entries.size} 集"

        openDrawer(title, subtitle) { container ->
            val scroll = ScrollView(this).apply {
                layoutParams = FrameLayout.LayoutParams(
                    ViewGroup.LayoutParams.MATCH_PARENT,
                    ViewGroup.LayoutParams.MATCH_PARENT,
                )
                isVerticalScrollBarEnabled = false
            }
            val listLayout = LinearLayout(this).apply {
                orientation = LinearLayout.VERTICAL
                layoutParams = FrameLayout.LayoutParams(
                    ViewGroup.LayoutParams.MATCH_PARENT,
                    ViewGroup.LayoutParams.WRAP_CONTENT,
                )
            }

            entries.forEach { entry ->
                val isCurrent = entry.current || entry.id == currentItemId
                val itemView = LinearLayout(this).apply {
                    orientation = LinearLayout.HORIZONTAL
                    gravity = Gravity.CENTER_VERTICAL
                    setPadding(dp(14), dp(12), dp(14), dp(12))
                    background = if (isCurrent) {
                        rounded(0x33E8B06A.toInt(), 10f)
                    } else {
                        rounded(0x18FFFFFF, 10f)
                    }
                    isClickable = true
                    isFocusable = true
                    layoutParams = LinearLayout.LayoutParams(
                        ViewGroup.LayoutParams.MATCH_PARENT,
                        ViewGroup.LayoutParams.WRAP_CONTENT,
                    ).apply {
                        bottomMargin = dp(8)
                    }
                    setOnClickListener {
                        closeDrawer()
                        if (entry.id != currentItemId) {
                            switchToEpisode(entry.id)
                        }
                    }
                }

                if (isCurrent) {
                    val playIcon = ImageView(this).apply {
                        setImageResource(R.drawable.ic_play)
                        imageTintList = ColorStateList.valueOf(Color.parseColor("#E8B06A"))
                        layoutParams = LinearLayout.LayoutParams(dp(14), dp(14)).apply {
                            rightMargin = dp(8)
                        }
                    }
                    itemView.addView(playIcon)
                }

                val nameView = TextView(this).apply {
                    text = entry.displayLabel()
                    setTextColor(if (isCurrent) Color.parseColor("#E8B06A") else Color.WHITE)
                    textSize = 13.5f
                    if (isCurrent) typeface = android.graphics.Typeface.DEFAULT_BOLD
                    layoutParams = LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f)
                }
                itemView.addView(nameView)

                if (entry.watched && !isCurrent) {
                    itemView.addView(TextView(this).apply {
                        text = "✓ 已看"
                        setTextColor(Color.parseColor("#7A8293"))
                        textSize = 11f
                    })
                } else if (isCurrent) {
                    itemView.addView(TextView(this).apply {
                        text = "播放中"
                        setTextColor(Color.parseColor("#E8B06A"))
                        textSize = 11f
                    })
                }

                listLayout.addView(itemView)
            }
            scroll.addView(listLayout)
            container.addView(scroll)
        }
    }

    private fun drawerActionRow(
        title: String,
        subtitle: String?,
        action: () -> Unit,
    ): View = drawer.createActionRow(title, subtitle, action)

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

    private fun playItem(playInfo: PlayInfo, startMs: Long, attempt: Int = 0) {
        resetGestureState()
        pendingSeekProgress = -1
        playbackAttempt = attempt
        info = playInfo
        // 切集时只缓存当前视频：换集后删掉上一集的数据（异步，不阻塞起播）。
        val previousItemId = currentItemId
        val previousUri = currentPlayUri?.toString()
        currentItemId = playInfo.itemId
        advancing = false
        titleView.text = playInfo.title
        loadingView.visibility = View.GONE
        currentPlayUri = Uri.parse(playInfo.playUrl)
        if (attempt == 0) {
            resolvedMediaUri = null
        }
        // 换集就清空缓存线，重新按新片源的缓存数据累积。
        if (playInfo.itemId != previousItemId && this::seekBar.isInitialized) {
            cachedRanges = emptyList()
            seekBar.setBufferedRanges(emptyList())
        }

        val exo = ensurePlayer(playInfo, attempt)
        // 复用播放器时 ensurePlayer 不会重建数据源，这里把预取切到当前集。
        prefetcher.setSource(prefetchSourceFactory, currentPlayUri)
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
        // 新片源已经接管，旧集的数据可以安全删除（等新片源 READY 后真正删除）。
        if (playInfo.itemId != previousItemId) {
            pendingCacheRemoval = previousUri
        }
        updateProgressUi()
        updateEpisodeButtons()
        setControlsVisible(true)
    }

    private fun ensurePlayer(playInfo: PlayInfo, attempt: Int): ExoPlayer {
        val headers = playInfo.headers.toMutableMap()
        headers.putIfAbsent("Accept-Encoding", "identity")
        val headersKey = headers.entries
            .sortedBy { it.key.lowercase() }
            .joinToString("|") { "${it.key.lowercase()}=${it.value}" }
        val existing = player
        if (existing != null && playerHeadersKey == headersKey && attempt == 0 && !existing.isReleased) return existing
        if (existing != null) {
            // 不同媒体库的 UA 不同：换源时必须重建播放器，否则请求头还是上一集的
            runCatching { existing.release() }
            player = null
            playerView.player = null
        }
        val clientBuilder = OkHttpClient.Builder()
            .connectTimeout(15, TimeUnit.SECONDS)
            .readTimeout(30, TimeUnit.SECONDS)
            .followRedirects(true)
            .followSslRedirects(true)
            .retryOnConnectionFailure(true)
            .protocols(
                if (attempt == 0) {
                    listOf(Protocol.HTTP_2, Protocol.HTTP_1_1)
                } else {
                    listOf(Protocol.HTTP_1_1)
                },
            )
            .addInterceptor { chain ->
                val request = chain.request()
                Log.d(
                    TAG,
                    "http ${request.method} " +
                        "${request.url.host}${request.url.encodedPath.takeLast(28)} " +
                        "UA=${request.header("User-Agent")} " +
                        "Range=${request.header("Range")}",
                )
                try {
                    val response = chain.proceed(request)
                    Log.d(
                        TAG,
                        "http ${response.code} proto=${response.protocol} " +
                            "${response.header("Content-Type")} " +
                            "len=${response.header("Content-Length")} " +
                            "range=${response.header("Content-Range")} " +
                            "loc=${response.header("Location")?.let { runCatching { Uri.parse(it).host }.getOrNull() }}",
                    )
                    // 记录整片字节数：预取用它把“播放位置 + MB 上限”换算成字节区间。
                    val totalBytes = response.header("Content-Range")
                        ?.substringAfterLast('/')
                        ?.toLongOrNull()
                        ?: response.header("Content-Length")
                            ?.toLongOrNull()
                            ?.takeIf { response.code == 200 }
                    if (totalBytes != null && totalBytes > 0) {
                        prefetcher.setContentLength(totalBytes)
                    }
                    response
                } catch (error: Exception) {
                    Log.e(TAG, "http failed ${request.url.host}", error)
                    throw error
                }
            }
        // 开关开启后，片源（可能是另一台自签名 Alist）也一并放行。
        if (TlsPolicy.isAllowed(this, playInfo.playUrl)) {
            TlsPolicy.clientTls(playInfo.playUrl)?.let { tls ->
                clientBuilder.sslSocketFactory(tls.socketFactory, tls.trustManager)
                clientBuilder.hostnameVerifier(tls.hostnameVerifier)
            }
        }
        val httpFactory = OkHttpDataSource.Factory(clientBuilder.build())
            .setDefaultRequestProperties(headers)
            // 统计实时网速：挂在缓存层之下，只计真正走网络的字节。
            .setTransferListener(NetworkSpeedMeter)
        val ua = headers.entries.firstOrNull { it.key.equals("User-Agent", ignoreCase = true) }?.value
        if (!ua.isNullOrBlank()) {
            httpFactory.setUserAgent(ua)
        }
        val resolvingFactory = RedirectResolvingDataSourceFactory(
            upstreamFactory = httpFactory,
            getOriginalVideoUri = { currentPlayUri },
            getRedirectUri = { resolvedMediaUri },
            onRedirectUri = { uri ->
                Log.d(TAG, "cached 302 stream direct url: ${uri.host}")
                resolvedMediaUri = uri
            },
        )
        // 磁盘缓存：拉取过的字节落盘，seek 回已拉取区间直接读盘、不再发请求。
        // 缓存层放在 302 解析之下，Cache key 始终是稳定的播放地址。
        val diskCache = PlaybackDiskCache.open(this)
        val mediaDataSourceFactory: DataSource.Factory = if (diskCache != null) {
            val cacheFactory = CacheDataSource.Factory()
                .setCache(diskCache)
                .setUpstreamDataSourceFactory(resolvingFactory)
                .setCacheWriteDataSinkFactory(
                    CacheDataSink.Factory()
                        .setCache(diskCache)
                        .setFragmentSize(CACHE_FRAGMENT_SIZE),
                )
                // 先查盘再决定是否走网络；写盘失败自动降级为纯网络播放。
                .setFlags(
                    CacheDataSource.FLAG_BLOCK_ON_CACHE or
                        CacheDataSource.FLAG_IGNORE_CACHE_ON_ERROR,
                )
            DefaultDataSource.Factory(this, cacheFactory)
        } else {
            DefaultDataSource.Factory(this, resolvingFactory)
        }
        // 预取走独立数据源：和播放器共用同一个缓存目录与请求头，但互不占用对方状态。
        prefetchSourceFactory = if (diskCache != null) {
            CacheDataSource.Factory()
                .setCache(diskCache)
                // 复用 302 解析层：预取直接打直链，不再多一次跳转，请求头与播放器一致。
                .setUpstreamDataSourceFactory(resolvingFactory)
                .setCacheWriteDataSinkFactory(
                    CacheDataSink.Factory()
                        .setCache(diskCache)
                        .setFragmentSize(CACHE_FRAGMENT_SIZE),
                )
                // 预取失败（磁盘满 / 片源拒绝 Range）直接放弃，不影响播放。
                .setFlags(CacheDataSource.FLAG_BLOCK_ON_CACHE)
        } else {
            null
        }
        // 内存缓冲固定 64MB：时间阈值统一成兜底值，唯一的刹车是字节上限；
        // min 与 max 相同 → 播放消耗多少就立刻续拉多少。
        val memoryLimitMb = PlaybackCache.memoryLimitMb()
        Log.d(
            TAG,
            "memory buffer ${memoryLimitMb}MB, disk cache " +
                (if (diskCache != null) "${PlaybackDiskCache.limitMb()}MB" else "off"),
        )
        val loadControl = DefaultLoadControl.Builder()
            .setTargetBufferBytes(PlaybackCache.targetBufferBytes())
            .setBufferDurationsMs(
                PlaybackCache.bufferTimeCapMs(),
                PlaybackCache.bufferTimeCapMs(),
                PlaybackCache.bufferForPlaybackMs(),
                PlaybackCache.bufferForPlaybackAfterRebufferMs(),
            )
            // 回看缓存占用同一份字节预算，高码率下会挤占前向缓冲，这里关闭。
            .setBackBuffer(PlaybackCache.backBufferMs(), false)
            // 字节上限优先，时间阈值只做兜底。
            .setPrioritizeTimeOverSizeThresholds(false)
            .build()
        val exo = ExoPlayer.Builder(this)
            .setLoadControl(loadControl)
            .setMediaSourceFactory(DefaultMediaSourceFactory(mediaDataSourceFactory))
            .setRenderersFactory(
                DefaultRenderersFactory(this).setEnableDecoderFallback(true),
            )
            .setHandleAudioBecomingNoisy(true)
            .build()
        exo.addListener(playbackListener)
        player = exo
        playerHeadersKey = headersKey
        playerView.player = exo
        prefetcher.setSource(prefetchSourceFactory, currentPlayUri)
        prefetcher.setWindowMb(
            PlaybackCache.prefetchWindowMb(this, PlaybackDiskCache.limitMb()),
        )
        return exo
    }

    private class RedirectResolvingDataSource(
        private val upstream: DataSource,
        private val originalVideoUri: Uri?,
        private val getRedirectUri: () -> Uri?,
        private val onRedirectUri: (Uri) -> Unit,
    ) : DataSource {
        override fun addTransferListener(transferListener: TransferListener) {
            upstream.addTransferListener(transferListener)
        }

        override fun open(dataSpec: DataSpec): Long {
            val redirectUri = getRedirectUri()
            val effectiveSpec = if (redirectUri != null && originalVideoUri != null && dataSpec.uri == originalVideoUri) {
                dataSpec.buildUpon().setUri(redirectUri).build()
            } else {
                dataSpec
            }
            val length = upstream.open(effectiveSpec)
            val resolved = upstream.uri
            if (resolved != null && originalVideoUri != null && dataSpec.uri == originalVideoUri && resolved != originalVideoUri) {
                onRedirectUri(resolved)
            }
            return length
        }

        override fun read(buffer: ByteArray, offset: Int, length: Int): Int =
            upstream.read(buffer, offset, length)

        override fun getUri(): Uri? = upstream.uri ?: getRedirectUri()

        override fun getResponseHeaders(): Map<String, List<String>> =
            upstream.responseHeaders

        override fun close() {
            upstream.close()
        }
    }

    private class RedirectResolvingDataSourceFactory(
        private val upstreamFactory: DataSource.Factory,
        private val getOriginalVideoUri: () -> Uri?,
        private val getRedirectUri: () -> Uri?,
        private val onRedirectUri: (Uri) -> Unit,
    ) : DataSource.Factory {
        override fun createDataSource(): DataSource =
            RedirectResolvingDataSource(
                upstream = upstreamFactory.createDataSource(),
                originalVideoUri = getOriginalVideoUri(),
                getRedirectUri = getRedirectUri,
                onRedirectUri = onRedirectUri,
            )
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
            this,
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

    /** 当前已缓冲到的绝对位置；未知时返回 0。 */
    private fun bufferedPositionMs(): Long {
        val buffered = player?.bufferedPosition ?: return 0L
        return if (buffered == C.TIME_UNSET || buffered <= 0L) 0L else buffered
    }

    private fun progressOf(positionMs: Long, durationMs: Long): Int =
        (positionMs * SEEK_MAX / durationMs).toInt().coerceIn(0, SEEK_MAX)

    /**
     * 维护进度条上的缓存线：内存已缓冲区间 + 磁盘里真实存在的缓存分段，取并集后**只增不减**。
     * 因为不做减法，往回拖时也不会出现「先塌掉再涨回来」的闪跳。
     */
    private fun updateCachedRanges(duration: Long) {
        if (duration <= 0 || !this::seekBar.isInitialized) return
        val additions = ArrayList<IntRange>(4)
        val position = player?.currentPosition ?: 0L
        val buffered = bufferedPositionMs()
        if (buffered > position) {
            additions += progressOf(position, duration)..progressOf(buffered, duration)
        }
        for (span in prefetcher.cachedSpansMs()) {
            if (span.last > span.first) {
                additions += progressOf(span.first, duration)..progressOf(span.last, duration)
            }
        }
        if (additions.isEmpty()) return
        val merged = mergeRanges(cachedRanges + additions)
        if (merged != cachedRanges) {
            cachedRanges = merged
            seekBar.setBufferedRanges(merged)
        }
    }

    /** 合并重叠/相邻区间，保证结果升序且互不重叠。 */
    private fun mergeRanges(input: List<IntRange>): List<IntRange> {
        if (input.isEmpty()) return emptyList()
        val sorted = input.sortedBy { it.first }
        val out = ArrayList<IntRange>(sorted.size)
        var start = sorted[0].first
        var end = sorted[0].last
        for (index in 1 until sorted.size) {
            val range = sorted[index]
            if (range.first <= end + 1) {
                if (range.last > end) end = range.last
            } else {
                if (end > start) out += start..end
                start = range.first
                end = range.last
            }
        }
        if (end > start) out += start..end
        return out
    }

    /** 记录本次跳转目标：进度条钉在目标值，直到播放器追上或 1.5 秒超时。 */
    private fun markPendingSeek(progress: Int) {
        pendingSeekProgress = progress.coerceIn(0, SEEK_MAX)
        pendingSeekAtMs = SystemClock.uptimeMillis()
    }

    /** 拖动进度条或横向手势时，只更新预览，不触发 seek。 */
    private fun previewSeekPosition(positionMs: Long) {
        val duration = currentDuration()
        if (duration <= 0) return
        val target = positionMs.coerceIn(0L, duration)
        val progress = (target * SEEK_MAX / duration).toInt().coerceIn(0, SEEK_MAX)
        seekBar.progress = progress
        seekBar.invalidate()
        val stateRes = if (target <= bufferedPositionMs()) {
            R.string.player_seek_buffered
        } else {
            R.string.player_seek_buffering
        }
        timeView.text = getString(stateRes, formatTime(target))
    }

    private fun updateProgressUi() {
        val exo = player ?: return
        val duration = currentDuration()
        val position = exo.currentPosition.coerceAtLeast(0L)
        // 缓存线独立于拖动状态：拖动时也照常按磁盘实际数据增长。
        updateCachedRanges(duration)
        if (!userSeeking && !gesturePreviewActive) {
            if (duration > 0) {
                val actual = (position * SEEK_MAX / duration)
                    .toInt()
                    .coerceIn(0, SEEK_MAX)
                // seek 之后播放器要一两帧才追上目标，这期间钉住目标值，
                // 否则进度条会先回弹到旧位置再弹回去（视觉上的“闪一下”）。
                val now = SystemClock.uptimeMillis()
                if (pendingSeekProgress >= 0) {
                    val reached = abs(actual - pendingSeekProgress) <= 2
                    if (reached || now - pendingSeekAtMs > 1_500L) {
                        pendingSeekProgress = -1
                    }
                }
                seekBar.progress = if (pendingSeekProgress >= 0) pendingSeekProgress else actual
                timeView.text = "${formatTime(position)} / ${formatTime(duration)}"
            }
        }
        val isPlaying = exo.isPlaying
        val isBuffering = exo.playbackState == Player.STATE_BUFFERING && exo.playWhenReady
        if (isBuffering && loadingView.visibility != View.VISIBLE) {
            bufferingView.visibility = View.VISIBLE
            centerPlayButton.visibility = View.GONE
        } else {
            bufferingView.visibility = View.GONE
            if (controlsVisible && !locked) {
                centerPlayButton.visibility = View.VISIBLE
            } else {
                centerPlayButton.visibility = View.GONE
            }
            centerPlayButton.setImageResource(if (isPlaying) R.drawable.ic_pause else R.drawable.ic_play)
            centerPlayButton.contentDescription = playPauseButton.contentDescription
        }
        playPauseButton.setImageResource(if (isPlaying) R.drawable.ic_pause else R.drawable.ic_play)
        playPauseButton.contentDescription =
            if (isPlaying) getString(R.string.player_pause) else getString(R.string.player_play)
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
            fullscreenButton.setImageResource(R.drawable.ic_fullscreen_exit)
        } else {
            enterWindowedMode()
        }
        fullscreenButton.contentDescription = fullscreenLabel()
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
            fullscreenButton.setImageResource(R.drawable.ic_fullscreen)
            fullscreenButton.contentDescription = fullscreenLabel()
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
            this,
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
        resetGestureState()
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

    /** 自己处理横竖屏（清单里声明了 configChanges），所以这里重建底部栏。 */
    override fun onConfigurationChanged(newConfig: Configuration) {
        super.onConfigurationChanged(newConfig)
        if (!this::controls.isInitialized || !this::bottomBar.isInitialized) return
        val previousProgress = seekBar.progress
        controls.removeView(bottomBar)
        buildBottomBar()
        seekBar.progress = previousProgress
        seekBar.setBufferedRanges(cachedRanges)
        updateEpisodeButtons()
        updateProgressUi()
    }

    override fun onDestroy() {
        stopHeartbeat()
        main.removeCallbacksAndMessages(null)
        prefetcher.stop()
        NetworkSpeedMeter.reset()
        runCatching { player?.release() }
        player = null
        playerView.player = null
        // 退出播放即清空本次会话的磁盘缓存（删除放在后台线程）。
        PlaybackDiskCache.close(clear = true)
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
            hideLockButtonImmediately()
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
            isDrawerOpen() -> closeDrawer()
            locked -> toggleLock()
            fullscreen -> toggleFullscreen()
            else -> finishWithResult()
        }
    }

    private fun togglePlay() {
        val exo = player ?: return
        if (exo.playbackState == Player.STATE_BUFFERING) {
            if (exo.playWhenReady) {
                exo.pause()
                toast("已暂停")
            } else {
                exo.play()
                toast("正在缓冲加载中...")
            }
            updateProgressUi()
            return
        }
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
