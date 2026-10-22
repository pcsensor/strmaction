package top.strmaction.companion

import android.annotation.SuppressLint
import android.content.Intent
import android.graphics.Color
import android.net.Uri
import android.net.http.SslError
import android.os.Build
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.view.Gravity
import android.view.KeyEvent
import android.view.MotionEvent
import android.view.View
import android.view.ViewGroup
import android.view.WindowManager
import android.webkit.CookieManager
import android.webkit.SslErrorHandler
import android.webkit.ValueCallback
import android.webkit.WebChromeClient
import android.webkit.WebResourceError
import android.webkit.WebResourceRequest
import android.webkit.WebSettings
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.Button
import android.widget.FrameLayout
import android.widget.LinearLayout
import android.widget.ProgressBar
import android.widget.TextView
import android.widget.Toast
import androidx.activity.addCallback
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AppCompatActivity
import androidx.core.view.WindowCompat
import androidx.core.view.WindowInsetsCompat
import androidx.core.view.WindowInsetsControllerCompat
import java.net.ConnectException
import java.net.SocketTimeoutException
import java.net.UnknownHostException
import java.security.cert.CertPathValidatorException
import java.util.concurrent.Executors
import javax.net.ssl.SSLHandshakeException
import javax.net.ssl.SSLPeerUnverifiedException

/**
 * 手机优先的 WebView 壳（电视端同样可用）：
 *
 * - 手机：竖屏/横屏跟随系统，触摸滚动完全交给 WebView（不拦截、不嵌套滚动冲突）；
 * - 电视：自动横屏、隐藏系统栏、加载 `?tv=1` 进入 10-foot 布局，遥控器长按确定可重设服务器；
 * - 播放交给 PlayerActivity（Media3），网页不接触播放地址与 token；
 * - 支持网页里的海报/背景图上传（onShowFileChooser）。
 */
class MainActivity : AppCompatActivity() {

    companion object {
        const val PREFS = "strmaction"
        const val KEY_SERVER = "server_url"
    }

    private lateinit var webView: WebView
    private lateinit var errorView: LinearLayout
    private lateinit var errorDetailView: TextView
    private lateinit var loadingView: LinearLayout
    private lateinit var serverUrl: String
    private lateinit var allowedHost: String
    private var isTv = false
    private var pageFailed = false
    private var pageLoaded = false
    private var checkingConnection = false
    private var healthCheckGeneration = 0
    private var fileChooserCallback: ValueCallback<Array<Uri>>? = null

    private val main = Handler(Looper.getMainLooper())
    private val healthExecutor = Executors.newSingleThreadExecutor { runnable ->
        Thread(runnable, "strmaction-health").apply { isDaemon = true }
    }

    private val pageTimeout = Runnable {
        if (!pageLoaded && !pageFailed) {
            showError(getString(R.string.web_timeout))
        }
    }

    private val playerLauncher = registerForActivityResult(
        ActivityResultContracts.StartActivityForResult(),
    ) {
        refreshWebProgress()
    }

    private val fileChooserLauncher = registerForActivityResult(
        ActivityResultContracts.StartActivityForResult(),
    ) { result ->
        val callback = fileChooserCallback
        fileChooserCallback = null
        if (callback == null) return@registerForActivityResult
        val uris = WebChromeClient.FileChooserParams.parseResult(result.resultCode, result.data)
        callback.onReceiveValue(uris)
    }

    @SuppressLint("SetJavaScriptEnabled")
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        serverUrl = PlayApi.serverUrl(this)
        if (serverUrl.isBlank()) {
            startActivity(Intent(this, SetupActivity::class.java))
            finish()
            return
        }
        allowedHost = parsedHost(serverUrl) ?: ""
        isTv = Device.isTelevision(this)

        if (isTv) {
            requestedOrientation = android.content.pm.ActivityInfo.SCREEN_ORIENTATION_LANDSCAPE
            WindowCompat.setDecorFitsSystemWindows(window, false)
            window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
            hideSystemBars()
        } else {
            // 手机：系统栏占位（状态栏颜色跟随页面），页面不会被刘海/状态栏遮挡
            WindowCompat.setDecorFitsSystemWindows(window, true)
            @Suppress("DEPRECATION")
            run {
                window.statusBarColor = statusBarColor()
                window.navigationBarColor = statusBarColor()
            }
        }

        val root = FrameLayout(this).apply {
            setBackgroundColor(Color.parseColor("#07080A"))
        }

        webView = WebView(this).apply {
            layoutParams = FrameLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.MATCH_PARENT,
            )
            setBackgroundColor(Color.parseColor("#07080A"))
            overScrollMode = View.OVER_SCROLL_NEVER
            isVerticalScrollBarEnabled = false
            isHorizontalScrollBarEnabled = false
            isNestedScrollingEnabled = true
            scrollBarStyle = View.SCROLLBARS_INSIDE_OVERLAY

