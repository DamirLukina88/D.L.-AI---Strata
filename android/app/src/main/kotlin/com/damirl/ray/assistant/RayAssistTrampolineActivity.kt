package com.damirl.ray.assistant

import android.app.Activity
import android.content.Intent
import android.os.Build
import android.os.Bundle
import android.util.Log
import android.view.WindowManager

class RayAssistTrampolineActivity : Activity() {

    companion object {
        private const val TAG = "RayAssistTrampoline"
        const val EXTRA_START_LISTENING = "extra_start_listening"
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        Log.d(TAG, "RayAssistTrampolineActivity launched with action=${intent?.action}")

        // Allow showing over lockscreen if device is locked
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O_MR1) {
            setShowWhenLocked(true)
            setTurnScreenOn(true)
        } else {
            @Suppress("DEPRECATION")
            window.addFlags(
                WindowManager.LayoutParams.FLAG_SHOW_WHEN_LOCKED or
                WindowManager.LayoutParams.FLAG_TURN_SCREEN_ON
            )
        }

        val args = Bundle().apply {
            putString("action", intent?.action)
            putString("source", "bluetooth_or_trampoline")
        }

        // Try to invoke the system voice assistant overlay
        val shown = RayVoiceInteractionService.showSession(args)
        if (!shown) {
            // the assistant service isn't connected to this process (or Ray isn't the default assistant): the same
            // drawer as an activity, not the full app
            Log.d(TAG, "Voice interaction session unavailable -> RayVoiceActivity")
            startActivity(Intent(this, RayVoiceActivity::class.java).apply {
                action = intent?.action ?: Intent.ACTION_ASSIST
                flags = Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_SINGLE_TOP
            })
        }

        finish()
    }
}
