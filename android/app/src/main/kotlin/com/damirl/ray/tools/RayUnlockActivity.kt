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
        private const val EXTRA_HOLD_CAMERA = "hold_for_camera"
        @Volatile private var cameraHoldInstance: RayUnlockActivity? = null

        /** Brings a translucent lock-screen window to the front briefly so CameraX can capture while locked/backgrounded. */
        fun startCameraHold(context: Context, timeoutMs: Long = 1_500): Boolean {
            if (cameraHoldInstance != null) return true
            return try {
                context.startActivity(Intent(context, RayUnlockActivity::class.java).apply {
                    putExtra(EXTRA_HOLD_CAMERA, true)
                    addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_NO_ANIMATION)
                })
                val end = SystemClock.uptimeMillis() + timeoutMs
                while (cameraHoldInstance == null && SystemClock.uptimeMillis() < end) Thread.sleep(50)
                cameraHoldInstance != null
            } catch (e: Exception) {
                Log.w(TAG, "Could not start camera hold activity: ${e.message}")
                false
            }
        }

        fun finishCameraHold() {
            val act = cameraHoldInstance ?: return
            cameraHoldInstance = null
            act.runOnUiThread { act.finish() }
        }

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
        if (intent?.getBooleanExtra(EXTRA_HOLD_CAMERA, false) == true) {
            if (android.os.Build.VERSION.SDK_INT >= android.os.Build.VERSION_CODES.O_MR1) {
                setShowWhenLocked(true)
                setTurnScreenOn(true)
            }
            cameraHoldInstance = this
            return
        }
        val keyguard = getSystemService(KeyguardManager::class.java)
        if (keyguard == null || keyguard.isDeviceLocked) { finish(); return }      // would ask for the PIN
        keyguard.requestDismissKeyguard(this, object : KeyguardManager.KeyguardDismissCallback() {
            override fun onDismissSucceeded() { Log.d(TAG, "Lock screen dismissed (trusted)"); finish() }
            override fun onDismissCancelled() { Log.d(TAG, "Dismiss cancelled"); finish() }
            override fun onDismissError() { Log.d(TAG, "Dismiss failed"); finish() }
        })
    }

    override fun onDestroy() {
        if (cameraHoldInstance == this) cameraHoldInstance = null
        super.onDestroy()
    }
}
