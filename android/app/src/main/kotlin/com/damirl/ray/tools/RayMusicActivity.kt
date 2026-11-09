package com.damirl.ray.tools

import android.app.Activity
import android.content.Context
import android.content.Intent
import android.graphics.Color
import android.graphics.Typeface
import android.graphics.drawable.GradientDrawable
import android.media.AudioManager
import android.os.Build
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.os.PowerManager
import android.os.SystemClock
import android.support.v4.media.MediaMetadataCompat
import android.support.v4.media.session.MediaSessionCompat
import android.support.v4.media.session.PlaybackStateCompat
import android.util.Log
import android.util.TypedValue
import android.view.Gravity
import android.view.KeyEvent
import android.view.ViewGroup
import android.view.WindowManager
import android.widget.LinearLayout
import android.widget.TextView
import com.damirl.ray.MainActivity
import com.damirl.ray.assistant.VoiceDrawerController
import com.damirl.ray.audio.AudioPlaybackService
import com.damirl.ray.audio.BluetoothMic
import com.damirl.ray.audio.MediaButtonHandler
import com.damirl.ray.audio.VoiceTrace
import org.mozilla.geckoview.AllowOrDeny
import org.mozilla.geckoview.GeckoResult
import org.mozilla.geckoview.GeckoRuntime
import org.mozilla.geckoview.GeckoRuntimeSettings
import org.mozilla.geckoview.GeckoSession
import org.mozilla.geckoview.GeckoSessionSettings
import org.mozilla.geckoview.GeckoView
import org.mozilla.geckoview.MediaSession

/**
 * In-app lock-screen music player (`showWhenLocked`, `turnScreenOn`): plays YouTube Music links over the lock screen.
 *
 * Runs on GeckoView (Mozilla's engine), not a WebView: Google refuses sign-in inside an app's WebView ("This browser
 * or app may not be secure", 2026-11-09), so a WebView player could only play signed out.  GeckoView keeps a normal
 * browser profile in the app's data, so the YouTube Music sign-in stays across starts.  Playback is driven through
 * the page's own media session (the play/pause/next/previous handlers YouTube Music registers), not injected scripts.
 */
class RayMusicActivity : Activity() {

    companion object {
        private const val TAG = "RayMusicPlayer"
        private const val EXTRA_URL = "extra_url"
        // the sites the player may show: YouTube (Music) and Google's sign-in and consent pages
        private val ALLOWED_SITES = listOf("youtube.com", "youtu.be", "google.com", "google.hr", "googleusercontent.com")

        // one engine per process (GeckoRuntime.create may be called only once)
        @Volatile private var runtime: GeckoRuntime? = null

        @Volatile private var instance: RayMusicActivity? = null
        @Volatile var isCurrentlyPlaying: Boolean = false
            private set
        @Volatile var currentTitle: String = ""
            private set
        @Volatile var currentArtist: String = ""
            private set
        @Volatile private var holdForSpeech: Boolean = false
        @Volatile private var speechPaused: Boolean = false
        @Volatile private var quietWaitGeneration: Int = 0

        // A voice turn ("Ok Ray" or the headset double tap) pauses the player until the turn is over, then the song
        // continues: right away when nothing was asked, ~1 s after Ray's answer, and not at all when the user told
        // him to pause or stop (the user's rules, 2026-11-09).  Asking for another song, next or previous plays.
        @Volatile private var turnHold = false
        @Volatile private var turnResume = false           // play when the turn is over
        @Volatile private var turnGen = 0
        @Volatile private var releaseAfterSpeech = false

        fun isActive(): Boolean = instance != null

        fun isPlaying(): Boolean = instance != null && isCurrentlyPlaying

        // a music video kept the screen on: the page holds the engine's 'video-playing' lock and asks for a
        // screen wake lock ('screen'), so the phone never slept in a pocket (measured 2026-11-09).  Both are off
        private const val GECKO_PREFS = """prefs:
  media.video-wakelock: false
  dom.screenwakelock.enabled: false
"""

        private fun runtime(context: Context): GeckoRuntime = runtime ?: synchronized(this) {
            runtime ?: run {
                val config = java.io.File(context.filesDir, "geckoview-config.yaml")
                runCatching { if (!config.exists() || config.readText() != GECKO_PREFS) config.writeText(GECKO_PREFS) }
                GeckoRuntime.create(
                    context.applicationContext,
                    GeckoRuntimeSettings.Builder()
                        .configFilePath(config.absolutePath)
                        .consoleOutput(true)            // the extension's "[ray-audio]" lines (tag GeckoConsole)
                        .build()
                ).also { rt ->
                    // plays the song version instead of the music video (assets/web_extensions/raymusic)
                    rt.webExtensionController
                        .ensureBuiltIn("resource://android/assets/web_extensions/raymusic/", "raymusic@damirl.com")
                        .accept(
                            { Log.d(TAG, "audio-only extension ready") },
                            { e -> Log.w(TAG, "audio-only extension failed", e) }
                        )
                }
            }.also { runtime = it }
        }

        fun open(context: Context, url: String): String {
            return try {
                turnHold = false                                // a new song waits for Ray on its own (below)
                turnResume = false
                holdForSpeech = true
                speechPaused = false
                val gen = ++quietWaitGeneration
                val intent = Intent(context, RayMusicActivity::class.java).apply {
                    putExtra(EXTRA_URL, url)
                    addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_SINGLE_TOP)
                }
                context.startActivity(intent)
                Log.d(TAG, "Opened RayMusicActivity for $url")
                VoiceTrace.event("music_player_open", "url" to url.take(80))

                // Wait until Ray finishes speaking his confirmation (and the helmet call link is idle) before
                // starting playback, so the song doesn't play under his voice or stop when HFP closes.
                Thread({
                    waitForQuiet(context)
                    if (gen == quietWaitGeneration) {
                        holdForSpeech = false
                        instance?.kickPlayback()
                    }
                }, "RayMusicQuietWait").start()
                "Started."
            } catch (e: Exception) {
                Log.e(TAG, "Could not open RayMusicActivity", e)
                "Error: Music player could not be opened (${e.message})."
            }
        }

