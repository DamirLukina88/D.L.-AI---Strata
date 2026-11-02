package com.damirl.ray.assistant

import android.content.Context
import android.util.Log
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import com.damirl.ray.audio.AudioPlaybackService
import com.damirl.ray.audio.SpeechRecognitionManager
import com.damirl.ray.audio.VoiceOutput
import com.damirl.ray.network.ChatDelta
import com.damirl.ray.network.ChatMessage
import com.damirl.ray.network.NetworkClient
import com.damirl.ray.network.RayChatRepository
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.catch
import kotlinx.coroutines.launch

// What the voice drawer does, apart from where it is shown: listening (with one more try when nothing was said),
// sending what you said to Ray, and reading his answer aloud.  Used by RayVoiceSession (the system assistant overlay)
// and RayVoiceActivity (the same drawer as an activity, when the assistant service isn't connected)
class VoiceDrawerController(private val context: Context, private val scope: CoroutineScope) {

    companion object {
        private const val TAG = "RayVoiceDrawer"
        // Google's recognizer stops 5 s after the mic opens if nobody has started talking; listen once more before
        // giving up, so there are 10 s to start (holding the power button, then finding words, often takes longer)
        private const val NO_SPEECH_RETRIES = 1
    }

    private val networkClient = NetworkClient()
    private val chatRepository = RayChatRepository(networkClient)
    private var speechManager: SpeechRecognitionManager? = SpeechRecognitionManager(context)
    private var noSpeechRetries = 0
    private var askJob: Job? = null
    private var retryJob: Job? = null
    private var closed = false

    // UI state observable by Compose
    var phase by mutableStateOf(VoicePhase.LISTENING)
        private set
    var status by mutableStateOf("Listening…")
        private set
    var userPrompt by mutableStateOf("")
        private set
    var partialText by mutableStateOf("")
        private set
    var micLevel by mutableFloatStateOf(0f)
        private set
    var assistantResponse by mutableStateOf("")
        private set
    var activeToolNote by mutableStateOf<String?>(null)
        private set
    /** The model's thinking for this answer, streamed; shown in the drawer, never read aloud. */
    var thinkingText by mutableStateOf("")
        private set
    /** How long he thought, once the answer started (null while still thinking or with no thinking). */
    var thoughtSeconds by mutableStateOf<Int?>(null)
        private set
    /** How many tools he called in this answer (the panda reacts to each). */
    var toolCalls by mutableStateOf(0)
        private set

    init {
        // the live transcript and the mic level drive the drawer while it listens
        speechManager?.let { manager ->
            scope.launch { manager.partialText.collect { if (phase == VoicePhase.LISTENING) partialText = it } }
            scope.launch { manager.rmsLevel.collect { micLevel = it } }
        }
    }

    /** The drawer was opened: start over and listen. */
    fun start() {
        closed = false
        WakeWord.hold("drawer")
        userPrompt = ""
        assistantResponse = ""
        activeToolNote = null
        thinkingText = ""
        thoughtSeconds = null
        noSpeechRetries = 0
        scope.launch { networkClient.probeAndSelectRoute() }
        listen()
    }

    fun onMicTap() {
        if (phase == VoicePhase.LISTENING) {
            speechManager?.stopListening()
        } else {
            noSpeechRetries = 0
            listen()
        }
    }

    /**
     * The drawer was closed, swiped away or lost focus: stop listening, drop the answer it was waiting for and stop
     * reading one aloud, so Ray neither listens nor talks with nobody looking (the app's mic would hear him otherwise)
     */
    fun close() {
        if (closed) return
        closed = true
        Log.d(TAG, "Drawer closed: stopping listening and speech")
        WakeWord.release("drawer")
        retryJob?.cancel()
        askJob?.cancel()
        speechManager?.cancel()
        VoiceOutput.stopNative(context)
        if (phase == VoicePhase.LISTENING || phase == VoicePhase.THINKING || phase == VoicePhase.ANSWERING) {
            phase = VoicePhase.IDLE
            status = "Tap the mic to ask again"
        }
    }

    fun destroy() {
        close()
        speechManager?.cancel()
        speechManager = null
    }

    private fun listen() {
        phase = VoicePhase.LISTENING
        status = if (noSpeechRetries > 0) "Still listening…" else "Listening…"
        userPrompt = ""
        partialText = ""
        activeToolNote = null

        speechManager?.startListening(
            onFinalResult = { transcribed ->
                Log.d(TAG, "Heard: '$transcribed'")
                userPrompt = transcribed
                partialText = ""
                ask(transcribed)
            },
            onError = { err ->
                Log.w(TAG, "Listening failed: $err")
                phase = VoicePhase.ERROR
                status = "Couldn't listen: $err"
            },
            onNoSpeech = {
                if (noSpeechRetries < NO_SPEECH_RETRIES) {
                    noSpeechRetries++
                    Log.d(TAG, "No speech yet, listening again ($noSpeechRetries)")
                    status = "Still listening…"
                    // the recognizer service is still disconnecting from the last attempt; starting at once fails (11)
                    retryJob = scope.launch {
                        delay(400)
                        if (!closed && phase == VoicePhase.LISTENING) listen()
                    }
                } else {
                    phase = VoicePhase.IDLE
                    status = "I didn't catch that"
                    partialText = ""
                }
            }
        )
    }

    /** The last tool Ray called in this answer (the panda picks his work prop from it). */
    var lastTool: String? = null
        private set

    // "Using a phone tool…", "Using Home Assistant…": MCP tools arrive as server__tool
    private fun toolNote(name: String): String {
        val server = name.substringBefore("__", "")
        return when {
            name.startsWith("phone_") || server == "phone" -> "Using a phone tool…"
            server == "homeassistant" -> "Using Home Assistant…"
            server.isNotEmpty() -> "Using $server…"
            else -> "Using a tool…"
        }
    }

    private fun ask(text: String) {
        if (text.isBlank()) return

        phase = VoicePhase.THINKING
        status = "Thinking…"
        assistantResponse = ""
        activeToolNote = null
        thinkingText = ""
        thoughtSeconds = null
        lastTool = null

        val messages = listOf(ChatMessage(role = "user", content = text))
        val askedAt = System.currentTimeMillis()

        askJob = scope.launch {
            var accumulated = ""
            var failed = false
            chatRepository.streamChat(messages, isVoice = true)
                .catch { error ->
                    failed = true
                    phase = VoicePhase.ERROR
                    assistantResponse = "Error: ${error.message}"
                    status = "Can't reach the server"
                }
                .collect { piece ->
                    when (piece) {
                        is ChatDelta.Thinking -> thinkingText += piece.text
                        is ChatDelta.Tool -> {
                            lastTool = piece.name
                            toolCalls++
                            activeToolNote = toolNote(piece.name)
                        }
                        is ChatDelta.Text -> {
                            if (phase != VoicePhase.ANSWERING) {
                                phase = VoicePhase.ANSWERING
                                status = "Answering…"
                                if (thinkingText.isNotBlank()) {
                                    thoughtSeconds = ((System.currentTimeMillis() - askedAt) / 1000).toInt().coerceAtLeast(1)
                                }
                            }
                            accumulated += piece.text
                            assistantResponse = accumulated
                        }
                    }
                }

            if (failed) return@launch
            phase = VoicePhase.IDLE
            status = "Tap the mic to ask again"

            if (accumulated.isNotBlank() && !closed) {
                AudioPlaybackService.startSpeaking(context, accumulated)
            }
        }
    }
}
