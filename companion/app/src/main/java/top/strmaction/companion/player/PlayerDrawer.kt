package top.strmaction.companion.player

import android.app.Activity
import android.content.res.ColorStateList
import android.graphics.Color
import android.graphics.drawable.GradientDrawable
import android.view.Gravity
import android.view.View
import android.view.ViewGroup
import android.widget.FrameLayout
import android.widget.ImageView
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import top.strmaction.companion.PlayEntry
import top.strmaction.companion.R

class PlayerDrawer(
    private val activity: Activity,
    private val root: FrameLayout,
    private val onDrawerStateChanged: ((isOpen: Boolean) -> Unit)? = null,
) {
    private lateinit var drawerOverlay: FrameLayout
    private lateinit var drawerBackdrop: View
    private lateinit var drawerContainer: LinearLayout
    private lateinit var drawerTitleView: TextView
    private lateinit var drawerSubtitleView: TextView
    private lateinit var drawerBackBtn: ImageView
    private lateinit var drawerCloseBtn: ImageView
    private lateinit var drawerBody: FrameLayout
    private var drawerBackAction: (() -> Unit)? = null

    init {
        initDrawer()
    }

    private fun initDrawer() {
        drawerOverlay = FrameLayout(activity).apply {
            layoutParams = FrameLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.MATCH_PARENT,
            )
            visibility = View.GONE
            isClickable = true
        }

        drawerBackdrop = View(activity).apply {
            layoutParams = FrameLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.MATCH_PARENT,
            )
            setBackgroundColor(0x88000000.toInt())
            setOnClickListener { close() }
        }
        drawerOverlay.addView(drawerBackdrop)

        val screenW = activity.resources.displayMetrics.widthPixels
        val screenH = activity.resources.displayMetrics.heightPixels
        val targetW = if (screenW > screenH) {
            (screenW * 0.40f).toInt()
        } else {
            (screenW * 0.70f).toInt().coerceAtLeast(activity.dp(280))
        }

        drawerContainer = LinearLayout(activity).apply {
            orientation = LinearLayout.VERTICAL
            layoutParams = FrameLayout.LayoutParams(
                targetW,
                ViewGroup.LayoutParams.MATCH_PARENT,
            ).apply {
                gravity = Gravity.END
            }
            background = GradientDrawable().apply {
                setColor(0xF713161F.toInt())
                cornerRadii = floatArrayOf(
                    activity.dp(16).toFloat(), activity.dp(16).toFloat(),
                    0f, 0f,
                    0f, 0f,
                    activity.dp(16).toFloat(), activity.dp(16).toFloat(),
                )
            }
            setPadding(activity.dp(16), activity.dp(16), activity.dp(16), activity.dp(16))
            isClickable = true
        }

        val header = LinearLayout(activity).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER_VERTICAL
            layoutParams = LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.WRAP_CONTENT,
            ).apply {
                bottomMargin = activity.dp(12)
            }
        }

        drawerBackBtn = createIconButton(R.drawable.ic_back, "返回", activity.dp(32), activity.dp(6)) {
            val back = drawerBackAction
            if (back != null) back() else close()
        }.apply {
            visibility = View.GONE
        }
        header.addView(drawerBackBtn)

        val titleBox = LinearLayout(activity).apply {
            orientation = LinearLayout.VERTICAL
            layoutParams = LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f).apply {
                leftMargin = activity.dp(4)
            }
        }
        drawerTitleView = TextView(activity).apply {
            setTextColor(Color.WHITE)
            textSize = 15.5f
            typeface = android.graphics.Typeface.DEFAULT_BOLD
            maxLines = 1
            ellipsize = android.text.TextUtils.TruncateAt.END
        }
        drawerSubtitleView = TextView(activity).apply {
            setTextColor(Color.parseColor("#9AA2B1"))
            textSize = 11f
            maxLines = 1
            ellipsize = android.text.TextUtils.TruncateAt.END
            visibility = View.GONE
        }
        titleBox.addView(drawerTitleView)
        titleBox.addView(drawerSubtitleView)
        header.addView(titleBox)

        drawerCloseBtn = createIconButton(R.drawable.ic_close, "关闭", activity.dp(32), activity.dp(6)) {
            close()
        }
        header.addView(drawerCloseBtn)
        drawerContainer.addView(header)

        drawerContainer.addView(View(activity).apply {
            layoutParams = LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, activity.dp(1)).apply {
                bottomMargin = activity.dp(12)
            }
            setBackgroundColor(0x22FFFFFF)
        })

        drawerBody = FrameLayout(activity).apply {
            layoutParams = LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                0,
                1f,
            )
        }
        drawerContainer.addView(drawerBody)
        drawerOverlay.addView(drawerContainer)
        root.addView(drawerOverlay)
    }

    fun isOpen(): Boolean =
        this::drawerOverlay.isInitialized && drawerOverlay.visibility == View.VISIBLE

    fun open(
        title: String,
        subtitle: String? = null,
        onBack: (() -> Unit)? = null,
        setupBody: (FrameLayout) -> Unit,
    ) {
        drawerTitleView.text = title
        if (subtitle != null) {
            drawerSubtitleView.text = subtitle
            drawerSubtitleView.visibility = View.VISIBLE
        } else {
            drawerSubtitleView.visibility = View.GONE
        }
        drawerBackAction = onBack
        drawerBackBtn.visibility = if (onBack != null) View.VISIBLE else View.GONE
        drawerBody.removeAllViews()
        setupBody(drawerBody)

        val screenW = activity.resources.displayMetrics.widthPixels
        val screenH = activity.resources.displayMetrics.heightPixels
        val targetW = if (screenW > screenH) {
            (screenW * 0.40f).toInt()
        } else {
            (screenW * 0.70f).toInt().coerceAtLeast(activity.dp(280))
        }
        (drawerContainer.layoutParams as? FrameLayout.LayoutParams)?.width = targetW
        drawerContainer.requestLayout()

        drawerOverlay.visibility = View.VISIBLE
        drawerContainer.translationX = targetW.toFloat()
        drawerBackdrop.alpha = 0f
        drawerBackdrop.animate().alpha(1f).setDuration(220).start()
        drawerContainer.animate().translationX(0f).setDuration(240).start()
        onDrawerStateChanged?.invoke(true)
    }

    fun close() {
        if (!isOpen()) return
        val targetW = drawerContainer.width.takeIf { it > 0 } ?: activity.dp(300)
        drawerBackdrop.animate().alpha(0f).setDuration(180).start()
        drawerContainer.animate().translationX(targetW.toFloat()).setDuration(200).withEndAction {
            drawerOverlay.visibility = View.GONE
            drawerBody.removeAllViews()
            onDrawerStateChanged?.invoke(false)
        }.start()
    }

    fun createItem(
        label: String,
        selected: Boolean,
        action: () -> Unit,
    ): View =
        LinearLayout(activity).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER_VERTICAL
            setPadding(activity.dp(14), activity.dp(12), activity.dp(14), activity.dp(12))
            background = if (selected) {
                activity.rounded(0x33E8B06A.toInt(), 10f)
            } else {
                activity.rounded(0x14FFFFFF, 10f)
            }
            isClickable = true
            isFocusable = true
            layoutParams = LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.WRAP_CONTENT,
            ).apply {
                bottomMargin = activity.dp(8)
            }
            addView(TextView(activity).apply {
                text = label
                setTextColor(if (selected) Color.parseColor("#E8B06A") else Color.WHITE)
                textSize = 13.5f
                if (selected) typeface = android.graphics.Typeface.DEFAULT_BOLD
                layoutParams = LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f)
            })
            if (selected) {
                addView(TextView(activity).apply {
                    text = "✓"
                    setTextColor(Color.parseColor("#E8B06A"))
                    textSize = 14f
                    typeface = android.graphics.Typeface.DEFAULT_BOLD
                })
            }
            setOnClickListener { action() }
        }

    fun createActionRow(title: String, subtitle: String?, action: () -> Unit): View =
        LinearLayout(activity).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER_VERTICAL
            setPadding(activity.dp(14), activity.dp(13), activity.dp(14), activity.dp(13))
            background = activity.rounded(0x14FFFFFF, 10f)
            isClickable = true
            isFocusable = true
            layoutParams = LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.WRAP_CONTENT,
            ).apply {
                bottomMargin = activity.dp(8)
            }
            addView(TextView(activity).apply {
                text = title
                setTextColor(Color.WHITE)
                textSize = 14f
                layoutParams = LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f)
            })
            if (subtitle != null) {
                addView(TextView(activity).apply {
                    text = subtitle
                    setTextColor(Color.parseColor("#9AA2B1"))
                    textSize = 12f
                    layoutParams = LinearLayout.LayoutParams(
                        ViewGroup.LayoutParams.WRAP_CONTENT,
                        ViewGroup.LayoutParams.WRAP_CONTENT,
                    ).apply {
                        rightMargin = activity.dp(6)
                    }
                })
            }
            addView(TextView(activity).apply {
                text = "›"
                setTextColor(Color.parseColor("#66FFFFFF"))
                textSize = 18f
            })
            setOnClickListener { action() }
        }

    private fun createIconButton(
        resId: Int,
        contentDesc: String,
        sizeDp: Int,
        paddingDp: Int,
        action: () -> Unit,
    ): ImageView =
        ImageView(activity).apply {
            setImageResource(resId)
            contentDescription = contentDesc
            scaleType = ImageView.ScaleType.FIT_CENTER
            setPadding(paddingDp, paddingDp, paddingDp, paddingDp)
            isFocusable = true
            isClickable = true
            val outValue = android.util.TypedValue()
            if (activity.theme.resolveAttribute(android.R.attr.selectableItemBackgroundBorderless, outValue, true)) {
                setBackgroundResource(outValue.resourceId)
            }
            layoutParams = LinearLayout.LayoutParams(sizeDp, sizeDp)
            setOnClickListener { action() }
        }
}
