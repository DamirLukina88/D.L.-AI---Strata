package com.damirl.ray.audio

import android.content.Context
import android.util.Log
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow

// Ray's two voices: the native one (AudioPlaybackService, used by the voice drawer) and the web app's (TTSController in
// the WebView, used by the app's own mic button).  Ray must never listen while either is talking, or he hears himself:
// with the drawer still reading an answer aloud, the app's mic button transcribed that answer and sent it back to him
object VoiceOutput {

    /** A piece of Ray's voice sounding now: its text and how long it has left, for his mouth. */
    data class Piece(val text: String, val seconds: Double)

    private val _sounding = MutableStateFlow<Piece?>(null)
    /** Set when sound really starts (the player's position moves) and cleared the moment it ends. */
    val sounding: StateFlow<Piece?> = _sounding.asStateFlow()

    /** The app's page: told the same, for the panda in its Code tab; set by RayNativeBridge. */
    @Volatile
    var onSounding: ((Piece?) -> Unit)? = null

    fun setSounding(piece: Piece?) {
        if (piece == null && _sounding.value == null) return
        _sounding.value = piece
        onSounding?.invoke(piece)
        VoiceTrace.event(if (piece != null) "voice_on" else "voice_off", "seconds" to piece?.seconds)
    }

    private const val TAG = "RayVoiceOutput"

    /** Stops the web app's voice; set by RayNativeBridge for the WebView it belongs to. */
    @Volatile
    var stopWebSpeech: (() -> Unit)? = null

    /** Silences the native voice (only if it is talking: each stop call starts the playback service). */
    fun stopNative(context: Context) {
        if (AudioPlaybackService.isSpeakingState.value) {
            Log.d(TAG, "Stopping the native voice")
            AudioPlaybackService.stopSpeaking(context)
        }
    }

    /** Silences both voices, before Ray listens. */
    fun stopAll(context: Context) {
        stopNative(context)
        stopWebSpeech?.invoke()
    }
}
