package top.strmaction.companion

import android.content.Intent
import android.graphics.Color
import android.net.Uri
import android.os.Bundle
import android.text.InputType
import android.view.Gravity
import android.view.ViewGroup
import android.widget.Button
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import androidx.appcompat.app.AppCompatActivity
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL
import java.util.concurrent.Executors

/** 首次启动 / 重新配置服务器地址。手机可滚动，电视可遥控填写。 */
class SetupActivity : AppCompatActivity() {

    private lateinit var urlInput: EditText
    private lateinit var packageInput: EditText
    private lateinit var statusView: TextView
    private lateinit var testButton: Button
    private lateinit var saveButton: Button
    private val executor = Executors.newSingleThreadExecutor { runnable ->
        Thread(runnable, "strmaction-setup").apply { isDaemon = true }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val prefs = getSharedPreferences(MainActivity.PREFS, MODE_PRIVATE)
        val tv = Device.isTelevision(this)
        val padding = if (tv) 64 else 24

        val container = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(dp(padding), dp(if (tv) 48 else 36), dp(padding), dp(48))
            setBackgroundColor(Color.parseColor("#07080A"))
        }

        container.addView(
            TextView(this).apply {
                text = "StrmAction"
                textSize = if (tv) 34f else 28f
                setTextColor(Color.parseColor("#E8B06A"))
                letterSpacing = 0.02f
            },
        )
        container.addView(
            TextView(this).apply {
                text = getString(R.string.setup_title)
                textSize = if (tv) 24f else 20f
                setTextColor(Color.WHITE)
                setPadding(0, dp(10), 0, 0)
            },
        )
        container.addView(
            TextView(this).apply {
                text = getString(R.string.setup_desc)
                textSize = if (tv) 14f else 13f
                setTextColor(Color.parseColor("#8A93A5"))
                setPadding(0, dp(12), 0, 0)
                setLineSpacing(dp(4).toFloat(), 1f)
            },
        )

        urlInput = EditText(this).apply {
            hint = getString(R.string.setup_hint)
            inputType = InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_VARIATION_URI
            val savedServer = prefs.getString(MainActivity.KEY_SERVER, null)
            if (!savedServer.isNullOrBlank()) {
                setText(savedServer)
            }
            setTextColor(Color.WHITE)
            setHintTextColor(Color.parseColor("#5C6678"))
            setSingleLine(true)
            textSize = if (tv) 18f else 16f
            setPadding(dp(14), dp(14), dp(14), dp(14))
        }
        container.addView(urlInput, matchWidth(top = 24))

        container.addView(
            TextView(this).apply {
                text = getString(R.string.setup_mpv_label)
                textSize = 12f
                setTextColor(Color.parseColor("#8A93A5"))
                setPadding(0, dp(18), 0, 0)
            },
        )
        packageInput = EditText(this).apply {
            setText(prefs.getString(MainActivity.KEY_MPV_PACKAGE, MpvFallback.DEFAULT_PACKAGE))
            setTextColor(Color.WHITE)
            setSingleLine(true)
            textSize = 15f
            setPadding(dp(14), dp(12), dp(14), dp(12))
            inputType = InputType.TYPE_CLASS_TEXT
        }
        container.addView(packageInput, matchWidth(top = 6))

