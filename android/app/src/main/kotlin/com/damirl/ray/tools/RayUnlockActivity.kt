package com.damirl.ray.tools

import android.app.Activity
import android.app.KeyguardManager
import android.content.Context
import android.content.Intent
import android.os.Bundle
import android.os.SystemClock
import android.util.Log

// Ray starts a song by pressing Play in Brave, which a locked phone hides.  While a trusted device is connected
// (the helmet, through Smart Lock / Extend Unlock) the phone needs no PIN: this invisible screen wakes it and
// dismisses the lock screen, and RayMediaController locks it again once the music plays.  With the phone really
// locked (it would ask for the PIN) it is never started: Ray doesn't put a PIN prompt on a screen in a pocket
class RayUnlockActivity : Activity() {

    companion object {
        private const val TAG = "RayUnlock"

        /** The lock screen shows, but the phone is trusted (no PIN needed): it can be dismissed. */
        fun dismissable(context: Context): Boolean {
            val keyguard = context.getSystemService(Context.KEYGUARD_SERVICE) as? KeyguardManager ?: return false
            return keyguard.isKeyguardLocked && !keyguard.isDeviceLocked
        }

        /** Dismisses a trusted phone's lock screen; true when it is gone (within [timeoutMs]). Not the main thread. */
        fun dismiss(context: Context, timeoutMs: Long = 3_000): Boolean {
            if (!dismissable(context)) return !isKeyguardShowing(context)
            context.startActivity(Intent(context, RayUnlockActivity::class.java)
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_NO_ANIMATION))
            val end = SystemClock.uptimeMillis() + timeoutMs
            while (isKeyguardShowing(context) && SystemClock.uptimeMillis() < end) Thread.sleep(100)
            return !isKeyguardShowing(context)
        }

        private fun isKeyguardShowing(context: Context) =
            (context.getSystemService(Context.KEYGUARD_SERVICE) as? KeyguardManager)?.isKeyguardLocked ?: true
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val keyguard = getSystemService(KeyguardManager::class.java)
        if (keyguard == null || keyguard.isDeviceLocked) { finish(); return }      // would ask for the PIN
        keyguard.requestDismissKeyguard(this, object : KeyguardManager.KeyguardDismissCallback() {
            override fun onDismissSucceeded() { Log.d(TAG, "Lock screen dismissed (trusted)"); finish() }
            override fun onDismissCancelled() { Log.d(TAG, "Dismiss cancelled"); finish() }
            override fun onDismissError() { Log.d(TAG, "Dismiss failed"); finish() }
        })
    }
}
