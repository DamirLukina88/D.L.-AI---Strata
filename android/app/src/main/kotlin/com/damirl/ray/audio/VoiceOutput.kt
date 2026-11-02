package com.damirl.ray.audio

import android.content.Context
import android.util.Log

// Ray's two voices: the native one (AudioPlaybackService, used by the voice drawer) and the web app's (TTSController in
// the WebView, used by the app's own mic button).  Ray must never listen while either is talking, or he hears himself:
// with the drawer still reading an answer aloud, the app's mic button transcribed that answer and sent it back to him
object VoiceOutput {

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
