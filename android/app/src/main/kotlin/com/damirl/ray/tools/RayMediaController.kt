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
import com.damirl.ray.BuildConfig
import com.damirl.ray.audio.AudioPlaybackService

// What the phone plays: the now-playing info, play/pause/skip through the player's media session (YouTube Music in
// Brave shows one with background play), and phone_play_music, which opens a YouTube Music link in Brave.  None of
// it needs the phone unlocked
class RayMediaController(private val context: Context) {

    companion object {
        private const val TAG = "RayMedia"

        @Volatile private var resumeAfterSpeech = false

        /** Ray starts talking: if Brave plays, it is resumed once he is done (his voice takes the audio meanwhile). */
        fun pauseForSpeech(context: Context) {
            val media = RayMediaController(context.applicationContext)
            if (!media.bravePlaying() || resumeAfterSpeech) return
            resumeAfterSpeech = true
            Thread({
                media.waitForQuiet()
                resumeAfterSpeech = false
                if (!media.bravePlaying()) {
                    media.braveSession()?.transportControls?.play()
                    Log.d(TAG, "after speech: resumed Brave, playing=${media.waitForBrave(3_000)}")
                }
            }, "RayMusicResume").start()
        }
        const val BRAVE = "com.brave.browser"
        // the player's Play button on music.youtube.com, in the order tried: "Play" starts it; its "Start playback"
        // hint (the only label on a fresh page) is a fallback (a tap on it did nothing on 2026-11-03 21:34)
        private val PLAY_LABELS = listOf("play", "reproduciraj", "pokreni", "play video", "start playback")
        // the model tends to explain a music command at length; the user wants a few words
        const val SHORT = "Say only that sentence to the user, word for word: no greeting, no comment, no offer."
        // the tool said "Started" on a locked phone (the helmet, the phone in a pocket) and Ray told the user it
        // played; it starts only once the phone is unlocked (Play is pressed on screen)
        const val LOCKED_START = "Not playing yet: the phone is locked, and Brave starts it only once the user " +
            "unlocks the phone (Ray presses Play on the screen; up to 5 minutes). Say only this to the user: " +
            "\"It starts as soon as you unlock the phone.\" (With the helmet set as a trusted device, Ray can start " +
            "songs without that.)"
        private const val AUTOSTART_MS = 300_000L            // long enough to take the phone out and unlock it
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
        val locked = (context.getSystemService(Context.KEYGUARD_SERVICE) as? KeyguardManager)?.isDeviceLocked ?: true
        return try {
            context.startActivity(intent)
            Log.d(TAG, "playUrl: opened in Brave (locked=$locked)")
            Thread({ autostart() }, "RayMusicStart").start()
            // Brave allowed to autoplay (its --autoplay-policy line, 2026-11-03) starts the song itself, locked
            // too: only when it doesn't is the user told to unlock
            if (locked && !waitForBrave(12_000)) LOCKED_START else "Started."
        } catch (e: Exception) {
            Log.e(TAG, "Brave could not be opened", e)
            "Error: Brave could not be opened (${e.message}). Is it installed?"
        }
    }

    // Brave doesn't autoplay a page another app opened (it waits for a tap), so Ray taps Play himself (his screen
    // reading service): once he has finished talking (and no call is on), the phone is
    // unlocked and Brave's page shows the button.  Until then, or until Brave plays by itself, he waits (90 s at most)
    private fun autostart() {
        val keyguard = context.getSystemService(Context.KEYGUARD_SERVICE) as? KeyguardManager
        val wasShown = com.damirl.ray.MainActivity.shown        // typed in Ray's app: back to it once it plays
        val end = SystemClock.uptimeMillis() + AUTOSTART_MS
        // the tool runs before Ray says his answer: wait for it to start (10 s at most; a typed chat may have none)
        // and to end, so the song doesn't start under his voice
        waitForQuiet()                                        // he says his answer first, the page loads meanwhile
        val speaking = AudioPlaybackService.isSpeakingState
        var tries = 0
        var unlocked = false
        while (SystemClock.uptimeMillis() < end) {
            if (bravePlaying()) { done(wasShown, unlocked); return }
            val quiet = !speaking.value && !inCall() && com.damirl.ray.audio.BluetoothMic.idle()
            val locked = keyguard?.isDeviceLocked ?: true
            // a trusted phone (the helmet connected: Smart Lock) shows its lock screen without needing the PIN:
            // Ray dismisses it to reach the Play button, and locks it again once the music plays
            if (quiet && !locked && !unlocked && RayUnlockActivity.dismissable(context)) {
                unlocked = RayUnlockActivity.dismiss(context)
                Log.d(TAG, "autostart: trusted lock screen dismissed=$unlocked")
            }
            if (quiet && !locked && RayAccessibilityService.tapLabelled(BRAVE, PLAY_LABELS)) {
                if (waitForBrave(1_500)) {
                    done(wasShown, unlocked)
                    return
                }
            }
            if (BuildConfig.DEBUG && ++tries % 20 == 1) {
                Log.d(TAG, "autostart: quiet=$quiet locked=$locked; Brave shows: " + RayAccessibilityService.labelsOf(BRAVE))
            }
            Thread.sleep(250)
        }
        Log.d(TAG, "autostart: gave up (no Play button, phone locked or still busy)")
        if (unlocked) RayAccessibilityService.lockScreen()
    }