            settings.apply {
                javaScriptEnabled = true
                domStorageEnabled = true
                databaseEnabled = true
                mediaPlaybackRequiresUserGesture = false
                // 响应式页面：按 viewport meta 布局，禁止双击/双指缩放干扰滚动
                useWideViewPort = true
                loadWithOverviewMode = true
                setSupportZoom(false)
                builtInZoomControls = false
                displayZoomControls = false
                textZoom = 100
                defaultTextEncodingName = "UTF-8"
                cacheMode = WebSettings.LOAD_DEFAULT
                allowFileAccess = false
                allowContentAccess = false
                javaScriptCanOpenWindowsAutomatically = false
                mixedContentMode = WebSettings.MIXED_CONTENT_COMPATIBILITY_MODE
                userAgentString = "$userAgentString StrmActionCompanion/${BuildConfig.VERSION_NAME}"
            }

            CookieManager.getInstance().setAcceptCookie(true)

            // 防止任何父容器在手指按下时抢走手势（滚动/横向滑动都只归 WebView）
            setOnTouchListener { view, event ->
                when (event.actionMasked) {
                    MotionEvent.ACTION_DOWN -> view.parent?.requestDisallowInterceptTouchEvent(true)
                    MotionEvent.ACTION_UP, MotionEvent.ACTION_CANCEL ->
                        view.parent?.requestDisallowInterceptTouchEvent(false)
                }
                false
            }

            webViewClient = object : WebViewClient() {
                override fun shouldOverrideUrlLoading(
                    view: WebView,
                    request: WebResourceRequest,
                ): Boolean = handleUrl(request.url.toString())

                override fun onPageFinished(view: WebView, url: String) {
                    super.onPageFinished(view, url)
                    if (checkingConnection) return
                    pageLoaded = true
                    main.removeCallbacks(pageTimeout)
                    if (!pageFailed) {
                        loadingView.visibility = View.GONE
                        errorView.visibility = View.GONE
                    }
                    // 电视遥控器：页面加载完后必须把焦点还给 WebView，否则方向键无效
                    if (isTv) view.requestFocus()
                }

                override fun onReceivedError(
                    view: WebView,
                    request: WebResourceRequest,
                    error: WebResourceError,
                ) {
                    super.onReceivedError(view, request, error)
                    if (checkingConnection) return
                    if (request.isForMainFrame) {
                        val detail = error.description?.toString()
                            ?.takeIf { it.isNotBlank() }
                            ?: getString(R.string.web_unreachable)
                        showError(detail)
                    }
                }

                override fun onReceivedHttpError(
                    view: WebView,
                    request: WebResourceRequest,
                    errorResponse: android.webkit.WebResourceResponse,
                ) {
                    super.onReceivedHttpError(view, request, errorResponse)
                    if (checkingConnection) return
                    if (request.isForMainFrame) {
                        showError(getString(R.string.web_http_error, errorResponse.statusCode))
                    }
                }

                override fun onReceivedSslError(
                    view: WebView,
                    handler: SslErrorHandler,
                    error: SslError,
                ) {
                    if (checkingConnection) {
                        handler.cancel()
                        return
                    }
                    if (TlsPolicy.isEnabled(this@MainActivity)) {
                        handler.proceed()
                        return
                    }
                    handler.cancel()
                    val url: String? = error.url
                    val host = url?.let { runCatching { Uri.parse(it).host }.getOrNull() }
                    // 外部子资源的证书问题不把整页切成错误页，只拦掉该资源。
                    if (host == null || host.equals(allowedHost, ignoreCase = true)) {
                        showError(getString(R.string.web_ssl_error))
                    }
                }
            }

            webChromeClient = object : WebChromeClient() {
                override fun onConsoleMessage(message: android.webkit.ConsoleMessage): Boolean {
                    android.util.Log.d(
                        "StrmActionWeb",
                        "${message.message()} @${message.sourceId()}:${message.lineNumber()}",
                    )
                    return true
                }

                override fun onShowFileChooser(
                    webView: WebView,
                    filePathCallback: ValueCallback<Array<Uri>>,
                    fileChooserParams: FileChooserParams,
                ): Boolean {
                    this@MainActivity.fileChooserCallback?.onReceiveValue(null)
                    this@MainActivity.fileChooserCallback = filePathCallback
                    return runCatching {
                        fileChooserLauncher.launch(fileChooserParams.createIntent())
                        true
                    }.getOrElse {
                        this@MainActivity.fileChooserCallback = null
                        false
                    }
                }
            }

