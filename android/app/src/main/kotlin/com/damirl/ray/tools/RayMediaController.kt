package com.damirl.ray.tools

import android.content.ComponentName
import android.content.Context
import android.media.AudioManager
import android.media.session.MediaController
import android.media.session.MediaSessionManager
import android.media.session.PlaybackState
import android.os.SystemClock
import android.util.Log
import android.view.KeyEvent

class RayMediaController(private val context: Context) {

    companion object {
        private const val TAG = "RayMedia"
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

            for (controller in controllers) {
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

            if (controllers.isNotEmpty()) {
                val active = controllers.firstOrNull { it.playbackState?.state == PlaybackState.STATE_PLAYING }
                    ?: controllers.first()

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
                return "Executed media action '$normAction'."
            }
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