    // the music plays: back to Ray's app if it was on screen, or the phone locked again if Ray unlocked it
    private fun done(wasShown: Boolean, unlocked: Boolean) {
        if (unlocked) {
            Thread.sleep(500)
            Log.d(TAG, "music plays: locking the phone again=${RayAccessibilityService.lockScreen()}")
        } else if (wasShown) backToRay()
    }

    // Brave in the background freezes a paused page, and then its session ignores play; Brave on screen wakes it
    // up.  So: play; if nothing plays after 2.5 s, Brave comes to the front, play again (or tap the player's Play
    // button), and Ray's app comes back if it was on screen.  Blocking, at most about 10 s
    private fun resumeBrave(session: MediaController): String {
        session.transportControls.play()
        if (waitForBrave(2_500)) return "Playing. $SHORT"
        val wasShown = com.damirl.ray.MainActivity.shown
        val keyguard = context.getSystemService(Context.KEYGUARD_SERVICE) as? KeyguardManager
        if (keyguard?.isDeviceLocked != false) {
            return "Error: Brave didn't resume while the phone is locked (it freezes a paused page). Ask the user " +
                "to unlock the phone, then try again."
        }
        val unlocked = RayUnlockActivity.dismissable(context) && RayUnlockActivity.dismiss(context)
        if (com.damirl.ray.assistant.VoiceDrawerController.closeIfOpen()) Thread.sleep(800)   // it covers Brave
        val launch = context.packageManager.getLaunchIntentForPackage(BRAVE)
            ?: return "Error: Brave could not be opened."
        context.startActivity(launch.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
        Thread.sleep(1_500)
        braveSession()?.transportControls?.play()
        var playing = waitForBrave(2_000)
        if (!playing && RayAccessibilityService.tapLabelled(BRAVE, PLAY_LABELS)) playing = waitForBrave(2_500)
        Log.d(TAG, "resumeBrave: woke Brave, playing=$playing")
        if (playing || unlocked) done(wasShown, unlocked)
        return if (playing) "Playing. $SHORT" else "Error: Brave didn't resume. It is on the screen now; ask the " +
            "user to press play there."
    }

    // until Ray has said his answer (it starts within 8 s of the tool, or there is none: a typed chat) and the
    // helmet's call link is handed back: music started earlier played under his voice, and the switch back from
    // the call link stopped it
    private fun waitForQuiet(maxMs: Long = 120_000) {
        val speaking = AudioPlaybackService.isSpeakingState
        val end = SystemClock.uptimeMillis() + maxMs
        val answerBy = SystemClock.uptimeMillis() + 8_000
        while (!speaking.value && SystemClock.uptimeMillis() < answerBy) Thread.sleep(100)
        while ((speaking.value || inCall()) && SystemClock.uptimeMillis() < end) Thread.sleep(100)
        // said: the drawer has done its job, and it covers Brave (Ray's screen reading saw no Play button under it)
        com.damirl.ray.assistant.VoiceDrawerController.closeIfOpen()
        while (!com.damirl.ray.audio.BluetoothMic.idle() && SystemClock.uptimeMillis() < end) Thread.sleep(100)
        Thread.sleep(300)                                     // the helmet switches back to music
    }

    private fun waitForBrave(ms: Long): Boolean {
        val end = SystemClock.uptimeMillis() + ms
        while (SystemClock.uptimeMillis() < end) {
            if (bravePlaying()) return true
            Thread.sleep(150)
        }
        return bravePlaying()
    }

    fun braveSession(): MediaController? = try {
        sessionManager?.getActiveSessions(ComponentName(context, RayNotificationListenerService::class.java))
            .orEmpty().firstOrNull { it.packageName == BRAVE }
    } catch (_: SecurityException) {
        null
    }

    private fun backToRay() {
        context.startActivity(Intent(context, com.damirl.ray.MainActivity::class.java)
            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_REORDER_TO_FRONT))
    }

    // a call (no music over it)
    private fun inCall(): Boolean = audioManager?.mode.let {
        it == AudioManager.MODE_IN_CALL || it == AudioManager.MODE_IN_COMMUNICATION
    }

    fun bravePlaying(): Boolean = try {
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

            // not "any audio is active": Ray's own voice and a headset's call link count as that ("something is
            // playing" while nothing did)
            "No music is playing or paused on the phone."
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
            val starts = normAction == "play" ||
                (normAction == "play_pause" && active.playbackState?.state != PlaybackState.STATE_PLAYING)
            if (starts && active.packageName == BRAVE) {
                // after Ray's answer, not under it (see waitForQuiet)
                Thread({ waitForQuiet(); Log.d(TAG, "deferred play: ${resumeBrave(active)}") }, "RayMusicPlay").start()
                return "Playing. $SHORT"           // it starts once he has said it
            }
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
            val done = when (normAction) {
                "next", "skip" -> "Skipped to the next song"
                "previous", "prev" -> "Back to the previous song"
                "pause", "stop" -> "Paused"
                else -> "Playing"
            }
            return "$done. $SHORT"
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
        return "Done: $normAction. $SHORT"
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
