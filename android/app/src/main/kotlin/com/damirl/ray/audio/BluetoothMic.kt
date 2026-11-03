package com.damirl.ray.audio

import android.content.Context
import android.media.AudioDeviceInfo
import android.media.AudioManager
import android.os.Build
import android.os.Handler
import android.os.Looper
import android.os.SystemClock
import android.util.Log

// A connected Bluetooth headset's call link (SCO) while Ray listens and, after you spoke through the headset, while
// he answers.  A headset's mic only works over that link, which Android opens when an app makes the headset the
// communication device; without it the recognizer records from the phone's mic.  The answer goes over it too: helmet
// intercoms (Sena) put calls above intercom and music, and played Ray's answer over the music link (A2DP) not at all.
// One link for the whole app: each user (listening, a native reply, the web app's reply) holds it by name, and it is
// handed back a moment after the last one lets go (so a quick second listen, or listen then answer, keeps it)
object BluetoothMic {

    private const val TAG = "RayBtMic"
    private const val LINK_TIMEOUT_MS = 2500L      // go ahead anyway if the link hasn't come up by then
    private const val SETTLE_MS = 300L             // the routing switch is reported a little before audio flows
    // a link that was down: a helmet (Sena) plays its own tone and needs about a second before the mic's audio
    // flows; with 300 ms the recognizer's first listen heard the user's first words hardly or not at all
    private const val COLD_SETTLE_MS = 1200L
    private const val RELEASE_DELAY_MS = 1000L
    private const val CONVERSATION_MS = 120_000L   // an answer within 2 min of speaking through the headset uses it

    private val handler = Handler(Looper.getMainLooper())
    private var audioManager: AudioManager? = null
    private val holders = mutableSetOf<String>()
    private val waiting = mutableMapOf<String, () -> Unit>()   // holders waiting for the link to come up
    private var owned = false                                   // we made the headset the communication device
    private var linkUp = false
    private var pendingListener: Any? = null                    // AudioManager.OnCommunicationDeviceChangedListener
    private var pendingTimeout: Runnable? = null
    private var lastHeadsetListenAt = 0L
    private val releaseNow = Runnable { clear() }

    /** True when Ray last listened through a headset less than 2 minutes ago: his answer should go back the same way. */
    fun inHeadsetConversation(): Boolean =
        lastHeadsetListenAt != 0L && SystemClock.elapsedRealtime() - lastHeadsetListenAt < CONVERSATION_MS

    /**
     * Holds the headset link for [holder] and calls onReady once it is live, at once when no headset with a mic is
     * connected (the phone's mic and speaker are used then).  Main thread only.
     */
    fun acquire(context: Context, holder: String, onReady: () -> Unit) {
        val am = audioManager ?: context.applicationContext.getSystemService(AudioManager::class.java).also { audioManager = it }
        handler.removeCallbacks(releaseNow)
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.S || am == null) { onReady(); return }
        val sco = am.availableCommunicationDevices.firstOrNull { it.type == AudioDeviceInfo.TYPE_BLUETOOTH_SCO }
        if (sco == null) { onReady(); return }
        holders.add(holder)
        if (holder == "listen") lastHeadsetListenAt = SystemClock.elapsedRealtime()

        if (owned && linkUp && am.communicationDevice?.id == sco.id) {
            Log.d(TAG, "$holder: headset link already live (${sco.productName})")
            onReady()
            return
        }
        waiting[holder] = onReady
        if (pendingListener != null) return                     // already coming up: onReady runs with the others
        val cold = !owned                                       // not held a moment ago (released, or never)

        val fire = { reason: String ->
            if (pendingListener != null || pendingTimeout != null) {
                cancelPending()
                linkUp = true
                Log.d(TAG, "Headset link ${sco.productName}: $reason, for ${waiting.keys}")
                handler.postDelayed({
                    val ready = waiting.values.toList()
                    waiting.clear()
                    ready.forEach { it() }
                }, if (cold) COLD_SETTLE_MS else SETTLE_MS)
            }
        }
        val listener = AudioManager.OnCommunicationDeviceChangedListener { device ->
            if (device?.id == sco.id) fire("up")
        }
        am.addOnCommunicationDeviceChangedListener({ handler.post(it) }, listener)
        pendingListener = listener
        if (!am.setCommunicationDevice(sco)) {
            Log.w(TAG, "setCommunicationDevice(${sco.productName}) refused; using the phone")
            cancelPending()
            val ready = waiting.values.toList()
            waiting.clear()
            ready.forEach { it() }
            return
        }
        owned = true
        linkUp = false
        val timeout = Runnable { fire("not confirmed after $LINK_TIMEOUT_MS ms") }
        pendingTimeout = timeout
        handler.postDelayed(timeout, LINK_TIMEOUT_MS)
    }

    /** No one holds the headset link and it is handed back: the music link (A2DP) plays again. */
    fun idle(): Boolean = holders.isEmpty() && !owned

    /** Lets go for [holder]; the link is handed back to the phone shortly after the last holder lets go. */
    fun release(holder: String) {
        holders.remove(holder)
        waiting.remove(holder)
        if (holders.isEmpty()) {
            cancelPending()
            handler.removeCallbacks(releaseNow)
            if (owned) handler.postDelayed(releaseNow, RELEASE_DELAY_MS)
        }
    }

    private fun clear() {
        if (holders.isNotEmpty()) return
        if (owned && Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
            audioManager?.clearCommunicationDevice()
            Log.d(TAG, "Headset link released")
        }
        owned = false
        linkUp = false
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
