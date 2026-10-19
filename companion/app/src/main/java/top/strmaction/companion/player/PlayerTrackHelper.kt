package top.strmaction.companion.player

import android.content.Context
import android.view.ViewGroup
import android.widget.FrameLayout
import android.widget.LinearLayout
import android.widget.ScrollView
import androidx.media3.common.C
import androidx.media3.common.TrackSelectionOverride
import androidx.media3.common.Tracks
import androidx.media3.exoplayer.ExoPlayer
import top.strmaction.companion.R

object PlayerTrackHelper {

    fun textTracks(player: ExoPlayer?): List<Pair<Tracks.Group, Int>> {
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

    fun audioTracks(player: ExoPlayer?): List<Pair<Tracks.Group, Int>> {
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

    fun trackLabel(group: Tracks.Group, index: Int): String {
        val format = group.getTrackFormat(index)
        val label = format.label?.takeIf { it.isNotBlank() }
            ?: format.language?.takeIf { it.isNotBlank() }
            ?: "轨道 ${index + 1}"
        return label
    }

    fun showSubtitleMenu(
        context: Context,
        drawer: PlayerDrawer,
        player: ExoPlayer?,
        onBack: () -> Unit,
        onToast: (String) -> Unit,
    ) {
        val tracks = textTracks(player)
        if (tracks.isEmpty()) {
            onToast(context.getString(R.string.player_no_track))
            return
        }
        drawer.open(context.getString(R.string.player_menu_subtitle), onBack = onBack) { container ->
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

            val isOff = player?.trackSelectionParameters?.disabledTrackTypes?.contains(C.TRACK_TYPE_TEXT) == true
            layout.addView(drawer.createItem(context.getString(R.string.player_subtitle_off), isOff) {
                player?.trackSelectionParameters = player?.trackSelectionParameters
                    ?.buildUpon()
                    ?.setTrackTypeDisabled(C.TRACK_TYPE_TEXT, true)
                    ?.build() ?: return@createItem
                drawer.close()
            })

            tracks.forEach { (group, index) ->
                val label = trackLabel(group, index)
                val isSelected = !isOff && player?.trackSelectionParameters?.overrides?.containsKey(group.mediaTrackGroup) == true
                layout.addView(drawer.createItem(label, isSelected) {
                    player?.trackSelectionParameters = player?.trackSelectionParameters
                        ?.buildUpon()
                        ?.setTrackTypeDisabled(C.TRACK_TYPE_TEXT, false)
                        ?.setOverrideForType(TrackSelectionOverride(group.mediaTrackGroup, index))
                        ?.build() ?: return@createItem
                    drawer.close()
                })
            }
            scroll.addView(layout)
            container.addView(scroll)
        }
    }

    fun showAudioMenu(
        context: Context,
        drawer: PlayerDrawer,
        player: ExoPlayer?,
        onBack: () -> Unit,
        onToast: (String) -> Unit,
    ) {
        val tracks = audioTracks(player)
        if (tracks.isEmpty()) {
            onToast(context.getString(R.string.player_no_track))
            return
        }
        drawer.open(context.getString(R.string.player_menu_audio), onBack = onBack) { container ->
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
            tracks.forEach { (group, index) ->
                val label = trackLabel(group, index)
                val isSelected = player?.trackSelectionParameters?.overrides?.containsKey(group.mediaTrackGroup) == true
                layout.addView(drawer.createItem(label, isSelected) {
                    player?.trackSelectionParameters = player?.trackSelectionParameters
                        ?.buildUpon()
                        ?.setOverrideForType(TrackSelectionOverride(group.mediaTrackGroup, index))
                        ?.build() ?: return@createItem
                    drawer.close()
                })
            }
            scroll.addView(layout)
            container.addView(scroll)
        }
    }
}
