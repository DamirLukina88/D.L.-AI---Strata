package com.damirl.ray.audio

import android.content.Context
import android.media.AudioAttributes
import android.media.MediaPlayer
import android.media.PlaybackParams
import android.speech.tts.TextToSpeech
import android.util.Log
import com.damirl.ray.network.NetworkClient
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.withContext
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONObject
import java.io.File
import java.io.FileOutputStream
import java.util.Locale
import java.util.concurrent.atomic.AtomicBoolean

class PiperAudioPlayer(
    private val context: Context,
    private val networkClient: NetworkClient
) {
    companion object {
        private const val TAG = "RayAudio"
        private const val PITCH_FACTOR = 1.5f // Ray's signature red panda cartoon pitch
        private const val SPEED_FACTOR = 1.05f
        private val JSON_MEDIA_TYPE = "application/json; charset=utf-8".toMediaType()
    }

    private var mediaPlayer: MediaPlayer? = null
    private var systemTts: TextToSpeech? = null
    private val isTtsInitialized = AtomicBoolean(false)

    private val _isPlaying = MutableStateFlow(false)
    val isPlaying: StateFlow<Boolean> = _isPlaying.asStateFlow()

    init {
        // Prepare offline Android TTS fallback
        try {
            systemTts = TextToSpeech(context) { status ->
                if (status == TextToSpeech.SUCCESS) {
                    systemTts?.language = Locale.US
                    systemTts?.setPitch(PITCH_FACTOR)
                    isTtsInitialized.set(true)
                    Log.d(TAG, "Offline Android TTS fallback initialized")
                }
            }
        } catch (e: Exception) {
            Log.w(TAG, "Failed to initialize system TTS fallback", e)
        }
    }

    suspend fun speak(text: String, onComplete: () -> Unit = {}) = withContext(Dispatchers.IO) {
        val cleanText = SpeechCleaner.clean(text)
        if (cleanText.isBlank()) {
            onComplete()
            return@withContext
        }

        stop()
        _isPlaying.value = true
        Log.d(TAG, "Requesting Piper TTS for: ${cleanText.take(40)}...")

        var synthesizedFile: File? = null
        try {
            synthesizedFile = fetchPiperWav(cleanText)
        } catch (e: Exception) {
            Log.w(TAG, "Piper server TTS failed (${e.message}), falling back to system TTS")
        }

        if (synthesizedFile != null && synthesizedFile.exists()) {
            playWavFile(synthesizedFile, onComplete)
        } else {
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

        networkClient.okHttpClient.newCall(request).execute().use { response ->
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
                setAudioAttributes(
                    AudioAttributes.Builder()
                        .setContentType(AudioAttributes.CONTENT_TYPE_SPEECH)
                        .setUsage(AudioAttributes.USAGE_ASSISTANT)
                        .build()
                )
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

    private fun speakWithSystemTts(text: String, onComplete: () -> Unit) {
        Log.d(TAG, "Speaking via System TTS fallback")
        if (isTtsInitialized.get() && systemTts != null) {
            systemTts?.speak(text, TextToSpeech.QUEUE_FLUSH, null, "ray_tts_${System.currentTimeMillis()}")
            // System TTS doesn't block, so we set a timeout for completion
            _isPlaying.value = true
        } else {
            Log.e(TAG, "System TTS fallback not available")
            _isPlaying.value = false
            onComplete()
        }
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
