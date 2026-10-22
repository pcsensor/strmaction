package top.strmaction.companion.player

import android.content.Context
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.graphics.RectF
import android.graphics.drawable.ColorDrawable
import android.util.AttributeSet
import android.view.MotionEvent
import android.widget.SeekBar

/**
 * 播放进度条（方案 A：缓存线置顶）。
 *
 * - 轨道：8dp 全高圆角，半透明白；
 * - 已播放：从左侧整段填金橙，全高保留；
 * - 已缓存：2.5dp 白色细线**压在最上层**，连已播放区域也穿过去，按真实缓存区间分段绘制
 *   （缓存有洞就断开，命中磁盘的每一段都能看见）；
 * - 播放头：3.5×16dp 白色竖线，压在最上层，上下各露出轨道 4dp。
 *
 * 缓存区间由调用方通过 [setBufferedRanges] 传入，单位是进度值（0..max）。
 * 调用方只做并集、不删减，所以缓存线只会增长，不会因为 seek 回缩闪跳。
 */
class BufferedSeekBar @JvmOverloads constructor(
    context: Context,
    attrs: AttributeSet? = null,
    defStyleAttr: Int = android.R.attr.seekBarStyle,
) : SeekBar(context, attrs, defStyleAttr) {

    private val trackPaint = Paint(Paint.ANTI_ALIAS_FLAG)
    private val playedPaint = Paint(Paint.ANTI_ALIAS_FLAG)
    private val bufferedPaint = Paint(Paint.ANTI_ALIAS_FLAG)
    private val headPaint = Paint(Paint.ANTI_ALIAS_FLAG)
    private val rect = RectF()

    // dp() 只收 Int，小数尺寸按密度直接换算。
    private val density = context.resources.displayMetrics.density
    private val trackHeight = context.dp(8).toFloat()
    private val bufferedLineHeight = 2.5f * density
    /** 播放头竖线：3.5×16dp，上下各露出轨道 4dp。 */
    private val headWidth = 3.5f * density
    private val headHeight = context.dp(16).toFloat()
    private val headHalf = headWidth / 2f

    private val trackColor = Color.parseColor("#3DFFFFFF")
    private val playedColor = Color.parseColor("#F0A94D")
    private val bufferedColor = Color.parseColor("#E8FFFFFF")

    /** 已缓存区间（进度单位），由外部维护成单调递增。 */
    private var bufferedRanges: List<IntRange> = emptyList()

    init {
        // 默认轨道和滑块全部隐藏，交给 onDraw 统一绘制。
        progressDrawable = ColorDrawable(Color.TRANSPARENT)
        thumb = null
        minimumHeight = context.dp(32)
        setPadding(context.dp(10), 0, context.dp(10), 0)
    }

    /**
     * thumb = null 时，AOSP AbsSeekBar 不会在 progress 变化时 invalidate；
     * 这里主动补上，否则自绘轨道会停在上一帧。
     */
    override fun setProgress(progress: Int) {
        val old = this.progress
        super.setProgress(progress)
        if (this.progress != old) invalidate()
    }

    override fun setSecondaryProgress(secondaryProgress: Int) {
        val old = this.secondaryProgress
        super.setSecondaryProgress(secondaryProgress)
        if (this.secondaryProgress != old) invalidate()
    }

    /** 传入已缓存区间（进度单位，升序、互不重叠）。内容没变就不重绘。 */
    fun setBufferedRanges(ranges: List<IntRange>) {
        if (ranges == bufferedRanges) return
        bufferedRanges = ranges
        invalidate()
    }

    override fun onTouchEvent(event: MotionEvent): Boolean {
        val handled = super.onTouchEvent(event)
        if (handled) invalidate()
        return handled
    }

    override fun onDraw(canvas: Canvas) {
        val width = width.toFloat()
        val height = height.toFloat()
        if (width <= 0f || height <= 0f) return

        // 竖线只有 3.5dp 宽，两端只留半个线宽，轨道比圆点版本各多出 4dp。
        val left = paddingLeft + headHalf
        val right = width - paddingRight - headHalf
        if (right <= left) return

        val centerY = height / 2f
        val span = right - left
        val maxValue = max.coerceAtLeast(1)
        val trackTop = centerY - trackHeight / 2f
        val trackBottom = centerY + trackHeight / 2f
        val trackRadius = trackHeight / 2f

        // 1. 轨道（全高）
        trackPaint.color = trackColor
        rect.set(left, trackTop, right, trackBottom)
        canvas.drawRoundRect(rect, trackRadius, trackRadius, trackPaint)

        // 2. 已播放：整段金橙，全高保留
        val playedFraction = (progress.toFloat() / maxValue).coerceIn(0f, 1f)
        val playedX = left + span * playedFraction
        if (playedX - left > 0.5f) {
            playedPaint.color = playedColor
            rect.set(left, trackTop, playedX, trackBottom)
            canvas.drawRoundRect(rect, trackRadius, trackRadius, playedPaint)
        }

        // 3. 已缓存：白色细线压在最上层，穿过已播放区域，按区间分段
        val lineRadius = bufferedLineHeight / 2f
        bufferedPaint.color = bufferedColor
        for (range in bufferedRanges) {
            val startFraction = (range.first.toFloat() / maxValue).coerceIn(0f, 1f)
            val endFraction = (range.last.toFloat() / maxValue).coerceIn(0f, 1f)
            val startX = left + span * startFraction
            val endX = left + span * endFraction
            if (endX - startX <= 1f) continue
            rect.set(startX, centerY - lineRadius, endX, centerY + lineRadius)
            canvas.drawRoundRect(rect, lineRadius, lineRadius, bufferedPaint)
        }

        // 4. 播放头：白色竖线，压在最上层（缓存细线在这里断开一小段）
        headPaint.color = Color.WHITE
        rect.set(
            playedX - headHalf,
            centerY - headHeight / 2f,
            playedX + headHalf,
            centerY + headHeight / 2f,
        )
        canvas.drawRoundRect(rect, headHalf, headHalf, headPaint)
    }
}
