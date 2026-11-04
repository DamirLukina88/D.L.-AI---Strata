package com.damirl.ray.audio

import android.content.Context
import android.content.Intent
import android.os.SystemClock
import android.util.Log
import android.view.KeyEvent
import com.damirl.ray.assistant.RayAssistTrampolineActivity
import com.damirl.ray.assistant.RayVoiceInteractionService

object MediaButtonHandler {

    private const val TAG = "RayMediaButton"
    private const val DOUBLE_CLICK_TIMEOUT_MS = 500L

    private var lastClickTime = 0L
    private var clickCount = 0

    /**
     * Handles incoming media key events from headsets, earbuds, or lock screen controls.
     * Returns true if the event was consumed.
     */
    fun handleKeyEvent(context: Context, keyEvent: KeyEvent): Boolean {
        Log.d(
            TAG,
            "Media key event received: action=${keyEvent.action}, keyCode=${keyEvent.keyCode}, repeatCount=${keyEvent.repeatCount}"
        )
        VoiceTrace.init(context)
        VoiceTrace.event("media_key", "code" to keyEvent.keyCode, "action" to keyEvent.action, "repeat" to keyEvent.repeatCount)

        // Only handle key release to avoid double-processing down + up
        if (keyEvent.action != KeyEvent.ACTION_UP) {
            return false
        }

        // Ignore long-press auto-repeats
        if (keyEvent.repeatCount > 0) {
            return false
        }

        val isMediaKey = when (keyEvent.keyCode) {
            KeyEvent.KEYCODE_HEADSETHOOK,
            KeyEvent.KEYCODE_MEDIA_PLAY_PAUSE,
            KeyEvent.KEYCODE_MEDIA_PLAY,
            KeyEvent.KEYCODE_MEDIA_PAUSE -> true
            else -> false
        }

        if (!isMediaKey) {
            return false
        }

        val now = SystemClock.uptimeMillis()
        if (now - lastClickTime < DOUBLE_CLICK_TIMEOUT_MS) {
            clickCount++
        } else {
            clickCount = 1
        }
        lastClickTime = now

        Log.d(TAG, "Media button click count: $clickCount")

        if (clickCount >= 2) {
            clickCount = 0
            lastClickTime = 0L
            Log.d(TAG, "Double-tap detected on media button -> Waking Ray Assistant! 🐾")
            VoiceTrace.event("trigger", "action" to "media double tap", "via" to "media button",
                *VoiceTrace.deviceState(context))
            triggerRayAssistant(context)
            return true
        } else {
            // Single tap: if audio is actively speaking, stop it
            if (AudioPlaybackService.isSpeakingState.value) {
                Log.d(TAG, "Single tap while speaking -> Stopping speech")
                AudioPlaybackService.stopSpeaking(context)
                return true
            }
        }

        return false
    }

    fun triggerRayAssistant(context: Context) {
        val shown = RayVoiceInteractionService.showSession()
        if (!shown) {
            Log.d(TAG, "Voice interaction session not active or ready -> Launching Assist Trampoline")
            val intent = Intent(context, RayAssistTrampolineActivity::class.java).apply {
                flags = Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP
            }
            context.startActivity(intent)
        }
    }
}