        fun setSpeechPaused(paused: Boolean) {
            speechPaused = paused
            val act = instance ?: return
            act.mainHandler.post {
                if (paused) {
                    act.doControl("pause", byUser = false)
                } else {
                    holdForSpeech = false
                    act.doControl("play", byUser = false)
                }
            }
        }

        fun getNowPlayingStatus(): String? {
            if (instance == null) return null
            val title = currentTitle.ifBlank { "YouTube Music" }
            val artistStr = if (currentArtist.isNotBlank()) " by $currentArtist" else ""
            val status = if (isCurrentlyPlaying) "Playing" else "Paused"
            return "$status: '$title'$artistStr on Ray Music Player."
        }

        fun control(action: String): String {
            val act = instance ?: return "Nothing is playing or paused."
            val norm = action.lowercase().trim()
            act.mainHandler.post {
                if (norm == "stop") {
                    act.doControl("pause", byUser = true)
                    act.finish()
                } else {
                    act.doControl(norm, byUser = true)
                }
            }
            val done = when (norm) {
                "next", "skip" -> "Skipped to the next song"
                "previous", "prev" -> "Back to the previous song"
                "pause", "stop" -> "Paused"
                else -> "Playing"
            }
            return "$done. ${RayMediaController.SHORT}"
        }

        /** "Ok Ray" was heard or the headset was double-tapped: the song pauses while Ray listens and answers. */
        fun holdForTurn(context: Context, source: String) {
            val act = instance ?: return
            val gen = ++turnGen
            releaseAfterSpeech = false
            if (!turnHold) {
                turnHold = true
                turnResume = isCurrentlyPlaying
            }
            VoiceTrace.event("music_turn_hold", "source" to source, "resume" to turnResume)
            act.mainHandler.post { act.doControl("pause", byUser = false) }
            // a turn whose drawer never opened would keep the song paused for good
            Thread({
                Thread.sleep(10_000)
                if (gen == turnGen && turnHold && VoiceDrawerController.closeOpen == null) {
                    releaseTurn(context, spoke = false, why = "no drawer")
                }
            }, "RayMusicTurnGuard").start()
        }

        /** The drawer listens again: a release already on its way is dropped. */
        fun continueTurn() {
            if (!turnHold) return
            turnGen++
            releaseAfterSpeech = false
        }

