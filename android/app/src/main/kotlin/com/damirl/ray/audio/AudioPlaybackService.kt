package com.damirl.ray.audio

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.media.AudioAttributes
import android.media.AudioFocusRequest
import android.media.AudioManager
import android.os.Build
import android.os.IBinder
import android.os.PowerManager
import android.support.v4.media.session.MediaSessionCompat
import android.support.v4.media.session.PlaybackStateCompat
import android.util.Log
import android.view.KeyEvent
import androidx.core.app.NotificationCompat
import com.damirl.ray.MainActivity
import com.damirl.ray.R
import com.damirl.ray.network.NetworkClient
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch

class AudioPlaybackService : Service() {

    companion object {
        private const val TAG = "RayAudio"
        private const val NOTIFICATION_ID = 1001
        private const val CHANNEL_ID = "ray_speech_playback"

        const val ACTION_SPEAK = "com.damirl.ray.action.SPEAK"
        const val ACTION_STOP = "com.damirl.ray.action.STOP"
        const val EXTRA_TEXT = "extra_text"

        private val _isSpeakingState = MutableStateFlow(false)
        val isSpeakingState: StateFlow<Boolean> = _isSpeakingState.asStateFlow()

        fun startSpeaking(context: Context, text: String) {
            val intent = Intent(context, AudioPlaybackService::class.java).apply {
                action = ACTION_SPEAK
                putExtra(EXTRA_TEXT, text)
            }
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                context.startForegroundService(intent)
            } else {
                context.startService(intent)
            }
        }

