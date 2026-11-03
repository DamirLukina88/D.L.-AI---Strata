package com.damirl.ray.tools

import android.app.KeyguardManager
import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.net.Uri
import android.provider.Browser
import android.media.AudioManager
import android.media.session.MediaController
import android.media.session.MediaSessionManager
import android.media.session.PlaybackState
import android.os.SystemClock
import android.util.Log
import android.view.KeyEvent

// What the phone plays: the now-playing info, play/pause/skip through the player's media session (YouTube Music in
// Brave shows one with background play), and phone_play_music, which opens a YouTube Music link in Brave.  None of
// it needs the phone unlocked
class RayMediaController(private val context: Context) {

    companion object {
        private const val TAG = "RayMedia"
        const val BRAVE = "com.brave.browser"
        // the player's Play button on music.youtube.com (English and Croatian page language)
        private val PLAY_LABELS = setOf("play", "reproduciraj", "pokreni", "play video")
        private const val AUTOSTART_MS = 90_000L
        private val PLAYABLE = Regex("""^https://(music\.|www\.|m\.)?youtube\.com/.*|^https://youtu\.be/.*""")
    }

    /** Opens [url] (a YouTube Music song or the Liked songs, found by phone_mcp.py) in Brave, where it plays. */
    fun playUrl(url: String): String {
        if (!PLAYABLE.matches(url)) return "Error: only music.youtube.com or youtube.com links can be played."
        val intent = Intent(Intent.ACTION_VIEW, Uri.parse(url))
            .setPackage(BRAVE)
            // the same app id each time: Brave reuses Ray's tab instead of opening a new one per song
            .putExtra(Browser.EXTRA_APPLICATION_ID, context.packageName)
            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        return try {
            context.startActivity(intent)
            Log.d(TAG, "playUrl: opened in Brave")
            Thread({ autostart() }, "RayMusicStart").start()
            "Opened it in YouTube Music (Brave); it starts as soon as you're done talking."
        } catch (e: Exception) {
            Log.e(TAG, "Brave could not be opened", e)
            "Error: Brave could not be opened (${e.message}). Is it installed?"
        }
    }

    // Brave doesn't autoplay a page another app opened (it waits for a tap), so Ray taps Play himself (his screen
    // reading service): once nothing plays any more (he has finished talking, the old song stopped), the phone is
    // unlocked and Brave's page shows the button.  Until then, or until Brave plays by itself, he waits (90 s at most)
    private fun autostart() {
        val keyguard = context.getSystemService(Context.KEYGUARD_SERVICE) as? KeyguardManager
        val end = SystemClock.uptimeMillis() + AUTOSTART_MS
        Thread.sleep(2_500)                                   // the page loads
        while (SystemClock.uptimeMillis() < end) {
            if (bravePlaying()) return
            val quiet = audioManager?.isMusicActive != true
            val locked = keyguard?.isDeviceLocked ?: true
            if (quiet && !locked && RayAccessibilityService.tapLabelled(BRAVE, PLAY_LABELS)) {
                Thread.sleep(2_000)
                if (bravePlaying()) return
            }
            Thread.sleep(1_000)
        }
        Log.d(TAG, "autostart: gave up (no Play button, phone locked or still busy)")
    }

    private fun bravePlaying(): Boolean = try {
        val component = ComponentName(context, RayNotificationListenerService::class.java)
        sessionManager?.getActiveSessions(component).orEmpty()
            .any { it.packageName == BRAVE && it.playbackState?.state == PlaybackState.STATE_PLAYING }
    } catch (_: SecurityException) {
        false
    }

    // the session to control: the one playing, else Brave's, else any that has a song; never Ray's own (his voice)
    private fun target(controllers: List<MediaController>): MediaController? {
        val others = controllers.filter { it.packageName != context.packageName }
        return others.firstOrNull { it.playbackState?.state == PlaybackState.STATE_PLAYING }
            ?: others.firstOrNull { it.packageName == BRAVE }
            ?: others.firstOrNull { it.metadata?.getString(android.media.MediaMetadata.METADATA_KEY_TITLE) != null }
    }

    private val audioManager = context.getSystemService(Context.AUDIO_SERVICE) as? AudioManager
    private val sessionManager = context.getSystemService(Context.MEDIA_SESSION_SERVICE) as? MediaSessionManager