        /** The turn is over ([spoke]: Ray is saying his answer): the song continues once he is done. */
        fun releaseTurn(context: Context, spoke: Boolean, why: String) {
            if (!turnHold) return
            val gen = ++turnGen
            val afterSpeech = spoke || releaseAfterSpeech
            releaseAfterSpeech = afterSpeech
            Thread({
                val speaking = AudioPlaybackService.isSpeakingState
                val am = context.getSystemService(Context.AUDIO_SERVICE) as? AudioManager
                val end = SystemClock.uptimeMillis() + 120_000L
                if (afterSpeech) {
                    val by = SystemClock.uptimeMillis() + 3_500L     // his voice starts after it is fetched
                    while (!speaking.value && SystemClock.uptimeMillis() < by) Thread.sleep(100)
                }
                while ((speaking.value || inCall(am)) && SystemClock.uptimeMillis() < end) Thread.sleep(100)
                while (!BluetoothMic.idle() && SystemClock.uptimeMillis() < end) Thread.sleep(100)
                Thread.sleep(if (afterSpeech) 1_000L else 300L)
                if (gen != turnGen || !turnHold) return@Thread
                turnHold = false
                releaseAfterSpeech = false
                val resume = turnResume
                turnResume = false
                VoiceTrace.event("music_turn_release", "why" to why, "resume" to resume)
                val act = instance ?: return@Thread
                if (resume) act.mainHandler.post { act.doControl("play", byUser = false) }
            }, "RayMusicTurnRelease").start()
        }

        private fun waitForQuiet(context: Context, maxMs: Long = 45_000L) {
            val speaking = AudioPlaybackService.isSpeakingState
            val am = context.getSystemService(Context.AUDIO_SERVICE) as? AudioManager
            val end = SystemClock.uptimeMillis() + maxMs
            // Wait up to 3.5 s for Ray's TTS answer to begin (a typed chat or PC turn may have none on the phone)
            val answerBy = SystemClock.uptimeMillis() + 3_500L
            while (!speaking.value && SystemClock.uptimeMillis() < answerBy) {
                Thread.sleep(100)
            }
            while ((speaking.value || inCall(am)) && SystemClock.uptimeMillis() < end) {
                Thread.sleep(100)
            }
            VoiceDrawerController.closeIfOpen()
            while (!BluetoothMic.idle() && SystemClock.uptimeMillis() < end) {
                Thread.sleep(100)
            }
            Thread.sleep(250)
        }