        fun stopSpeaking(context: Context) {
            val intent = Intent(context, AudioPlaybackService::class.java).apply {
                action = ACTION_STOP
            }
            context.startService(intent)
        }
    }

    private val serviceScope = CoroutineScope(SupervisorJob() + Dispatchers.Main)
    private var wakeLock: PowerManager.WakeLock? = null
    private var audioManager: AudioManager? = null
    private var audioFocusRequest: AudioFocusRequest? = null
    private var piperPlayer: PiperAudioPlayer? = null
    private var mediaSession: MediaSessionCompat? = null
    private var speakGeneration = 0          // the answer being said; an older one's fetch or end is ignored
    private var answerJob: Job? = null       // its pieces being fetched and said
    private var answerPieces: List<PiperAudioPlayer.Piece> = emptyList()

    override fun onCreate() {
        super.onCreate()
        Log.d(TAG, "AudioPlaybackService created")

        createNotificationChannel()
        VoiceTrace.init(this)
        // the shared client: the route the drawer just probed (a client of its own always used the LAN address, so
        // away from home Ray's voice waited 15 s and fell back to the phone's voice, 2026-11-04)
        piperPlayer = PiperAudioPlayer(this, NetworkClient.shared)

        val powerManager = getSystemService(Context.POWER_SERVICE) as PowerManager
        wakeLock = powerManager.newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "RayAssistant:AudioWakeLock").apply {
            setReferenceCounted(false)
        }

        audioManager = getSystemService(Context.AUDIO_SERVICE) as AudioManager
        initMediaSession()
    }

    private fun initMediaSession() {
        try {
            val mediaButtonIntent = Intent(Intent.ACTION_MEDIA_BUTTON).apply {
                setClass(this@AudioPlaybackService, MediaButtonReceiver::class.java)
            }
            val mediaButtonPendingIntent = PendingIntent.getBroadcast(
                this,
                0,
                mediaButtonIntent,
                PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
            )

            mediaSession = MediaSessionCompat(this, "RayAudioServiceSession").apply {
                setFlags(
                    MediaSessionCompat.FLAG_HANDLES_MEDIA_BUTTONS or
                    MediaSessionCompat.FLAG_HANDLES_TRANSPORT_CONTROLS
                )
                setMediaButtonReceiver(mediaButtonPendingIntent)
                setCallback(object : MediaSessionCompat.Callback() {
                    override fun onMediaButtonEvent(mediaButtonEvent: Intent): Boolean {
                        val keyEvent = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
                            mediaButtonEvent.getParcelableExtra(Intent.EXTRA_KEY_EVENT, KeyEvent::class.java)
                        } else {
                            @Suppress("DEPRECATION")
                            mediaButtonEvent.getParcelableExtra(Intent.EXTRA_KEY_EVENT)
                        } ?: return super.onMediaButtonEvent(mediaButtonEvent)

                        return MediaButtonHandler.handleKeyEvent(this@AudioPlaybackService, keyEvent)
                    }

                    override fun onPause() {
                        finishPlayback()
                    }

                    override fun onStop() {
                        finishPlayback()
                    }
                })
                isActive = true
            }
        } catch (e: Exception) {
            Log.w(TAG, "Failed to initialize MediaSessionCompat in AudioPlaybackService", e)
        }
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        val action = intent?.action ?: return START_NOT_STICKY

        when (action) {
            ACTION_SPEAK -> {
                val text = intent.getStringExtra(EXTRA_TEXT) ?: ""
                if (text.isNotBlank()) {
                    updateMediaPlaybackState(PlaybackStateCompat.STATE_PLAYING)
                    val notification = createNotification(text)
                    startForeground(NOTIFICATION_ID, notification)
                    acquireWakeLock()
                    // before taking the audio: that pauses Brave, and the check would then find nothing playing
                    // to resume (the song stayed stopped after his answer, 2026-11-03 21:57)
                    com.damirl.ray.tools.RayMediaController.pauseForSpeech(this)
                    requestAudioFocus()

                    _isSpeakingState.value = true
                    com.damirl.ray.assistant.WakeWord.hold("speak")     // "Ok Ray" mustn't hear Ray
                    val generation = ++speakGeneration
                    val headset = BluetoothMic.inHeadsetConversation()
                    VoiceTrace.event("speak_start", "chars" to text.length, "headset" to headset)
                    // his voice is fetched at once, while the headset's call link comes up (that took up to 3.7 s
                    // before the fetch even started, 2026-11-04)
                    val cleanText = SpeechCleaner.clean(text)
                    dropAnswer()
                    val job = SupervisorJob(serviceScope.coroutineContext[Job])
                    val answerScope = CoroutineScope(serviceScope.coroutineContext + job)
                    answerJob = job
                    answerPieces = piperPlayer?.fetchAhead(answerScope, cleanText).orEmpty()
                    val pieces = answerPieces
                    val play = {
                        answerScope.launch {
                            piperPlayer?.playAll(pieces) {
                                Log.d(TAG, "Speech playback finished")
                                if (generation == speakGeneration) finishPlayback()
                            }
                        }
                    }
                    // you spoke through a headset (helmet intercom): answer over its call link, which it plays even
                    // while the intercom is on; otherwise the usual output (the music link, or the phone)
                    if (headset) {
                        Log.d(TAG, "Answering over the headset's call link")
                        BluetoothMic.acquire(this, "reply") { if (_isSpeakingState.value) play() }
                    } else {
                        play()
                    }
                }
            }
            ACTION_STOP -> {
                Log.d(TAG, "Received ACTION_STOP")
                finishPlayback()
            }
        }

        return START_NOT_STICKY
    }

    private fun updateMediaPlaybackState(state: Int) {
        val playbackState = PlaybackStateCompat.Builder()
            .setActions(
                PlaybackStateCompat.ACTION_PLAY or
                PlaybackStateCompat.ACTION_PAUSE or
                PlaybackStateCompat.ACTION_PLAY_PAUSE or
                PlaybackStateCompat.ACTION_STOP
            )
            .setState(state, PlaybackStateCompat.PLAYBACK_POSITION_UNKNOWN, 1.0f)
            .build()
        mediaSession?.setPlaybackState(playbackState)
    }

    private fun acquireWakeLock() {
        try {
            wakeLock?.let {
                if (!it.isHeld) {
                    it.acquire(120_000) // 2 minute safety timeout
                    Log.d(TAG, "WakeLock acquired")
                }
            }
        } catch (e: Exception) {
            Log.w(TAG, "Failed to acquire wake lock", e)
        }
    }

    private fun releaseWakeLock() {
        try {
            wakeLock?.let {
                if (it.isHeld) {
                    it.release()
                    Log.d(TAG, "WakeLock released")
                }
            }
        } catch (_: Exception) {}
    }

    private fun requestAudioFocus() {
        val am = audioManager ?: return
        val attrs = AudioAttributes.Builder()
            .setUsage(AudioAttributes.USAGE_ASSISTANT)
            .setContentType(AudioAttributes.CONTENT_TYPE_SPEECH)
            .build()

        // music pauses while Ray talks (not ducked under him: over a helmet's call link the ducked music sounded
        // broken, and the user doesn't want him talking over it); RayMediaController resumes it afterwards
        val req = AudioFocusRequest.Builder(AudioManager.AUDIOFOCUS_GAIN_TRANSIENT)
            .setAudioAttributes(attrs)
            .setOnAudioFocusChangeListener { focusChange ->
                Log.d(TAG, "AudioFocus changed: $focusChange")
                VoiceTrace.event("speak_focus_change", "change" to focusChange)
                if (focusChange == AudioManager.AUDIOFOCUS_LOSS) {
                    finishPlayback()
                }
            }
            .build()

        audioFocusRequest = req
        val result = am.requestAudioFocus(req)
        Log.d(TAG, "AudioFocus granted: ${result == AudioManager.AUDIOFOCUS_REQUEST_GRANTED}")
        VoiceTrace.event("speak_focus", "granted" to (result == AudioManager.AUDIOFOCUS_REQUEST_GRANTED))
    }

    private fun abandonAudioFocus() {
        val req = audioFocusRequest ?: return
        audioManager?.abandonAudioFocusRequest(req)
        audioFocusRequest = null
    }

    private fun dropAnswer() {
        answerJob?.cancel()
        answerJob = null
        piperPlayer?.discard(answerPieces)
        answerPieces = emptyList()
    }

    private fun finishPlayback() {
        if (_isSpeakingState.value) VoiceTrace.event("speak_end")
        _isSpeakingState.value = false
        com.damirl.ray.assistant.WakeWord.release("speak")
        BluetoothMic.release("reply")
        updateMediaPlaybackState(PlaybackStateCompat.STATE_STOPPED)
        dropAnswer()
        piperPlayer?.stop()
        releaseWakeLock()
        abandonAudioFocus()
        stopForeground(STOP_FOREGROUND_REMOVE)
        stopSelf()
    }

    private fun createNotificationChannel() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val channel = NotificationChannel(
                CHANNEL_ID,
                "Ray Voice Playback",
                NotificationManager.IMPORTANCE_LOW
            ).apply {
                description = "Shows ongoing audio playback for Ray Assistant"
                setShowBadge(false)
            }
            val nm = getSystemService(NotificationManager::class.java)
            nm.createNotificationChannel(channel)
        }
    }

    private fun createNotification(text: String): Notification {
        val openAppIntent = Intent(this, MainActivity::class.java).apply {
            flags = Intent.FLAG_ACTIVITY_SINGLE_TOP
        }
        val openAppPendingIntent = PendingIntent.getActivity(
            this,
            0,
            openAppIntent,
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
        )

        val stopIntent = Intent(this, AudioPlaybackService::class.java).apply {
            action = ACTION_STOP
        }
        val stopPendingIntent = PendingIntent.getService(
            this,
            1,
            stopIntent,
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
        )

        val builder = NotificationCompat.Builder(this, CHANNEL_ID)
            .setSmallIcon(R.drawable.ic_tile_paw)
            .setContentTitle("Ray Assistant 🐾")
            .setContentText(text.take(60))
            .setContentIntent(openAppPendingIntent)
            .addAction(android.R.drawable.ic_media_pause, "Stop", stopPendingIntent)
            .setOngoing(true)
            .setCategory(NotificationCompat.CATEGORY_SERVICE)
            .setPriority(NotificationCompat.PRIORITY_LOW)

        mediaSession?.let { session ->
            builder.setStyle(
                androidx.media.app.NotificationCompat.MediaStyle()
                    .setMediaSession(session.sessionToken)
                    .setShowActionsInCompactView(0)
            )
        }

        return builder.build()
    }

    override fun onDestroy() {
        super.onDestroy()
        Log.d(TAG, "AudioPlaybackService destroyed")
        serviceScope.cancel()
        BluetoothMic.release("reply")
        com.damirl.ray.assistant.WakeWord.release("speak")
        piperPlayer?.release()
        piperPlayer = null
        mediaSession?.isActive = false
        mediaSession?.release()
        mediaSession = null
        releaseWakeLock()
        abandonAudioFocus()
    }

    override fun onBind(intent: Intent?): IBinder? = null
}
