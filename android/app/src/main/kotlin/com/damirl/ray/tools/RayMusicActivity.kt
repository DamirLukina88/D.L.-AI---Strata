package com.damirl.ray.tools

import android.annotation.SuppressLint
import android.app.Activity
import android.content.Context
import android.content.Intent
import android.graphics.Color
import android.graphics.Typeface
import android.graphics.drawable.GradientDrawable
import android.media.AudioManager
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.os.PowerManager
import android.os.SystemClock
import android.util.Log
import android.util.TypedValue
import android.view.Gravity
import android.view.View
import android.view.ViewGroup
import android.view.WindowManager
import android.webkit.CookieManager
import android.webkit.JavascriptInterface
import android.webkit.WebChromeClient
import android.webkit.WebResourceRequest
import android.webkit.WebSettings
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.FrameLayout
import android.widget.LinearLayout
import android.widget.TextView
import com.damirl.ray.MainActivity
import com.damirl.ray.assistant.VoiceDrawerController
import com.damirl.ray.audio.AudioPlaybackService
import com.damirl.ray.audio.BluetoothMic
import com.damirl.ray.audio.VoiceTrace

/**
 * In-app lock-screen music player activity (`android:showWhenLocked="true"`, `android:turnScreenOn="true"`).
 *
 * Plays YouTube Music / YouTube links directly inside a keep-awake WebView (`mediaPlaybackRequiresUserGesture = false`)
 * that overrides window visibility (`onWindowVisibilityChanged(View.VISIBLE)`) and page visibility (`document.hidden = false`),
 * so music starts automatically on a locked Xiaomi phone without unlocking or requiring unstable Brave command-line flags,
 * and continues playing when the screen turns off in a pocket.
 */
class RayMusicActivity : Activity() {

    companion object {
        private const val TAG = "RayMusicPlayer"
        private const val EXTRA_URL = "extra_url"
        private const val DESKTOP_CHROME_UA =
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"

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

        fun isActive(): Boolean = instance != null

        fun isPlaying(): Boolean = instance != null && isCurrentlyPlaying

        fun open(context: Context, url: String): String {
            return try {
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
                // unmuting/starting playback, so the song doesn't play under his voice or stop when HFP closes.
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
                    act.evaluateControlJs("pause")
                } else {
                    holdForSpeech = false
                    act.evaluateControlJs("play")
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
                when (norm) {
                    "stop" -> {
                        act.evaluateControlJs("pause")
                        act.finish()
                    }
                    else -> act.evaluateControlJs(norm)
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
    private var webView: KeepAwakeWebView? = null
    private var statusView: TextView? = null
    private var playPauseBtn: TextView? = null
    private var wakeLock: PowerManager.WakeLock? = null
    private var currentUrl: String = ""

    private val watchdogRunnable = object : Runnable {
        override fun run() {
            if (isFinishing || isDestroyed) return
            injectKeepAliveAndAutoplay()
            mainHandler.postDelayed(this, 1_000L)
        }
    }

    /**
     * Custom WebView that always reports [View.VISIBLE] to Chromium's renderer even when the phone screen turns off
     * or is locked in a pocket, preventing Chromium from suspending audio decoding.
     */
    private class KeepAwakeWebView(context: Context) : WebView(context) {
        override fun onWindowVisibilityChanged(visibility: Int) {
            super.onWindowVisibilityChanged(View.VISIBLE)
        }

        override fun onWindowFocusChanged(hasWindowFocus: Boolean) {
            super.onWindowFocusChanged(true)
        }
    }

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
        handleIntent(intent)
        mainHandler.postDelayed(watchdogRunnable, 800L)
    }

    override fun onNewIntent(intent: Intent?) {
        super.onNewIntent(intent)
        setIntent(intent)
        handleIntent(intent)
    }

    private fun handleIntent(intent: Intent?) {
        val url = intent?.getStringExtra(EXTRA_URL)?.trim().orEmpty()
        if (url.isNotEmpty()) {
            currentUrl = url
            statusView?.text = if (holdForSpeech) "Preparing music…" else "Loading music…"
            webView?.loadUrl(url)
        }
    }

    @SuppressLint("SetJavaScriptEnabled")
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
            val padH = dp(12)
            val padV = dp(10)
            setPadding(padH, dp(36), padH, padV)
        }

        val titleCol = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            layoutParams = LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f)
        }

        val headerLabel = TextView(this).apply {
            text = "RAY LOCK-SCREEN PLAYER"
            setTextColor(Color.parseColor("#7C8B9E"))
            setTextSize(TypedValue.COMPLEX_UNIT_SP, 10f)
            typeface = Typeface.DEFAULT_BOLD
        }

        statusView = TextView(this).apply {
            text = "Loading YouTube Music…"
            setTextColor(Color.parseColor("#E8EEF5"))
            setTextSize(TypedValue.COMPLEX_UNIT_SP, 14f)
            typeface = Typeface.DEFAULT_BOLD
            maxLines = 1
        }