        private fun inCall(am: AudioManager?): Boolean = am?.mode.let {
            it == AudioManager.MODE_IN_CALL || it == AudioManager.MODE_IN_COMMUNICATION
        }
    }

    private val mainHandler = Handler(Looper.getMainLooper())
    private var geckoSession: GeckoSession? = null
    private var pageMedia: MediaSession? = null      // the page's media session (YouTube Music's player)
    private var canGoBack = false
    private var userPaused = false
    private var pendingAction: String? = null        // asked before the page's media session existed
    private var statusView: TextView? = null
    private var playPauseBtn: TextView? = null
    private var wakeLock: PowerManager.WakeLock? = null

    // the player's own media session: Bluetooth headsets, cars and the lock screen send their play/pause/next/
    // previous here.  Without one the buttons reached Ray's voice session, which ignored them
    private var session: MediaSessionCompat? = null
    private var sessionPlaying: Boolean? = null
    private var sessionTitle = ""
    private var sessionArtist = ""

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        instance = this

        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O_MR1) {
            setShowWhenLocked(true)
            setTurnScreenOn(true)
        }
        @Suppress("DEPRECATION")
        window.addFlags(
            WindowManager.LayoutParams.FLAG_SHOW_WHEN_LOCKED or
                WindowManager.LayoutParams.FLAG_TURN_SCREEN_ON or
                WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON or
                WindowManager.LayoutParams.FLAG_ALLOW_LOCK_WHILE_SCREEN_ON
        )

        val pm = getSystemService(Context.POWER_SERVICE) as? PowerManager
        wakeLock = pm?.newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "RayAssistant:MusicPlayerWakeLock")?.apply {
            setReferenceCounted(false)
            acquire(4 * 60 * 60 * 1000L) // up to 4 hours of music playback
        }

        setupUi()
        setupSession()
        handleIntent(intent)
    }

    override fun onNewIntent(intent: Intent?) {
        super.onNewIntent(intent)
        setIntent(intent)
        handleIntent(intent)
    }

    // the engine would treat a stopped activity (screen off, locked) as a hidden tab; the song must keep playing
    override fun onStop() {
        super.onStop()
        geckoSession?.setActive(true)
    }

    @Suppress("OVERRIDE_DEPRECATION")
    override fun onBackPressed() {
        if (canGoBack) geckoSession?.goBack() else @Suppress("DEPRECATION") super.onBackPressed()
    }

    private fun handleIntent(intent: Intent?) {
        val url = intent?.getStringExtra(EXTRA_URL)?.trim().orEmpty()
        if (url.isNotEmpty()) {
            userPaused = false
            window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)   // until the song starts
            statusView?.text = if (holdForSpeech) "Preparing music…" else "Loading music…"
            geckoSession?.loadUri(url)
        }
    }

    private fun setupUi() {
        val root = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setBackgroundColor(Color.parseColor("#0B0D10"))
            layoutParams = ViewGroup.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.MATCH_PARENT
            )
        }

        // Top control bar (works on lock screen without unlocking)
        val topBar = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER_VERTICAL
            setBackgroundColor(Color.parseColor("#141820"))
            setPadding(dp(12), dp(36), dp(12), dp(10))
        }

        val titleCol = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            layoutParams = LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f)
        }
        titleCol.addView(TextView(this).apply {
            text = "RAY LOCK-SCREEN PLAYER"
            setTextColor(Color.parseColor("#7C8B9E"))
            setTextSize(TypedValue.COMPLEX_UNIT_SP, 10f)
            typeface = Typeface.DEFAULT_BOLD
        })
        statusView = TextView(this).apply {
            text = "Loading YouTube Music…"
            setTextColor(Color.parseColor("#E8EEF5"))
            setTextSize(TypedValue.COMPLEX_UNIT_SP, 14f)
            typeface = Typeface.DEFAULT_BOLD
            maxLines = 1
        }
        titleCol.addView(statusView)
        topBar.addView(titleCol)

        fun makeButton(label: String, bgHex: String = "#232A36", onClick: () -> Unit): TextView {
            return TextView(this).apply {
                text = label
                setTextColor(Color.parseColor("#E8EEF5"))
                setTextSize(TypedValue.COMPLEX_UNIT_SP, 12f)
                typeface = Typeface.DEFAULT_BOLD
                gravity = Gravity.CENTER
                background = GradientDrawable().apply {
                    setColor(Color.parseColor(bgHex))
                    cornerRadius = dp(8).toFloat()
                }
                setPadding(dp(10), dp(7), dp(10), dp(7))
                layoutParams = LinearLayout.LayoutParams(
                    ViewGroup.LayoutParams.WRAP_CONTENT,
                    ViewGroup.LayoutParams.WRAP_CONTENT
                ).apply { marginStart = dp(6) }
                setOnClickListener { onClick() }
            }
        }

        topBar.addView(makeButton("⏮") { doControl("previous", byUser = true) })
        playPauseBtn = makeButton("⏯") { doControl("play_pause", byUser = true) }.also { topBar.addView(it) }
        topBar.addView(makeButton("⏭") { doControl("next", byUser = true) })
        topBar.addView(makeButton("Ray") {
            startActivity(Intent(this, MainActivity::class.java).apply {
                addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_REORDER_TO_FRONT)
            })
        })
        topBar.addView(makeButton("✕", "#3A1D24") {
            doControl("pause", byUser = true)
            finish()
        })
        root.addView(
            topBar,
            LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT)
        )

        // the mobile site (the user's choice, 2026-11-09); its "open the app" links are refused in onLoadRequest
        val gs = GeckoSession(
            GeckoSessionSettings.Builder()
                .usePrivateMode(false)                                   // keep the sign-in
                .userAgentMode(GeckoSessionSettings.USER_AGENT_MODE_MOBILE)
                .viewportMode(GeckoSessionSettings.VIEWPORT_MODE_MOBILE)
                .build()
        )
        gs.permissionDelegate = object : GeckoSession.PermissionDelegate {
            // songs start without a tap (the lock screen has nobody to tap); every other permission is refused
            override fun onContentPermissionRequest(
                session: GeckoSession,
                perm: GeckoSession.PermissionDelegate.ContentPermission
            ): GeckoResult<Int> {
                val allow = perm.permission == GeckoSession.PermissionDelegate.PERMISSION_AUTOPLAY_AUDIBLE ||
                    perm.permission == GeckoSession.PermissionDelegate.PERMISSION_AUTOPLAY_INAUDIBLE ||
                    perm.permission == GeckoSession.PermissionDelegate.PERMISSION_MEDIA_KEY_SYSTEM_ACCESS
                return GeckoResult.fromValue(
                    if (allow) GeckoSession.PermissionDelegate.ContentPermission.VALUE_ALLOW
                    else GeckoSession.PermissionDelegate.ContentPermission.VALUE_DENY
                )
            }
        }
        gs.navigationDelegate = object : GeckoSession.NavigationDelegate {
            override fun onCanGoBack(session: GeckoSession, canGoBack: Boolean) {
                this@RayMusicActivity.canGoBack = canGoBack
            }

            // only YouTube and Google's sign-in open here (this engine is older than the newest Firefox, see
            // libs.versions.toml); intent:// and market:// links (open the app) are ignored too
            override fun onLoadRequest(
                session: GeckoSession,
                request: GeckoSession.NavigationDelegate.LoadRequest
            ): GeckoResult<AllowOrDeny> {
                val ok = allowedPage(request.uri)
                Log.d(TAG, "page ${if (ok) "opened" else "refused"}: ${pageName(request.uri)}")
                return GeckoResult.fromValue(if (ok) AllowOrDeny.ALLOW else AllowOrDeny.DENY)
            }

            // a pop-up (Google's account chooser opens one) has no window of its own here: it opens in the player
            override fun onNewSession(session: GeckoSession, uri: String): GeckoResult<GeckoSession>? {
                Log.d(TAG, "pop-up: ${pageName(uri)}")
                if (allowedPage(uri)) session.loadUri(uri)
                return null
            }
        }
        gs.contentDelegate = object : GeckoSession.ContentDelegate {
            override fun onTitleChange(session: GeckoSession, title: String?) {
                if (pageMedia == null && !title.isNullOrBlank()) {
                    statusView?.text = title.removeSuffix(" - YouTube Music").removeSuffix(" - YouTube")
                }
            }
        }
        gs.mediaSessionDelegate = object : MediaSession.Delegate {
            override fun onActivated(session: GeckoSession, mediaSession: MediaSession) {
                pageMedia = mediaSession
                pendingAction?.let { pendingAction = null; doControl(it, byUser = false) }
            }

            override fun onDeactivated(session: GeckoSession, mediaSession: MediaSession) {
                if (pageMedia == mediaSession) pageMedia = null
            }

            override fun onMetadata(session: GeckoSession, mediaSession: MediaSession, meta: MediaSession.Metadata) {
                meta.title?.takeIf { it.isNotBlank() }?.let { currentTitle = it.trim() }
                currentArtist = meta.artist?.trim().orEmpty()
                showState()
            }

            override fun onPlay(session: GeckoSession, mediaSession: MediaSession) {
                pageMedia = mediaSession
                // a song that started by itself while Ray is still talking waits for him
                if (holdForSpeech || speechPaused || userPaused || turnHold) {
                    mediaSession.pause()
                    return
                }
                isCurrentlyPlaying = true
                // the screen only had to stay on until the song started: in a pocket it drained the battery
                // (2026-11-09: the song kept playing with the screen off and the phone locked)
                window.clearFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
                showState()
            }

            override fun onPause(session: GeckoSession, mediaSession: MediaSession) {
                isCurrentlyPlaying = false
                showState()
            }

            override fun onStop(session: GeckoSession, mediaSession: MediaSession) {
                isCurrentlyPlaying = false
                showState()
            }
        }
        gs.open(runtime(this))
        gs.setActive(true)
        geckoSession = gs

        val gv = GeckoView(this).apply {
            setBackgroundColor(Color.parseColor("#0B0D10"))
            setSession(gs)
        }
        root.addView(gv, LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, 0, 1f))
        setContentView(root)
    }

    private fun setupSession() {
        try {
            session = MediaSessionCompat(this, "RayMusicSession").apply {
                setCallback(object : MediaSessionCompat.Callback() {
                    // the keys themselves: one place (MediaButtonHandler) decides, so a double tap still wakes Ray
                    override fun onMediaButtonEvent(mediaButtonEvent: Intent): Boolean {
                        val key = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
                            mediaButtonEvent.getParcelableExtra(Intent.EXTRA_KEY_EVENT, KeyEvent::class.java)
                        } else {
                            @Suppress("DEPRECATION")
                            mediaButtonEvent.getParcelableExtra(Intent.EXTRA_KEY_EVENT)
                        } ?: return super.onMediaButtonEvent(mediaButtonEvent)
                        MediaButtonHandler.handleKeyEvent(this@RayMusicActivity, key)
                        return true
                    }

                    // the lock screen's, the car's and the system media panel's buttons
                    override fun onPlay() { control("play") }
                    override fun onPause() { control("pause") }
                    override fun onSkipToNext() { control("next") }
                    override fun onSkipToPrevious() { control("previous") }
                    override fun onStop() { control("pause") }
                })
                isActive = true
            }
            updateSession(playing = false, title = "", artist = "")
        } catch (e: Exception) {
            Log.w(TAG, "Could not create the music media session", e)
        }
    }

    private fun showState() {
        val display = when {
            currentTitle.isNotBlank() && currentArtist.isNotBlank() -> "$currentTitle — $currentArtist"
            currentTitle.isNotBlank() -> currentTitle
            else -> "YouTube Music"
        }
        statusView?.text = if (isCurrentlyPlaying) "▶ $display" else "⏸ $display"
        playPauseBtn?.text = if (isCurrentlyPlaying) "⏸" else "▶"
        updateSession(isCurrentlyPlaying, currentTitle, currentArtist)
    }

    private fun updateSession(playing: Boolean, title: String, artist: String) {
        val s = session ?: return
        if (playing != sessionPlaying) {
            sessionPlaying = playing
            s.setPlaybackState(
                PlaybackStateCompat.Builder()
                    .setActions(
                        PlaybackStateCompat.ACTION_PLAY or
                            PlaybackStateCompat.ACTION_PAUSE or
                            PlaybackStateCompat.ACTION_PLAY_PAUSE or
                            PlaybackStateCompat.ACTION_SKIP_TO_NEXT or
                            PlaybackStateCompat.ACTION_SKIP_TO_PREVIOUS or
                            PlaybackStateCompat.ACTION_STOP
                    )
                    .setState(
                        if (playing) PlaybackStateCompat.STATE_PLAYING else PlaybackStateCompat.STATE_PAUSED,
                        PlaybackStateCompat.PLAYBACK_POSITION_UNKNOWN,
                        if (playing) 1f else 0f
                    )
                    .build()
            )
        }
        if (title != sessionTitle || artist != sessionArtist) {
            sessionTitle = title
            sessionArtist = artist
            s.setMetadata(
                MediaMetadataCompat.Builder()
                    .putString(MediaMetadataCompat.METADATA_KEY_TITLE, title.ifBlank { "YouTube Music" })
                    .putString(MediaMetadataCompat.METADATA_KEY_ARTIST, artist)
                    .build()
            )
        }
    }

    fun kickPlayback() {
        mainHandler.post { doControl("play", byUser = false) }
    }

    /** Runs on the main thread.  [byUser]: the user (or Ray for them) asked, so a pause sticks until they play. */
    private fun doControl(action: String, byUser: Boolean) {
        val media = pageMedia
        when (action) {
            "pause" -> {
                if (byUser) userPaused = true
                media?.pause() ?: run { pendingAction = "pause" }
            }
            "play" -> {
                if (byUser) {
                    userPaused = false
                    if (turnHold) { turnResume = true; return }    // asked during a turn: once Ray is done
                } else if (userPaused) {
                    return                                         // the user paused it: it stays paused
                }
                if (holdForSpeech || speechPaused || turnHold) return
                media?.play() ?: run { pendingAction = "play" }
            }
            "play_pause" -> doControl(if (isCurrentlyPlaying) "pause" else "play", byUser)
            "next", "skip" -> {
                userPaused = false
                if (turnHold) turnResume = true
                media?.nextTrack()
            }
            "previous", "prev" -> {
                userPaused = false
                if (turnHold) turnResume = true
                media?.previousTrack()
            }
        }
    }

    private fun allowedPage(uri: String): Boolean {
        if (uri.startsWith("about:")) return true
        val u = runCatching { java.net.URI(uri) }.getOrNull() ?: return false
        if (u.scheme?.lowercase() != "https") return false
        val host = u.host?.lowercase() ?: return false
        return ALLOWED_SITES.any { host == it || host.endsWith(".$it") }
    }

    // the host and path only: a sign-in page's query holds tokens, which have no place in the log
    private fun pageName(uri: String): String =
        runCatching { java.net.URI(uri).let { "${it.scheme}://${it.host}${it.path.orEmpty()}" } }.getOrDefault(uri.take(40))

    private fun dp(value: Int): Int =
        TypedValue.applyDimension(TypedValue.COMPLEX_UNIT_DIP, value.toFloat(), resources.displayMetrics).toInt()

    override fun onDestroy() {
        mainHandler.removeCallbacksAndMessages(null)
        isCurrentlyPlaying = false
        if (instance == this) instance = null
        session?.isActive = false
        session?.release()
        session = null
        try {
            wakeLock?.let { if (it.isHeld) it.release() }
        } catch (_: Exception) {}
        geckoSession?.close()
        geckoSession = null
        pageMedia = null
        super.onDestroy()
    }
}
