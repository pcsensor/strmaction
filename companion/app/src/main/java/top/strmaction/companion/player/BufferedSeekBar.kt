package top.strmaction.companion.player

import android.content.Context
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.graphics.Path
import android.graphics.RectF
import android.graphics.drawable.ColorDrawable
import android.util.AttributeSet
import android.widget.SeekBar

/**
 * Bilibili 风格的三层进度条：未缓冲 / 已缓冲 / 已播放。
 *
 * 仍然继承 SeekBar，保留原有的触摸、焦点、进度监听与 secondaryProgress 语义，
 * 只重绘轨道，避免系统 SeekBar 的 secondary 层在不同主题/设备上不可见。
 */
class BufferedSeekBar @JvmOverloads constructor(
    context: Context,
    attrs: AttributeSet? = null,
    defStyleAttr: Int = android.R.attr.seekBarStyle,
) : SeekBar(context, attrs, defStyleAttr) {

    private val trackPaint = Paint(Paint.ANTI_ALIAS_FLAG)
    private val thumbPaint = Paint(Paint.ANTI_ALIAS_FLAG)
    private val trackPath = Path()
    private val trackRect = RectF()

    private val trackHeight = context.dp(4).toFloat()
    private val thumbRadius = context.dp(6).toFloat()
    private val thumbInnerRadius = context.dp(3).toFloat()

    private val trackColor = Color.parseColor("#4DFFFFFF")
    private val bufferedColor = Color.parseColor("#CCFFFFFF")
    private val playedColor = Color.parseColor("#E8B06A")

    init {
        // 默认轨道和滑块全部隐藏，交给 onDraw 统一绘制。
        progressDrawable = ColorDrawable(Color.TRANSPARENT)
        thumb = null
        minimumHeight = context.dp(28)
        setPadding(context.dp(10), 0, context.dp(10), 0)
    }

    override fun onDraw(canvas: Canvas) {
        val width = width.toFloat()
        val height = height.toFloat()
        if (width <= 0f || height <= 0f) return

        val left = paddingLeft + thumbRadius
        val right = width - paddingRight - thumbRadius
        if (right <= left) return

        val centerY = height / 2f
        val top = centerY - trackHeight / 2f
        val bottom = centerY + trackHeight / 2f

        trackRect.set(left, top, right, bottom)
        trackPath.reset()
        trackPath.addRoundRect(
            trackRect,
            trackHeight / 2f,
            trackHeight / 2f,
            Path.Direction.CW,
        )

        val maxValue = max.coerceAtLeast(1)
        val playedFraction = (progress.toFloat() / maxValue).coerceIn(0f, 1f)
        val bufferedFraction = (secondaryProgress.toFloat() / maxValue)
            .coerceIn(playedFraction, 1f)
        val playedX = left + (right - left) * playedFraction
        val bufferedX = left + (right - left) * bufferedFraction

        canvas.save()
        canvas.clipPath(trackPath)

        trackPaint.color = trackColor
        canvas.drawRect(trackRect, trackPaint)

        trackPaint.color = bufferedColor
        canvas.drawRect(left, top, bufferedX, bottom, trackPaint)

        trackPaint.color = playedColor
        canvas.drawRect(left, top, playedX, bottom, trackPaint)

        canvas.restore()

        // 小圆点滑块：外圈用主题金色，内圈白色，保持 B 站式的轻量感。
        thumbPaint.color = playedColor
        canvas.drawCircle(playedX, centerY, thumbRadius, thumbPaint)
        thumbPaint.color = Color.WHITE
        canvas.drawCircle(playedX, centerY, thumbInnerRadius, thumbPaint)
    }
}
