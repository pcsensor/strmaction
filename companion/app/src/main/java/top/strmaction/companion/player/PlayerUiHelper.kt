package top.strmaction.companion.player

import android.content.Context
import android.graphics.drawable.GradientDrawable
import java.util.Locale

fun Context.dp(value: Int): Int = (value * resources.displayMetrics.density).toInt()

fun Context.rounded(color: Int, radiusDp: Float): GradientDrawable = GradientDrawable().apply {
    setColor(color)
    cornerRadius = dp(radiusDp.toInt()).toFloat()
}

fun formatTime(ms: Long): String {
    val totalSeconds = (ms / 1000).coerceAtLeast(0)
    val seconds = totalSeconds % 60
    val minutes = (totalSeconds / 60) % 60
    val hours = totalSeconds / 3600
    return if (hours > 0) {
        String.format(Locale.US, "%d:%02d:%02d", hours, minutes, seconds)
    } else {
        String.format(Locale.US, "%02d:%02d", minutes, seconds)
    }
}
