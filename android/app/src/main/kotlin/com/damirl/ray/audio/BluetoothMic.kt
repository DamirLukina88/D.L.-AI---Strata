package com.damirl.ray.audio

import android.content.Context
import android.media.AudioDeviceInfo
import android.media.AudioManager
import android.os.Build
import android.os.Handler
import android.os.Looper
import android.util.Log

// The microphone of a connected Bluetooth headset (a helmet intercom, earbuds) while Ray listens.  A headset's mic only
// works over its call link (SCO), which Android opens when an app makes the headset the communication device; without
// this the recognizer records from the phone's own mic.  Released a moment after listening ends (so a quick second
// listen keeps the link), which lets the reply play over the headset's music link (A2DP) at full quality
class BluetoothMic(context: Context) {

    companion object {
        private const val TAG = "RayBtMic"
        private const val LINK_TIMEOUT_MS = 2500L      // start listening anyway if the link hasn't come up by then
        private const val SETTLE_MS = 300L             // the routing switch is reported a little before audio flows
        private const val RELEASE_DELAY_MS = 1000L
    }

    private val audioManager = context.getSystemService(AudioManager::class.java)
    private val handler = Handler(Looper.getMainLooper())
    private var owned = false                          // we made the headset the communication device
    private var pendingListener: Any? = null           // AudioManager.OnCommunicationDeviceChangedListener (API 31+)
    private var pendingTimeout: Runnable? = null
    private var pendingReady: Runnable? = null
    private val releaseNow = Runnable { clear() }

    /** Calls onReady once the headset mic is live, at once when no headset with a mic is connected. */
    fun acquire(onReady: () -> Unit) {
        handler.removeCallbacks(releaseNow)
        cancelPending()
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.S || audioManager == null) { onReady(); return }
        val sco = audioManager.availableCommunicationDevices.firstOrNull { it.type == AudioDeviceInfo.TYPE_BLUETOOTH_SCO }
        if (sco == null) { onReady(); return }
        if (audioManager.communicationDevice?.id == sco.id) {
            Log.d(TAG, "Headset mic already live: ${sco.productName}")
            onReady()
            return
        }

        var fired = false
        val fire = { reason: String ->
            if (!fired) {
                fired = true
                cancelPending()
                Log.d(TAG, "Listening via ${sco.productName}: $reason")
                val ready = Runnable { pendingReady = null; onReady() }
                pendingReady = ready
                handler.postDelayed(ready, SETTLE_MS)
            }
        }
        val listener = AudioManager.OnCommunicationDeviceChangedListener { device ->
            if (device?.id == sco.id) fire("link up")
        }
        audioManager.addOnCommunicationDeviceChangedListener({ handler.post(it) }, listener)
        pendingListener = listener
        if (!audioManager.setCommunicationDevice(sco)) {
            Log.w(TAG, "setCommunicationDevice(${sco.productName}) refused; using the phone mic")
            cancelPending()
            onReady()
            return
        }
        owned = true
        val timeout = Runnable { fire("link not confirmed after ${LINK_TIMEOUT_MS} ms") }
        pendingTimeout = timeout
        handler.postDelayed(timeout, LINK_TIMEOUT_MS)
    }

    /** Hands the mic back to the phone shortly, unless Ray listens again first. */
    fun release() {
        cancelPending()
        pendingReady?.let { handler.removeCallbacks(it) }
        pendingReady = null
        handler.removeCallbacks(releaseNow)
        if (owned) handler.postDelayed(releaseNow, RELEASE_DELAY_MS)
    }

    private fun clear() {
        if (owned && Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
            audioManager?.clearCommunicationDevice()
            Log.d(TAG, "Headset mic released")
        }
        owned = false
    }

    private fun cancelPending() {
        pendingTimeout?.let { handler.removeCallbacks(it) }
        pendingTimeout = null
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
            (pendingListener as? AudioManager.OnCommunicationDeviceChangedListener)?.let {
                audioManager?.removeOnCommunicationDeviceChangedListener(it)
            }
        }
        pendingListener = null
    }
}
