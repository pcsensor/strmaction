package top.strmaction.companion.player

import android.content.Context
import android.graphics.Color
import android.view.ViewGroup
import android.widget.FrameLayout
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import top.strmaction.companion.R
import java.util.Locale

object PlayerSpeedHelper {

    fun trimSpeed(speed: Float): String =
        if (speed % 1f == 0f) String.format(Locale.US, "%.1f", speed)
        else String.format(Locale.US, "%.2f", speed).trimEnd('0').trimEnd('.')

    fun speedLabel(currentSpeed: Float): String =
        if (currentSpeed == 1f) "倍速" else "${trimSpeed(currentSpeed)}x"

    fun showSpeedMenu(
        context: Context,
        drawer: PlayerDrawer,
        currentSpeed: Float,
        longPressSpeed: Float,
        onApplySpeed: (Float) -> Unit,
        onApplyLongPressSpeed: (Float) -> Unit,
    ) {
        drawer.open("播放速度") { container ->
            val scroll = ScrollView(context).apply {
                layoutParams = FrameLayout.LayoutParams(
                    ViewGroup.LayoutParams.MATCH_PARENT,
                    ViewGroup.LayoutParams.MATCH_PARENT,
                )
                isVerticalScrollBarEnabled = false
            }
            val layout = LinearLayout(context).apply {
                orientation = LinearLayout.VERTICAL
                layoutParams = FrameLayout.LayoutParams(
                    ViewGroup.LayoutParams.MATCH_PARENT,
                    ViewGroup.LayoutParams.WRAP_CONTENT,
                )
            }

            layout.addView(TextView(context).apply {
                text = "播放速度"
                setTextColor(Color.parseColor("#8E96A8"))
                textSize = 12f
                setPadding(context.dp(4), context.dp(4), context.dp(4), context.dp(8))
            })

            val speeds = floatArrayOf(0.5f, 0.75f, 1f, 1.25f, 1.5f, 2f, 3f)
            val speedLabels = mapOf(
                0.5f to "0.5x",
                0.75f to "0.75x",
                1f to "1.0x (正常)",
                1.25f to "1.25x",
                1.5f to "1.5x",
                2f to "2.0x",
                3f to "3.0x",
            )

            speeds.forEach { speed ->
                val isSelected = currentSpeed == speed
                layout.addView(drawer.createItem(
                    label = speedLabels[speed] ?: "${trimSpeed(speed)}x",
                    selected = isSelected,
                ) {
                    onApplySpeed(speed)
                    drawer.close()
                })
            }

            layout.addView(TextView(context).apply {
                text = "长按加速倍速（按住屏幕时加速）"
                setTextColor(Color.parseColor("#8E96A8"))
                textSize = 12f
                setPadding(context.dp(4), context.dp(16), context.dp(4), context.dp(8))
            })

            val longSpeeds = floatArrayOf(1.5f, 2.0f, 2.5f, 3.0f)
            val longLabels = mapOf(
                1.5f to "1.5x",
                2.0f to "2.0x (默认)",
                2.5f to "2.5x",
                3.0f to "3.0x",
            )
            longSpeeds.forEach { speed ->
                val isSelected = longPressSpeed == speed
                layout.addView(drawer.createItem(
                    label = longLabels[speed] ?: "${trimSpeed(speed)}x",
                    selected = isSelected,
                ) {
                    onApplyLongPressSpeed(speed)
                    showSpeedMenu(
                        context,
                        drawer,
                        currentSpeed,
                        speed,
                        onApplySpeed,
                        onApplyLongPressSpeed,
                    )
                })
            }

            scroll.addView(layout)
            container.addView(scroll)
        }
    }
}
