package top.strmaction.companion

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Intent
import android.media.MediaMetadata
import android.media.session.MediaSession
import android.media.session.PlaybackState
import android.os.Build
import android.os.IBinder
import androidx.media3.common.Player

/** Keeps audio and system transport controls alive while Flutter is backgrounded. */
class PlaybackService : Service() {
    companion object { var instance: PlaybackService? = null }
    private lateinit var session: MediaSession
    private var lastNotificationAt = 0L
    private var lastSessionAt = 0L
    private var lastState = -1
    private var lastSpeed = -1f
    private var lastTitle = ""
    private var lastDuration = -1L
    override fun onCreate() {
        super.onCreate(); instance = this
        if (Build.VERSION.SDK_INT >= 26) (getSystemService(NOTIFICATION_SERVICE) as NotificationManager)
            .createNotificationChannel(NotificationChannel("playback", "播放", NotificationManager.IMPORTANCE_LOW))
        session = MediaSession(this, "StrmAction").apply {
            setCallback(object : MediaSession.Callback() {
                override fun onPlay() { UnifiedPlayer.active?.command("play", null) }
                override fun onPause() { UnifiedPlayer.active?.command("pause", null) }
                override fun onSeekTo(pos: Long) { UnifiedPlayer.active?.command("seek", pos) }
                override fun onStop() { UnifiedPlayer.active?.command("pause", null) }
            })
            isActive = true
        }
        startForeground(1, notification())
    }
    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        when (intent?.action) {
            "play" -> UnifiedPlayer.active?.command("play", null)
            "pause" -> UnifiedPlayer.active?.command("pause", null)
        }
        updateSession()
        return START_NOT_STICKY
    }
    private fun notification(): Notification {
        val engine = UnifiedPlayer.active
        val playing = engine?.exo?.isPlaying == true
        val control = PendingIntent.getService(this, if (playing) 2 else 3,
            Intent(this, PlaybackService::class.java).setAction(if (playing) "pause" else "play"), PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
        val open = PendingIntent.getActivity(this, 1, Intent(this, MainActivity::class.java), PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
        val builder = if (Build.VERSION.SDK_INT >= 26) Notification.Builder(this, "playback") else Notification.Builder(this)
        return builder.setContentTitle(engine?.title ?: "StrmAction").setSmallIcon(android.R.drawable.ic_media_play)
            .setContentIntent(open).setOngoing(playing).setVisibility(Notification.VISIBILITY_PUBLIC)
            .setStyle(Notification.MediaStyle().setMediaSession(session.sessionToken).setShowActionsInCompactView(0))
            .addAction(Notification.Action.Builder(if (playing) android.R.drawable.ic_media_pause else android.R.drawable.ic_media_play, if (playing) "暂停" else "播放", control).build()).build()
    }
    fun updateSession() {
        val engine = UnifiedPlayer.active ?: return
        val player = engine.exo ?: return
        val state = when { player.isPlaying -> PlaybackState.STATE_PLAYING; player.playbackState == Player.STATE_BUFFERING -> PlaybackState.STATE_BUFFERING; else -> PlaybackState.STATE_PAUSED }
        val now = android.os.SystemClock.elapsedRealtime()
        val speed = player.playbackParameters.speed
        val changed = state != lastState || speed != lastSpeed
        if (!changed && now - lastSessionAt < 1000) return
        lastSessionAt = now; lastState = state; lastSpeed = speed
        val duration = player.duration.coerceAtLeast(0)
        if (lastTitle != engine.title || lastDuration != duration) {
            lastTitle = engine.title; lastDuration = duration
            session.setMetadata(MediaMetadata.Builder().putString(MediaMetadata.METADATA_KEY_TITLE, engine.title)
                .putLong(MediaMetadata.METADATA_KEY_DURATION, duration).build())
        }
        session.setPlaybackState(PlaybackState.Builder().setActions(PlaybackState.ACTION_PLAY or PlaybackState.ACTION_PAUSE or PlaybackState.ACTION_SEEK_TO or PlaybackState.ACTION_PLAY_PAUSE)
            .setState(state, player.currentPosition, player.playbackParameters.speed).build())
        if (changed || now - lastNotificationAt >= 1000) { (getSystemService(NOTIFICATION_SERVICE) as NotificationManager).notify(1, notification()); lastNotificationAt = now }
    }
    override fun onBind(intent: Intent?): IBinder? = null
    override fun onDestroy() {
        instance = null; session.isActive = false; session.release(); super.onDestroy()
    }
}
