package com.damirl.ray.audio

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.os.Build
import android.util.Log
import android.view.KeyEvent

class MediaButtonReceiver : BroadcastReceiver() {

    companion object {
        private const val TAG = "RayMediaReceiver"
    }

    override fun onReceive(context: Context, intent: Intent) {
        if (Intent.ACTION_MEDIA_BUTTON == intent.action) {
            val keyEvent = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
                intent.getParcelableExtra(Intent.EXTRA_KEY_EVENT, KeyEvent::class.java)
            } else {
                @Suppress("DEPRECATION")
                intent.getParcelableExtra(Intent.EXTRA_KEY_EVENT)
            }

            if (keyEvent != null) {
                Log.d(TAG, "Received MEDIA_BUTTON intent with keyEvent: ${keyEvent.keyCode}")
                MediaButtonHandler.handleKeyEvent(context, keyEvent)
            }
        }
    }
}