            addJavascriptInterface(JsBridge(this@MainActivity, allowedHost), "StrmActionNative")
            isFocusable = true
            isFocusableInTouchMode = true
        }
        root.addView(webView)
        CookieManager.getInstance().setAcceptThirdPartyCookies(webView, true)

        errorView = buildErrorView()
        root.addView(errorView)
        loadingView = buildLoadingView()
        root.addView(loadingView)

        setContentView(root)
        pageFailed = false
        if (BuildConfig.DEBUG) {
            WebView.setWebContentsDebuggingEnabled(true)
        }
        startConnectionCheck()

        onBackPressedDispatcher.addCallback(this) {
            if (webView.canGoBack()) {
                webView.goBack()
            } else {
                finish()
            }
        }
    }

    private fun buildErrorView(): LinearLayout {
        val container = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            gravity = Gravity.CENTER
            setBackgroundColor(Color.parseColor("#07080A"))
            setPadding(dp(28), dp(28), dp(28), dp(28))
            visibility = View.GONE
            isClickable = true
            layoutParams = FrameLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.MATCH_PARENT,
            )
        }
        container.addView(
            TextView(this).apply {
                text = getString(R.string.web_error_title)
                setTextColor(Color.WHITE)
                textSize = 20f
                gravity = Gravity.CENTER
            },
        )
        container.addView(
            TextView(this).apply {
                text = getString(R.string.web_error_desc)
                setTextColor(Color.parseColor("#9AA3B2"))
                textSize = 13f
                gravity = Gravity.CENTER
                setPadding(0, dp(10), 0, dp(8))
            },
        )
        errorDetailView = TextView(this).apply {
            setTextColor(Color.parseColor("#FF8A8A"))
            textSize = 12f
            gravity = Gravity.CENTER
            setPadding(0, 0, 0, dp(18))
            visibility = View.GONE
        }
        container.addView(errorDetailView)
        val row = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER
        }
        row.addView(
            Button(this).apply {
                text = getString(R.string.web_retry)
                setOnClickListener { startConnectionCheck() }
            },
        )
        row.addView(
            Button(this).apply {
                text = getString(R.string.web_settings)
                setOnClickListener { openSetup() }
            },
        )
        container.addView(row)
        return container
    }

    private fun buildLoadingView(): LinearLayout {
        val container = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            gravity = Gravity.CENTER
            setBackgroundColor(Color.parseColor("#07080A"))
            setPadding(dp(28), dp(28), dp(28), dp(28))
            visibility = View.VISIBLE
            isClickable = true
            layoutParams = FrameLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.MATCH_PARENT,
            )
        }
        container.addView(
            ProgressBar(this).apply {
                isIndeterminate = true
                indeterminateTintList = android.content.res.ColorStateList.valueOf(
                    Color.parseColor("#E8B06A"),
                )
            },
        )
        container.addView(
            TextView(this).apply {
                text = getString(R.string.web_connecting)
                setTextColor(Color.parseColor("#9AA3B2"))
                textSize = 13f
                gravity = Gravity.CENTER
                setPadding(0, dp(12), 0, 0)
            },
        )
        return container
    }

    private fun startConnectionCheck() {
        val generation = ++healthCheckGeneration
        checkingConnection = true
        pageLoaded = false
        pageFailed = false
        webView.stopLoading()
        main.removeCallbacks(pageTimeout)
        errorView.visibility = View.GONE
        loadingView.visibility = View.VISIBLE
        loadingView.bringToFront()

        val appContext = applicationContext
        healthExecutor.execute {
            val result = runCatching {
                val url = "${serverUrl.trimEnd('/')}/api/health"
                val conn = TlsPolicy.openConnection(appContext, url).apply {
                    requestMethod = "GET"
                    connectTimeout = 5_000
                    readTimeout = 5_000
                    setRequestProperty("X-StrmAction-Companion", "1")
                }
                try {
                    val code = conn.responseCode
                    if (code !in 200..299) error("HTTP $code")
                } finally {
                    conn.disconnect()
                }
            }
            main.post {
                if (isFinishing || isDestroyed || generation != healthCheckGeneration) {
                    return@post
                }
                result.onSuccess { loadWebPage() }
                    .onFailure { showError(connectionErrorMessage(it)) }
            }
        }
    }

    private fun loadWebPage() {
        checkingConnection = false
        loadingView.visibility = View.GONE
        errorView.visibility = View.GONE
        pageLoaded = false
        pageFailed = false
        webView.loadUrl(withTvFlag(serverUrl))
        main.removeCallbacks(pageTimeout)
        main.postDelayed(pageTimeout, 10_000L)
    }

    private fun showError(message: String) {
        checkingConnection = false
        pageFailed = true
        main.removeCallbacks(pageTimeout)
        loadingView.visibility = View.GONE
        errorDetailView.text = message
        errorDetailView.visibility = View.VISIBLE
        errorView.visibility = View.VISIBLE
        errorView.bringToFront()
    }

    private fun connectionErrorMessage(error: Throwable): String {
        var cause: Throwable? = error
        while (cause != null) {
            when (cause) {
                is CertPathValidatorException, is SSLHandshakeException, is SSLPeerUnverifiedException ->
                    return getString(R.string.web_ssl_error)
                is SocketTimeoutException ->
                    return getString(R.string.web_timeout)
                is ConnectException, is UnknownHostException ->
                    return getString(R.string.web_unreachable)
            }
            cause = cause.cause
        }
        return error.message?.takeIf { it.isNotBlank() }
            ?: getString(R.string.web_error_desc)
    }

    private fun handleUrl(url: String): Boolean {
        if (url.startsWith("intent://", ignoreCase = true)) {
            runCatching {
                val intent = Intent.parseUri(url, Intent.URI_INTENT_SCHEME)
                startActivity(intent)
            }.onFailure {
                toast(getString(R.string.player_intent_missing))
            }
            return true
        }
        if (url.startsWith("http://", true) || url.startsWith("https://", true)) {
            val host = parsedHost(url)
            if (host != null && host.equals(allowedHost, ignoreCase = true)) {
                return false
            }
            runCatching { startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(url))) }
            return true
        }
        if (url.startsWith("magnet:", true) || url.startsWith("mailto:", true) ||
            url.startsWith("tel:", true)
        ) {
            runCatching { startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(url))) }
            return true
        }
        return false
    }

    private fun withTvFlag(url: String): String {
        if (!isTv) return url
        if (url.contains("tv=1")) return url
        val separator = if (url.contains("?")) "&" else "?"
        return "$url${separator}tv=1"
    }

    fun currentWebHost(): String? = webView.url?.let { parsedHost(it) }

    /** JS 桥：播放内置播放器 */
    fun openPlayer(itemId: Int) {
        if (itemId <= 0) return
        val intent = Intent(this, PlayerActivity::class.java)
            .putExtra(PlayerActivity.EXTRA_ITEM_ID, itemId)
        runCatching { playerLauncher.launch(intent) }
            .onFailure { toast(it.message ?: getString(R.string.player_error_title)) }
    }

    fun openSetup() {
        startActivity(Intent(this, SetupActivity::class.java))
    }

    private fun refreshWebProgress() {
        if (!::webView.isInitialized) return
        webView.post {
            webView.evaluateJavascript(
                "window.dispatchEvent(new Event('strmaction:progress-updated'));",
                null,
            )
            webView.requestFocus()
        }
    }

    override fun onResume() {
        super.onResume()
        if (!::webView.isInitialized) return
        webView.onResume()
        webView.post {
            webView.requestFocus()
            refreshWebProgress()
        }
    }

    override fun onPause() {
        if (::webView.isInitialized) {
            webView.onPause()
            // 保证登录 Cookie 及时落盘，冷启动后不丢会话
            CookieManager.getInstance().flush()
        }
        super.onPause()
    }

    /** 遥控器长按「确定」= 重新配置服务器地址（电视端唯一入口）。 */
    override fun onKeyDown(keyCode: Int, event: KeyEvent): Boolean {
        if ((keyCode == KeyEvent.KEYCODE_DPAD_CENTER || keyCode == KeyEvent.KEYCODE_ENTER) &&
            event.repeatCount == 0
        ) {
            event.startTracking()
        }
        return super.onKeyDown(keyCode, event)
    }

    override fun onKeyLongPress(keyCode: Int, event: KeyEvent): Boolean {
        if (keyCode == KeyEvent.KEYCODE_DPAD_CENTER || keyCode == KeyEvent.KEYCODE_ENTER) {
            openSetup()
            return true
        }
        return super.onKeyLongPress(keyCode, event)
    }

    override fun onDestroy() {
        healthExecutor.shutdownNow()
        main.removeCallbacks(pageTimeout)
        if (::webView.isInitialized) {
            webView.removeJavascriptInterface("StrmActionNative")
            webView.destroy()
        }
        super.onDestroy()
    }

    private fun hideSystemBars() {
        WindowInsetsControllerCompat(window, window.decorView).apply {
            hide(WindowInsetsCompat.Type.systemBars())
            systemBarsBehavior =
                WindowInsetsControllerCompat.BEHAVIOR_SHOW_TRANSIENT_BARS_BY_SWIPE
        }
    }

    private fun toast(message: String) {
        Toast.makeText(this, message, Toast.LENGTH_SHORT).show()
    }

    private fun dp(value: Int): Int = (value * resources.displayMetrics.density).toInt()
}
