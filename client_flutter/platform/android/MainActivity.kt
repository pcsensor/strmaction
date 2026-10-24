package top.strmaction.companion

import android.app.PictureInPictureParams
import android.app.UiModeManager
import android.content.Context
import android.content.res.Configuration
import android.os.Build
import android.util.Rational
import android.view.View
import android.view.WindowManager
import androidx.core.view.WindowCompat
import androidx.core.view.WindowInsetsCompat
import androidx.core.view.WindowInsetsControllerCompat
import androidx.media3.ui.PlayerView
import io.flutter.embedding.android.FlutterActivity
import io.flutter.embedding.engine.FlutterEngine
import io.flutter.plugin.common.EventChannel
import io.flutter.plugin.common.MethodChannel
import io.flutter.plugin.platform.PlatformView
import io.flutter.plugin.platform.PlatformViewFactory
import io.flutter.plugin.common.StandardMessageCodec
import java.io.File

class MainActivity : FlutterActivity() {
    private lateinit var player: UnifiedPlayer
    private var fullscreen = false

    private fun applyFullscreen() {
        WindowCompat.setDecorFitsSystemWindows(window, false)
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.P) {
            window.attributes = window.attributes.apply {
                layoutInDisplayCutoutMode = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R)
                    WindowManager.LayoutParams.LAYOUT_IN_DISPLAY_CUTOUT_MODE_ALWAYS
                else WindowManager.LayoutParams.LAYOUT_IN_DISPLAY_CUTOUT_MODE_SHORT_EDGES
            }
        }
        WindowInsetsControllerCompat(window, window.decorView).apply {
            systemBarsBehavior = WindowInsetsControllerCompat.BEHAVIOR_SHOW_TRANSIENT_BARS_BY_SWIPE
            if (fullscreen) hide(WindowInsetsCompat.Type.systemBars())
            else show(WindowInsetsCompat.Type.systemBars())
        }
    }

    override fun onWindowFocusChanged(hasFocus: Boolean) {
        super.onWindowFocusChanged(hasFocus)
        if (hasFocus) applyFullscreen()
    }

    override fun configureFlutterEngine(flutterEngine: FlutterEngine) {
        super.configureFlutterEngine(flutterEngine)
        player = UnifiedPlayer(this)
        val messenger = flutterEngine.dartExecutor.binaryMessenger
        MethodChannel(messenger, "strmaction/native").setMethodCallHandler { call, result ->
            try {
                when (call.method) {
                    "fullscreen" -> { fullscreen = call.arguments == true; applyFullscreen(); result.success(null) }
                    "configDirectory" -> result.success(File(filesDir, "unified-client").apply { mkdirs() }.absolutePath)
                    "legacySettings" -> {
                        val prefs = getSharedPreferences("player_prefs", Context.MODE_PRIVATE)
                        val legacy = mutableMapOf<String, Any>(
                            "server_url" to getSharedPreferences("strmaction", Context.MODE_PRIVATE).getString("server_url", "").orEmpty(),
                            "cache_limit_mb" to prefs.getInt("prefetch_mb", 512),
                            "disk_cache_limit_mb" to prefs.getInt("disk_cache_mb", 2048),
                            "inherit_cache_defaults" to !(prefs.contains("prefetch_mb") || prefs.contains("disk_cache_mb")),
                        )
                        result.success(legacy)
                    }
                    "isTV" -> result.success((getSystemService(UI_MODE_SERVICE) as UiModeManager).currentModeType == Configuration.UI_MODE_TYPE_TELEVISION)
                    "trust" -> {
                        PrivateCa.pem = call.arguments as? String ?: ""
                        // Validate now, before any player requests.
                        PrivateCa.configure(okhttp3.OkHttpClient.Builder())
                        result.success(null)
                    }
                    else -> result.notImplemented()
                }
            } catch (error: Exception) { result.error("native", error.localizedMessage, null) }
        }
        MethodChannel(messenger, "strmaction/player").setMethodCallHandler { call, result ->
            try { player.command(call.method, call.arguments); result.success(null) }
            catch (error: Exception) { result.error("player", error.localizedMessage, null) }
        }
        EventChannel(messenger, "strmaction/player/events").setStreamHandler(object : EventChannel.StreamHandler {
            override fun onListen(arguments: Any?, sink: EventChannel.EventSink) { player.sink = sink; player.emit() }
            override fun onCancel(arguments: Any?) { player.sink = null }
        })
        flutterEngine.platformViewsController.registry.registerViewFactory("strmaction/video", object : PlatformViewFactory(StandardMessageCodec.INSTANCE) {
            override fun create(context: Context, viewId: Int, args: Any?): PlatformView {
                val surface = PlayerView(context).apply {
                    useController = false
                    player = this@MainActivity.player.exo
                    isFocusable = false
                    isFocusableInTouchMode = false
                }
                this@MainActivity.player.surface = surface
                return object : PlatformView {
                    override fun getView(): View = surface
                    override fun dispose() { surface.player = null; this@MainActivity.player.surface = null }
                }
            }
        })
    }
    fun enterPlayerPiP() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O && player.loaded) {
            enterPictureInPictureMode(PictureInPictureParams.Builder().setAspectRatio(Rational(16, 9)).build())
        }
    }
    override fun onUserLeaveHint() {
        super.onUserLeaveHint()
        if (::player.isInitialized && player.exo?.isPlaying == true) enterPlayerPiP()
    }
    override fun onPictureInPictureModeChanged(inPictureInPictureMode: Boolean, newConfig: Configuration) {
        super.onPictureInPictureModeChanged(inPictureInPictureMode, newConfig)
        if (::player.isInitialized) { player.inPiP = inPictureInPictureMode; player.emit() }
    }
    override fun onDestroy() {
        if (::player.isInitialized) player.close()
        super.onDestroy()
    }
}