    /**
     * Get active media session metadata (title, artist, and playback state).
     */
    fun getNowPlaying(): String {
        return try {
            val component = ComponentName(context, RayNotificationListenerService::class.java)
            val controllers = sessionManager?.getActiveSessions(component) ?: emptyList()

            for (controller in listOfNotNull(target(controllers))) {
                val metadata = controller.metadata
                val state = controller.playbackState

                val title = metadata?.getString(android.media.MediaMetadata.METADATA_KEY_TITLE)
                val artist = metadata?.getString(android.media.MediaMetadata.METADATA_KEY_ARTIST)
                val isPlaying = state?.state == PlaybackState.STATE_PLAYING

                if (!title.isNullOrBlank()) {
                    val status = if (isPlaying) "Playing" else "Paused"
                    val artistStr = if (!artist.isNullOrBlank()) " by $artist" else ""
                    val pkg = controller.packageName
                    val appName = when {
                        pkg.contains("spotify") -> "Spotify"
                        pkg.contains("youtube") -> "YouTube"
                        pkg == BRAVE -> "YouTube Music in Brave"
                        else -> pkg
                    }
                    return "$status: '$title'$artistStr on $appName."
                }
            }

            if (audioManager?.isMusicActive == true) {
                return "Media is currently playing, but metadata details could not be read."
            }

            "No media is currently playing."
        } catch (e: SecurityException) {
            Log.w(TAG, "Notification listener permission needed for MediaSessionManager: ${e.message}")
            if (audioManager?.isMusicActive == true) {
                "Media is playing (detailed song metadata requires Notification Access in settings)."
            } else {
                "No active media playing."
            }
        } catch (e: Exception) {
            Log.e(TAG, "Error getting now playing", e)
            "Error inspecting media: ${e.message}"
        }
    }

    /**
     * Control playback (play, pause, play_pause, next, previous, stop).
     */
    fun controlMedia(action: String): String {
        val normAction = action.lowercase().trim()

        try {
            val component = ComponentName(context, RayNotificationListenerService::class.java)
            val controllers = sessionManager?.getActiveSessions(component) ?: emptyList()

            val active = target(controllers)
            if (active == null) {
                return "Nothing is playing or paused. To start music, use phone_play_music (without a query it " +
                    "plays the Liked songs)."
            }
            val controls = active.transportControls
            when (normAction) {
                "play" -> controls.play()
                "pause" -> controls.pause()
                "play_pause" -> {
                    if (active.playbackState?.state == PlaybackState.STATE_PLAYING) {
                        controls.pause()
                    } else {
                        controls.play()
                    }
                }
                "next", "skip" -> controls.skipToNext()
                "previous", "prev" -> controls.skipToPrevious()
                "stop" -> controls.stop()
                else -> controls.play()
            }
            Log.d(TAG, "controlMedia: dispatched '$normAction' via TransportControls to ${active.packageName}")
            return "Done: $normAction (${if (active.packageName == BRAVE) "YouTube Music in Brave" else active.packageName})."
        } catch (e: SecurityException) {
            Log.d(TAG, "Falling back to AudioManager key events for media control: ${e.message}")
        } catch (e: Exception) {
            Log.w(TAG, "Transport controls failed, using KeyEvent fallback", e)
        }

        // Fallback using KeyEvent via AudioManager
        val keyCode = when (normAction) {
            "play" -> KeyEvent.KEYCODE_MEDIA_PLAY
            "pause" -> KeyEvent.KEYCODE_MEDIA_PAUSE
            "play_pause" -> KeyEvent.KEYCODE_MEDIA_PLAY_PAUSE
            "next" -> KeyEvent.KEYCODE_MEDIA_NEXT
            "previous" -> KeyEvent.KEYCODE_MEDIA_PREVIOUS
            "stop" -> KeyEvent.KEYCODE_MEDIA_STOP
            else -> KeyEvent.KEYCODE_MEDIA_PLAY_PAUSE
        }

        sendMediaKeyEvent(keyCode)
        return "Executed media action '$normAction'."
    }

    private fun sendMediaKeyEvent(keyCode: Int) {
        val am = audioManager ?: return
        val eventTime = SystemClock.uptimeMillis()

        val downEvent = KeyEvent(eventTime, eventTime, KeyEvent.ACTION_DOWN, keyCode, 0)
        am.dispatchMediaKeyEvent(downEvent)

        val upEvent = KeyEvent(eventTime, eventTime, KeyEvent.ACTION_UP, keyCode, 0)
        am.dispatchMediaKeyEvent(upEvent)
    }
}
