package com.damirl.ray.audio

import android.content.Context
import android.media.AudioAttributes
import android.media.MediaPlayer
import android.media.PlaybackParams
import android.os.Handler
import android.os.Looper
import android.os.SystemClock
import android.speech.tts.TextToSpeech
import android.speech.tts.UtteranceProgressListener
import android.util.Log
import com.damirl.ray.network.NetworkClient
import com.damirl.ray.network.NetworkRoute
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.withContext
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONObject
import java.io.File
import java.io.FileOutputStream
import java.util.Locale
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.atomic.AtomicReference

// Ray's voice: Piper on the Strata server (/v1/audio/speech) over the route the drawer probed (LAN or the tunnel),
// played at his pitch; the phone's own voice only when the server can't be reached.  Both play as the assistant
// (USAGE_ASSISTANT), so they follow a headset's call link while one is held
class PiperAudioPlayer(
    private val context: Context,
    private val networkClient: NetworkClient
) {
    companion object {
        private const val TAG = "RayAudio"
        private const val PITCH_FACTOR = 1.5f // Ray's signature red panda cartoon pitch
        private const val SPEED_FACTOR = 1.05f
        private val JSON_MEDIA_TYPE = "application/json; charset=utf-8".toMediaType()

        /** Long enough for the phone's voice to read [chars] characters (about 12 a second) and then some. */
        fun systemVoiceLimitMs(chars: Int): Long = 5_000L + chars * 90L
    }

    // a dead route fails in 4 s, not the shared client's 15 s; Piper makes a long answer in a few seconds
    private val ttsClient: OkHttpClient = networkClient.okHttpClient.newBuilder()
        .connectTimeout(4, TimeUnit.SECONDS)
        .readTimeout(20, TimeUnit.SECONDS)
        .build()

    private val mainHandler = Handler(Looper.getMainLooper())
    private var mediaPlayer: MediaPlayer? = null
    private var systemTts: TextToSpeech? = null
    private val isTtsInitialized = AtomicBoolean(false)
    // the phone's voice reports its end through the listener: the one utterance being read and what to call then
    private val pendingUtterance = AtomicReference<Pair<String, () -> Unit>?>(null)

    private val _isPlaying = MutableStateFlow(false)
    val isPlaying: StateFlow<Boolean> = _isPlaying.asStateFlow()

    private val assistantAudio: AudioAttributes = AudioAttributes.Builder()
        .setContentType(AudioAttributes.CONTENT_TYPE_SPEECH)
        .setUsage(AudioAttributes.USAGE_ASSISTANT)
        .build()

    init {
        // Prepare offline Android TTS fallback
        try {
            systemTts = TextToSpeech(context) { status ->
                if (status == TextToSpeech.SUCCESS) {
                    systemTts?.language = Locale.US
                    systemTts?.setPitch(PITCH_FACTOR)
                    systemTts?.setAudioAttributes(assistantAudio)
                    systemTts?.setOnUtteranceProgressListener(object : UtteranceProgressListener() {
                        override fun onStart(utteranceId: String?) {}
                        override fun onDone(utteranceId: String?) = utteranceEnded(utteranceId, "done")
                        @Deprecated("Deprecated in Java")
                        override fun onError(utteranceId: String?) = utteranceEnded(utteranceId, "error")
                        override fun onError(utteranceId: String?, errorCode: Int) = utteranceEnded(utteranceId, "error $errorCode")
                        override fun onStop(utteranceId: String?, interrupted: Boolean) = utteranceEnded(utteranceId, "stopped")
                    })
                    isTtsInitialized.set(true)
                    Log.d(TAG, "Offline Android TTS fallback initialized")
                }
            }
        } catch (e: Exception) {
            Log.w(TAG, "Failed to initialize system TTS fallback", e)
        }
    }

    /** Fetches and plays [text] (cleaned for speech); [onComplete] runs once when it has been said or failed. */
    suspend fun speak(text: String, onComplete: () -> Unit = {}) {
        val cleanText = SpeechCleaner.clean(text)
        play(cleanText, fetch(cleanText), onComplete)
    }

    /**
     * Ray's voice for [cleanText] from the server, as a WAV file, or null when the server can't be reached.  On a
     * failure the route is probed again and the request tried once more (the LAN gone, the tunnel there).
     */
    suspend fun fetch(cleanText: String): File? = withContext(Dispatchers.IO) {
        if (cleanText.isBlank()) return@withContext null
        var route = networkClient.ensureRoute()
        for (attempt in 0..1) {
            if (route is NetworkRoute.Offline) break
            val started = SystemClock.elapsedRealtime()
            VoiceTrace.event("tts_fetch", "route" to NetworkClient.label(route), "chars" to cleanText.length, "attempt" to attempt)
            try {
                val file = fetchPiperWav(cleanText)
                VoiceTrace.event("tts_fetched", "ms" to SystemClock.elapsedRealtime() - started, "bytes" to file.length())
                return@withContext file
            } catch (e: Exception) {
                Log.w(TAG, "Piper server TTS failed (${e.message})")
                VoiceTrace.event("tts_failed", "ms" to SystemClock.elapsedRealtime() - started,
                    "error" to (e.message ?: e.javaClass.simpleName))
                if (attempt == 0) route = networkClient.probeAndSelectRoute()
            }
        }
        null
    }

    /** Plays [file] (from [fetch]) at Ray's pitch, or reads [cleanText] with the phone's voice when there is none. */
    suspend fun play(cleanText: String, file: File?, onComplete: () -> Unit) {
        if (cleanText.isBlank()) {
            onComplete()
            return
        }
        stop()
        _isPlaying.value = true
        if (file != null && file.exists()) {
            VoiceTrace.event("tts_play", "engine" to "piper")
            playWavFile(file, onComplete)
        } else {
            Log.w(TAG, "No Piper audio: falling back to system TTS")
            VoiceTrace.event("tts_play", "engine" to "system")
            speakWithSystemTts(cleanText, onComplete)
        }
    }

    private fun fetchPiperWav(text: String): File {
        val payload = JSONObject().apply {
            put("input", text)
            put("voice", "en_US-hfc_male-medium")
            put("response_format", "wav")
            put("speed", 1.0)
        }

        val request = networkClient.newAuthenticatedRequestBuilder("/v1/audio/speech")
            .post(payload.toString().toRequestBody(JSON_MEDIA_TYPE))
            .build()

        ttsClient.newCall(request).execute().use { response ->
            if (!response.isSuccessful) {
                throw IllegalStateException("Piper server returned HTTP ${response.code}")
            }
            val bytes = response.body?.bytes() ?: throw IllegalStateException("Empty audio response")
            val cacheFile = File(context.cacheDir, "ray_speech_${System.currentTimeMillis()}.wav")
            FileOutputStream(cacheFile).use { fos ->
                fos.write(bytes)
            }
            return cacheFile
        }
    }

    private suspend fun playWavFile(file: File, onComplete: () -> Unit) = withContext(Dispatchers.Main) {
        try {
            val player = MediaPlayer().apply {
                setAudioAttributes(assistantAudio)
                setDataSource(file.absolutePath)
                prepare()

                try {
                    val params = PlaybackParams().apply {
                        pitch = PITCH_FACTOR
                        speed = SPEED_FACTOR
                    }
                    playbackParams = params
                } catch (e: Exception) {
                    Log.w(TAG, "Failed to apply PlaybackParams pitch on MediaPlayer", e)
                }

                setOnCompletionListener {
                    Log.d(TAG, "MediaPlayer completed playback")
                    _isPlaying.value = false
                    try { file.delete() } catch (_: Exception) {}
                    onComplete()
                }

                setOnErrorListener { _, what, extra ->
                    Log.e(TAG, "MediaPlayer error: what=$what, extra=$extra")
                    _isPlaying.value = false
                    try { file.delete() } catch (_: Exception) {}
                    onComplete()
                    true
                }
            }

            mediaPlayer = player
            player.start()
            Log.d(TAG, "AudioTrack playing Piper WAV at pitch $PITCH_FACTOR")
        } catch (e: Exception) {
            Log.e(TAG, "Error playing WAV file", e)
            _isPlaying.value = false
            onComplete()
        }
    }

    // The phone's voice.  It used to report nothing when done, so Ray's turn never ended: the headset's call link,
    // the audio focus (music paused) and "speaking" stayed held until the service died (2026-11-04)
    private suspend fun speakWithSystemTts(text: String, onComplete: () -> Unit) {
        Log.d(TAG, "Speaking via System TTS fallback")
        val until = SystemClock.elapsedRealtime() + 2_000           // it initialises in the background
        while (!isTtsInitialized.get() && SystemClock.elapsedRealtime() < until) delay(100)
        val tts = systemTts
        if (!isTtsInitialized.get() || tts == null) {
            Log.e(TAG, "System TTS fallback not available")
            _isPlaying.value = false
            onComplete()
            return
        }
        val id = "ray_tts_${System.currentTimeMillis()}"
        pendingUtterance.set(id to onComplete)
        // in case the engine never reports back: Ray's turn still ends
        mainHandler.postDelayed({ utteranceEnded(id, "timed out") }, systemVoiceLimitMs(text.length))
        if (tts.speak(text, TextToSpeech.QUEUE_FLUSH, null, id) != TextToSpeech.SUCCESS) utteranceEnded(id, "refused")
    }

    private fun utteranceEnded(utteranceId: String?, how: String) {
        val pending = pendingUtterance.get() ?: return
        if (pending.first != utteranceId || !pendingUtterance.compareAndSet(pending, null)) return
        Log.d(TAG, "System TTS $how")
        VoiceTrace.event("tts_system_end", "how" to how)
        _isPlaying.value = false
        mainHandler.post { pending.second() }
    }

    fun stop() {
        try {
            mediaPlayer?.let {
                if (it.isPlaying) {
                    it.stop()
                }
                it.release()
            }
            mediaPlayer = null
            pendingUtterance.set(null)                             // a stop isn't the end of a new utterance
            systemTts?.stop()
        } catch (e: Exception) {
            Log.w(TAG, "Error stopping audio", e)
        } finally {
            _isPlaying.value = false
        }
    }

    fun release() {
        stop()
        try {
            systemTts?.shutdown()
            systemTts = null
        } catch (_: Exception) {}
    }
}
