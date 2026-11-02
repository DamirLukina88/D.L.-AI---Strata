package com.damirl.ray.audio

import android.content.Context
import android.content.Intent
import android.os.Bundle
import android.speech.RecognitionListener
import android.speech.RecognizerIntent
import android.speech.SpeechRecognizer
import android.util.Log
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import java.util.Locale

class SpeechRecognitionManager(private val context: Context) {

    companion object {
        private const val TAG = "RaySTT"
    }

    private var speechRecognizer: SpeechRecognizer? = null

    private val _isListening = MutableStateFlow(false)
    val isListening: StateFlow<Boolean> = _isListening.asStateFlow()

    private val _partialText = MutableStateFlow("")
    val partialText: StateFlow<String> = _partialText.asStateFlow()

    private val _rmsLevel = MutableStateFlow(0f)
    val rmsLevel: StateFlow<Float> = _rmsLevel.asStateFlow()

    // onNoSpeech, when given, is called instead of onError when nothing was said (Google's recognizer gives up 5 s
    // after the mic opens if no speech has started, and that limit can't be raised), so the caller can listen again
    fun startListening(
        onFinalResult: (String) -> Unit,
        onError: (String) -> Unit,
        onNoSpeech: (() -> Unit)? = null
    ) {
        if (!SpeechRecognizer.isRecognitionAvailable(context)) {
            Log.e(TAG, "Speech recognition is not available on this device")
            onError("Speech recognition not available")
            return
        }

        stopListening()

        try {
            val recognizer = SpeechRecognizer.createSpeechRecognizer(context)
            var heardSpeech = false
            recognizer.setRecognitionListener(object : RecognitionListener {
                override fun onReadyForSpeech(params: Bundle?) {
                    Log.d(TAG, "SpeechRecognizer ready for speech")
                    _isListening.value = true
                    _partialText.value = ""
                }

                override fun onBeginningOfSpeech() {
                    Log.d(TAG, "User started speaking")
                    heardSpeech = true
                }

                override fun onRmsChanged(rmsdB: Float) {
                    _rmsLevel.value = rmsdB
                }

                override fun onBufferReceived(buffer: ByteArray?) {}

                override fun onEndOfSpeech() {
                    Log.d(TAG, "Speech ended")
                    _isListening.value = false
                }

                override fun onError(error: Int) {
                    val message = when (error) {
                        SpeechRecognizer.ERROR_AUDIO -> "Audio recording error"
                        SpeechRecognizer.ERROR_CLIENT -> "Client error"
                        SpeechRecognizer.ERROR_INSUFFICIENT_PERMISSIONS -> "Missing audio permission"
                        SpeechRecognizer.ERROR_NETWORK -> "Network error"
                        SpeechRecognizer.ERROR_NETWORK_TIMEOUT -> "Network timeout"
                        SpeechRecognizer.ERROR_NO_MATCH -> "No speech recognized"
                        SpeechRecognizer.ERROR_RECOGNIZER_BUSY -> "Recognizer busy"
                        SpeechRecognizer.ERROR_SERVER -> "Server error"
                        SpeechRecognizer.ERROR_SPEECH_TIMEOUT -> "No speech heard"
                        SpeechRecognizer.ERROR_SERVER_DISCONNECTED -> "Speech service disconnected"
                        else -> "Speech recognition error ($error)"
                    }
                    Log.w(TAG, "SpeechRecognizer error: $message (speech heard: $heardSpeech)")
                    _isListening.value = false
                    destroyRecognizer()
                    val silent = error == SpeechRecognizer.ERROR_NO_MATCH || error == SpeechRecognizer.ERROR_SPEECH_TIMEOUT
                    if (silent && onNoSpeech != null) onNoSpeech() else onError(message)
                }

                override fun onResults(results: Bundle?) {
                    val matches = results?.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION)
                    val text = matches?.firstOrNull()?.trim() ?: ""
                    Log.d(TAG, "Final transcription: '$text'")
                    _isListening.value = false
                    _partialText.value = text
                    destroyRecognizer()
                    when {
                        text.isNotBlank() -> onFinalResult(text)
                        onNoSpeech != null -> onNoSpeech()
                        else -> onError("No speech heard")
                    }
                }

                override fun onPartialResults(partialResults: Bundle?) {
                    val matches = partialResults?.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION)
                    val text = matches?.firstOrNull()?.trim() ?: ""
                    if (text.isNotBlank()) {
                        Log.d(TAG, "Partial transcription: '$text'")
                        _partialText.value = text
                    }
                }

                override fun onEvent(eventType: Int, params: Bundle?) {}
            })

            speechRecognizer = recognizer

            val intent = Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH).apply {
                putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL, RecognizerIntent.LANGUAGE_MODEL_FREE_FORM)
                putExtra(RecognizerIntent.EXTRA_PARTIAL_RESULTS, true)
                putExtra(RecognizerIntent.EXTRA_MAX_RESULTS, 1)
                // a language tag string: a Locale object is dropped by the recognizer (ClassCastException in its log)
                putExtra(RecognizerIntent.EXTRA_LANGUAGE, Locale.getDefault().toLanguageTag())
                // No EXTRA_SPEECH_INPUT_*_SILENCE_LENGTH_MILLIS: Google's on-device recognizer applies them to the wait
                // before speech too (2000 ms ended a listen 2 s after the mic opened), so its own 5 s is kept
            }

            recognizer.startListening(intent)
        } catch (e: Exception) {
            Log.e(TAG, "Error starting speech recognition", e)
            _isListening.value = false
            onError(e.message ?: "Failed to start listening")
        }
    }

    fun stopListening() {
        try {
            speechRecognizer?.stopListening()
        } catch (_: Exception) {}
        _isListening.value = false
    }

    fun cancel() {
        destroyRecognizer()
        _isListening.value = false
        _partialText.value = ""
    }

    private fun destroyRecognizer() {
        try {
            speechRecognizer?.destroy()
        } catch (_: Exception) {}
        speechRecognizer = null
    }
}