        titleCol.addView(headerLabel)
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
                val lp = LinearLayout.LayoutParams(
                    ViewGroup.LayoutParams.WRAP_CONTENT,
                    ViewGroup.LayoutParams.WRAP_CONTENT
                ).apply { marginStart = dp(6) }
                layoutParams = lp
                setOnClickListener { onClick() }
            }
        }

        topBar.addView(makeButton("⏮") { evaluateControlJs("previous") })
        playPauseBtn = makeButton("⏯") { evaluateControlJs("play_pause") }.also { topBar.addView(it) }
        topBar.addView(makeButton("⏭") { evaluateControlJs("next") })
        topBar.addView(makeButton("Ray") {
            startActivity(Intent(this, MainActivity::class.java).apply {
                addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_REORDER_TO_FRONT)
            })
        })
        topBar.addView(makeButton("✕", "#3A1D24") {
            evaluateControlJs("pause")
            finish()
        })

        root.addView(
            topBar,
            LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT)
        )

        val wv = KeepAwakeWebView(this).apply {
            setBackgroundColor(Color.parseColor("#0B0D10"))
            settings.apply {
                javaScriptEnabled = true
                domStorageEnabled = true
                databaseEnabled = true
                mediaPlaybackRequiresUserGesture = false
                userAgentString = DESKTOP_CHROME_UA
                cacheMode = WebSettings.LOAD_DEFAULT
                useWideViewPort = true
                loadWithOverviewMode = true
                mixedContentMode = WebSettings.MIXED_CONTENT_COMPATIBILITY_MODE
            }
            CookieManager.getInstance().setAcceptCookie(true)
            CookieManager.getInstance().setAcceptThirdPartyCookies(this, true)
            // Pre-set Google's SOCS consent cookie so EU YouTube Music doesn't block autoplay on consent.youtube.com
            val socsCookie = "SOCS=CAISHAgCEhJnd3NfMjAyNDA1MTQtMF9SQzIaAmVuIAEaBgiA_LyaBg; domain=.youtube.com; path=/; Secure; SameSite=None"
            CookieManager.getInstance().setCookie("https://www.youtube.com", socsCookie)
            CookieManager.getInstance().setCookie("https://music.youtube.com", socsCookie)
            CookieManager.getInstance().setCookie("https://consent.youtube.com", socsCookie)
            CookieManager.getInstance().flush()

            addJavascriptInterface(PlayerBridge(), "RayPlayerBridge")

            webChromeClient = WebChromeClient()
            webViewClient = object : WebViewClient() {
                override fun shouldOverrideUrlLoading(view: WebView?, request: WebResourceRequest?): Boolean {
                    val u = request?.url ?: return false
                    val scheme = u.scheme?.lowercase() ?: ""
                    if (scheme == "http" || scheme == "https") return false
                    // Ignore intent:// or market:// redirects so YouTube Music stays in the web player
                    return true
                }

                override fun onPageStarted(view: WebView?, url: String?, favicon: android.graphics.Bitmap?) {
                    super.onPageStarted(view, url, favicon)
                    injectKeepAliveAndAutoplay()
                }

                override fun onPageFinished(view: WebView?, url: String?) {
                    super.onPageFinished(view, url)
                    injectKeepAliveAndAutoplay()
                }
            }
        }
        webView = wv
        root.addView(
            wv,
            LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, 0, 1f)
        )

        setContentView(root)
    }

    private inner class PlayerBridge {
        @JavascriptInterface
        fun onState(playing: Boolean, title: String, artist: String) {
            isCurrentlyPlaying = playing
            if (title.isNotBlank()) currentTitle = title.trim()
            if (artist.isNotBlank()) currentArtist = artist.trim()
            mainHandler.post {
                val display = when {
                    currentTitle.isNotBlank() && currentArtist.isNotBlank() -> "$currentTitle — $currentArtist"
                    currentTitle.isNotBlank() -> currentTitle
                    else -> "YouTube Music"
                }
                statusView?.text = if (playing) "▶ $display" else "⏸ $display"
                playPauseBtn?.text = if (playing) "⏸" else "▶"
            }
        }
    }

    fun kickPlayback() {
        mainHandler.post {
            injectKeepAliveAndAutoplay()
            evaluateControlJs("play")
        }
    }

    private fun injectKeepAliveAndAutoplay() {
        val wv = webView ?: return
        val shouldHold = holdForSpeech || speechPaused
        val js = """
            (function() {
                try {
                    if (!window.__rayVisPatched) {
                        window.__rayVisPatched = true;
                        Object.defineProperty(document, 'hidden', { get: function() { return false; }, configurable: true });
                        Object.defineProperty(document, 'visibilityState', { get: function() { return 'visible'; }, configurable: true });
                        window.addEventListener('visibilitychange', function(e) { e.stopImmediatePropagation(); }, true);
                        window.addEventListener('webkitvisibilitychange', function(e) { e.stopImmediatePropagation(); }, true);
                    }
                    // Auto-dismiss EU consent.youtube.com form if ever shown
                    if (location.hostname.indexOf('consent.') !== -1 || document.title.indexOf('Before you continue') !== -1) {
                        var consentBtn = document.querySelector('form[action*="save"] button, button[aria-label*="Accept"], button[aria-label*="Reject"]');
                        if (consentBtn) { consentBtn.click(); return; }
                    }
                    // Skip any skippable ad
                    var skip = document.querySelector('.ytp-ad-skip-button, .ytp-ad-skip-button-modern, .ytp-skip-ad-button');
                    if (skip) skip.click();
                    var adVid = document.querySelector('.ad-showing video, .ad-interrupting video');
                    if (adVid && isFinite(adVid.duration) && adVid.duration > 0) {
                        adVid.currentTime = adVid.duration;
                    }
                    var v = document.querySelector('video');
                    var hold = $shouldHold;
                    if (v) {
                        if (hold) {
                            if (!v.paused) v.pause();
                        } else if (!window.__rayUserPaused) {
                            v.muted = false;
                            if (v.volume < 0.1) v.volume = 1.0;
                            if (v.paused) {
                                var p = v.play();
                                if (p && p.catch) p.catch(function(){});
                            }
                        }
                    } else if (!hold && !window.__rayUserPaused) {
                        var playBtn = document.querySelector('ytmusic-player-bar #play-pause-button, .ytp-large-play-button, button[aria-label="Play"]');
                        if (playBtn) playBtn.click();
                    }
                    var titleEl = document.querySelector('ytmusic-player-bar .title, .ytp-title-link, h1.ytd-watch-metadata');
                    var artistEl = document.querySelector('ytmusic-player-bar .byline a, ytmusic-player-bar .byline');
                    var title = (titleEl && titleEl.textContent) ? titleEl.textContent.trim() : document.title.replace(/ - YouTube( Music)?$/, '');
                    var artist = (artistEl && artistEl.textContent) ? artistEl.textContent.trim().split('•')[0].trim() : '';
                    var playing = !!(v && !v.paused && !v.ended && v.readyState > 1);
                    if (window.RayPlayerBridge && window.RayPlayerBridge.onState) {
                        window.RayPlayerBridge.onState(playing, title || '', artist || '');
                    }
                } catch (e) {}
            })();
        """.trimIndent()
        wv.evaluateJavascript(js, null)
    }

    fun evaluateControlJs(action: String) {
        val wv = webView ?: return
        val js = when (action) {
            "pause", "stop" -> """
                (function() {
                    window.__rayUserPaused = true;
                    var v = document.querySelector('video');
                    if (v && !v.paused) v.pause();
                })();
            """.trimIndent()
            "play" -> """
                (function() {
                    window.__rayUserPaused = false;
                    var v = document.querySelector('video');
                    if (v) { v.muted = false; v.play(); }
                    else {
                        var b = document.querySelector('ytmusic-player-bar #play-pause-button, .ytp-play-button');
                        if (b) b.click();
                    }
                })();
            """.trimIndent()
            "play_pause" -> """
                (function() {
                    var v = document.querySelector('video');
                    if (v) {
                        if (v.paused) { window.__rayUserPaused = false; v.muted = false; v.play(); }
                        else { window.__rayUserPaused = true; v.pause(); }
                    }
                })();
            """.trimIndent()
            "next", "skip" -> """
                (function() {
                    window.__rayUserPaused = false;
                    var b = document.querySelector('ytmusic-player-bar .next-button, .ytp-next-button, button[aria-label="Next"], tp-yt-paper-icon-button.next-button');
                    if (b) b.click();
                })();
            """.trimIndent()
            "previous", "prev" -> """
                (function() {
                    window.__rayUserPaused = false;
                    var b = document.querySelector('ytmusic-player-bar .previous-button, .ytp-prev-button, button[aria-label="Previous"], tp-yt-paper-icon-button.previous-button');
                    if (b) b.click();
                    else {
                        var v = document.querySelector('video');
                        if (v) v.currentTime = 0;
                    }
                })();
            """.trimIndent()
            else -> return
        }
        wv.evaluateJavascript(js, null)
        mainHandler.postDelayed({ injectKeepAliveAndAutoplay() }, 250L)
    }

    private fun dp(value: Int): Int =
        TypedValue.applyDimension(TypedValue.COMPLEX_UNIT_DIP, value.toFloat(), resources.displayMetrics).toInt()

    override fun onDestroy() {
        mainHandler.removeCallbacksAndMessages(null)
        isCurrentlyPlaying = false
        if (instance == this) instance = null
        try {
            wakeLock?.let { if (it.isHeld) it.release() }
        } catch (_: Exception) {}
        webView?.destroy()
        webView = null
        super.onDestroy()
    }
}
