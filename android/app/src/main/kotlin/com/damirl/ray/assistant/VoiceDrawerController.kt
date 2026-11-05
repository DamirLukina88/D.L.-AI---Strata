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
import com.damirl.ray.audio.VoiceTrace
import com.damirl.ray.network.ChatDelta
import com.damirl.ray.network.ChatMessage
import com.damirl.ray.network.NetworkClient
import com.damirl.ray.network.RayChatRepository
import com.damirl.ray.tools.HttpPhoneRelayLink
import com.damirl.ray.tools.PhoneToolRelay
import com.damirl.ray.tools.PhoneTools
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
        // the open drawer (the system overlay or RayVoiceActivity) closes itself with this; null when none is open
        @Volatile var closeOpen: (() -> Unit)? = null

        // debug builds, from adb only (RayToolsReceiver): what the next drawer asks instead of listening.  Its answer
        // isn't spoken, so a test can run at night with no headset; the trace has it
        @Volatile var scriptedPrompt: String? = null

        /** Closes the open drawer (main thread): it covers Brave, whose Play button Ray must reach to start a song. */
        fun closeIfOpen(): Boolean {
            val close = closeOpen ?: return false
            android.os.Handler(android.os.Looper.getMainLooper()).post { close() }
            return true
        }

        private const val TAG = "RayVoiceDrawer"
        // Google's recognizer stops 5 s after the mic opens if nobody has started talking; listen once more before
        // giving up, so there are 10 s to start (holding the power button, then finding words, often takes longer)
        private const val NO_SPEECH_RETRIES = 1
    }

    private val networkClient = NetworkClient.shared
    private val chatRepository = RayChatRepository(networkClient)
    // runs Ray's phone tools during a turn; nothing else does with the phone locked and away from home
    private val phoneRelay by lazy {
        PhoneToolRelay(HttpPhoneRelayLink(networkClient), PhoneTools(context.applicationContext)::execute)
    }
    private var speechManager: SpeechRecognitionManager? = SpeechRecognitionManager(context)
    private var noSpeechRetries = 0
    private var askJob: Job? = null
    private var retryJob: Job? = null
    private var probeJob: Job? = null
    private var closed = false
    private var silent = false                  // a scripted prompt: nothing is said aloud

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
        VoiceTrace.init(context)
        com.damirl.ray.audio.BluetoothMic.init(context)
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
        VoiceTrace.event("drawer_start")
        // while you speak; ask() waits for it, so the question goes over the route found now (LAN or the tunnel)
        probeJob = scope.launch { networkClient.probeAndSelectRoute() }
        val scripted = scriptedPrompt.takeIf { com.damirl.ray.BuildConfig.DEBUG }
        scriptedPrompt = null
        silent = scripted != null
        if (scripted != null) {
            userPrompt = scripted
            ask(scripted)
        } else {
            listen()
        }
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
        VoiceTrace.event("drawer_close", "phase" to phase.name)
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
        VoiceTrace.event("listen", "retry" to noSpeechRetries)

        speechManager?.startListening(
            onFinalResult = { transcribed ->
                if (com.damirl.ray.BuildConfig.DEBUG) Log.d(TAG, "Heard: '$transcribed'")
                userPrompt = transcribed
                partialText = ""
                ask(transcribed)
            },
            onError = { err ->
                Log.w(TAG, "Listening failed: $err")
                VoiceTrace.event("listen_failed", "error" to err)
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
                    VoiceTrace.event("listen_gave_up")
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
            probeJob?.join()                                // the route the drawer is probing while you speak
            val relay = launch { phoneRelay.run() }         // a child: closing the drawer stops it too
            var accumulated = ""
            var spokenFrom = 0          // read aloud: only what follows the last tool call (see below)
            var failed = false
            for (attempt in 0..1) {
                var received = false
                var unreached: Throwable? = null
                VoiceTrace.event("ask", "route" to NetworkClient.label(networkClient.currentRoute.value),
                    "chars" to text.length, "attempt" to attempt)
                chatRepository.streamChat(messages, isVoice = true)
                    .catch { error ->
                        // the server was never reached (the LAN gone, say): probe again and send it once more
                        if (!received && attempt == 0 && NetworkClient.isConnectFailure(error)) {
                            unreached = error
                            return@catch
                        }
                        failed = true
                        VoiceTrace.event("answer_error", "error" to (error.message ?: error.javaClass.simpleName))
                        phase = VoicePhase.ERROR
                        assistantResponse = "Error: ${error.message}"
                        status = "Can't reach the server"
                    }
                    .collect { piece ->
                        if (!received) {
                            received = true
                            VoiceTrace.event("answer_first", "kind" to piece.javaClass.simpleName,
                                "ms" to System.currentTimeMillis() - askedAt)
                        }
                        when (piece) {
                            is ChatDelta.Thinking -> thinkingText += piece.text
                            is ChatDelta.Tool -> {
                                lastTool = piece.name
                                toolCalls++
                                VoiceTrace.event("answer_tool", "name" to piece.name)
                                // the line before a tool ("Searching YouTube Music for it...") fills the silence in the
                                // web app, which reads as it streams; the drawer speaks once at the end, so it was only
                                // extra talk before the confirmation
                                spokenFrom = accumulated.length
                                activeToolNote = toolNote(piece.name)
                            }
                            is ChatDelta.Text -> {
                                if (phase != VoicePhase.ANSWERING) {
                                    phase = VoicePhase.ANSWERING
                                    status = "Answering…"
                                    VoiceTrace.event("answer_text", "ms" to System.currentTimeMillis() - askedAt)
                                    if (thinkingText.isNotBlank()) {
                                        thoughtSeconds = ((System.currentTimeMillis() - askedAt) / 1000).toInt().coerceAtLeast(1)
                                    }
                                }
                                accumulated += piece.text
                                assistantResponse = accumulated
                            }
                        }
                    }
                val retryWith = unreached ?: break
                Log.w(TAG, "Server not reached (${retryWith.message}); probing again")
                VoiceTrace.event("ask_unreached", "error" to (retryWith.message ?: retryWith.javaClass.simpleName))
                networkClient.probeAndSelectRoute()
            }
            relay.cancel()                                  // the turn is over: no more tool calls

            if (failed) return@launch
            phase = VoicePhase.IDLE
            status = "Tap the mic to ask again"

            val spoken = accumulated.substring(spokenFrom).ifBlank { accumulated }
            VoiceTrace.event("answer_done", "chars" to accumulated.length, "spoken_chars" to spoken.length,
                "ms" to System.currentTimeMillis() - askedAt,
                "text" to if (com.damirl.ray.BuildConfig.DEBUG) spoken.take(400) else null)
            if (spoken.isNotBlank() && !closed && !silent) {
                AudioPlaybackService.startSpeaking(context, spoken)
            }
        }
    }
}