        val row = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.START
        }
        testButton = Button(this).apply {
            text = getString(R.string.setup_test)
            setOnClickListener { testConnection() }
        }
        saveButton = Button(this).apply {
            text = getString(R.string.setup_save)
            setBackgroundColor(Color.parseColor("#E8B06A"))
            setTextColor(Color.parseColor("#07080A"))
            setOnClickListener { saveAndEnter() }
        }
        row.addView(testButton, rowParams(top = 24))
        row.addView(saveButton, rowParams(top = 24))
        container.addView(row, matchWidth())

        statusView = TextView(this).apply {
            textSize = 13f
            setTextColor(Color.parseColor("#8A93A5"))
            setPadding(0, dp(18), 0, 0)
            setLineSpacing(dp(3).toFloat(), 1f)
        }
        container.addView(statusView, matchWidth())

        container.addView(
            TextView(this).apply {
                text = "${getString(R.string.app_name)} ${BuildConfig.VERSION_NAME} · 内置 Media3 播放器"
                textSize = 11f
                setTextColor(Color.parseColor("#4F5766"))
                setPadding(0, dp(28), 0, 0)
            },
        )

        val scroll = ScrollView(this).apply {
            setBackgroundColor(Color.parseColor("#07080A"))
            isFillViewport = true
            addView(
                container,
                ViewGroup.LayoutParams(
                    ViewGroup.LayoutParams.MATCH_PARENT,
                    ViewGroup.LayoutParams.WRAP_CONTENT,
                ),
            )
        }
        setContentView(scroll)
        urlInput.requestFocus()
    }

    private fun testConnection() {
        val base = normalizedUrl() ?: run {
            showStatus(getString(R.string.setup_invalid), true)
            return
        }
        testButton.isEnabled = false
        saveButton.isEnabled = false
        showStatus(getString(R.string.setup_testing), false)
        executor.execute {
            val result = runCatching {
                val conn = (URL("$base/api/health").openConnection() as HttpURLConnection).apply {
                    requestMethod = "GET"
                    connectTimeout = 5000
                    readTimeout = 5000
                    setRequestProperty("X-StrmAction-Companion", "1")
                }
                val code = conn.responseCode
                val text = (if (code in 200..299) conn.inputStream else conn.errorStream)
                    ?.bufferedReader()?.use { it.readText() } ?: ""
                conn.disconnect()
                if (code !in 200..299) error("HTTP $code")
                val json = JSONObject(text)
                if (!json.optBoolean("ok", false)) error("服务未就绪")
                json.optString("version", "?")
            }
            runOnUiThread {
                testButton.isEnabled = true
                saveButton.isEnabled = true
                result.onSuccess { version ->
                    showStatus(getString(R.string.setup_ok, version), false)
                }.onFailure { error ->
                    val message = error.message ?: error.javaClass.simpleName
                    showStatus(getString(R.string.setup_fail, message), true)
                }
            }
        }
    }

    private fun saveAndEnter() {
        val base = normalizedUrl() ?: run {
            showStatus(getString(R.string.setup_invalid), true)
            return
        }
        val packageName = packageInput.text.toString().trim()
            .ifBlank { MpvFallback.DEFAULT_PACKAGE }
        getSharedPreferences(MainActivity.PREFS, MODE_PRIVATE)
            .edit()
            .putString(MainActivity.KEY_SERVER, base)
            .putString(MainActivity.KEY_MPV_PACKAGE, packageName)
            .apply()
        startActivity(
            Intent(this, MainActivity::class.java)
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TASK),
        )
        finish()
    }

    private fun normalizedUrl(): String? {
        val raw = urlInput.text.toString().trim().trimEnd('/')
        if (raw.isBlank()) return null
        val parsed = runCatching { Uri.parse(raw) }.getOrNull() ?: return null
        if (parsed.host.isNullOrBlank()) return null
        if (parsed.scheme != "http" && parsed.scheme != "https") return null
        return raw
    }

    private fun showStatus(message: String, error: Boolean) {
        statusView.text = message
        statusView.setTextColor(
            if (error) Color.parseColor("#FF8A8A") else Color.parseColor("#7DD3A0"),
        )
    }

    private fun matchWidth(top: Int = 0): LinearLayout.LayoutParams =
        LinearLayout.LayoutParams(
            ViewGroup.LayoutParams.MATCH_PARENT,
            ViewGroup.LayoutParams.WRAP_CONTENT,
        ).apply { topMargin = dp(top) }

    private fun rowParams(top: Int = 0): LinearLayout.LayoutParams =
        LinearLayout.LayoutParams(
            ViewGroup.LayoutParams.WRAP_CONTENT,
            ViewGroup.LayoutParams.WRAP_CONTENT,
        ).apply {
            topMargin = dp(top)
            rightMargin = dp(12)
        }

    private fun dp(value: Int): Int = (value * resources.displayMetrics.density).toInt()

    override fun onDestroy() {
        executor.shutdownNow()
        super.onDestroy()
    }
}
