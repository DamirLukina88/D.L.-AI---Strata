package com.damirl.ray.audio

import android.bluetooth.BluetoothAdapter
import android.bluetooth.BluetoothDevice
import android.bluetooth.BluetoothHeadset
import android.bluetooth.BluetoothManager
import android.bluetooth.BluetoothProfile
import android.content.Context
import android.media.AudioDeviceInfo
import android.media.AudioManager
import android.os.Build
import android.os.Handler
import android.os.Looper
import android.os.SystemClock
import android.util.Log

// A connected Bluetooth headset's mic link (SCO) while Ray listens and, after you spoke through the headset, while he
// answers.  A headset's mic only works over that link; without it the recognizer records from the phone's mic.
// Helmet intercoms (Sena) put calls above intercom and music, and played Ray's answer over the music link (A2DP) not at
// all, so the answer goes over the link too.
//
// Two ways to open it:
//  - voice recognition (BluetoothHeadset.startVoiceRecognition), for listening.  It answers the headset's own request
//    (holding the helmet's button sends "start voice recognition") and opens the mic as a voice-recognition link.
//    Measured 2026-11-04 on the Sena: the other way below gave the recognizer silence from the helmet's mic in 4 of 5
//    listens, Android closed it ~6 s in (it keeps a link only for an app that plays or records itself, and Google's
//    recognizer records, not Ray), and the helmet, never told that voice recognition ended, took the next hold of its
//    button as "stop"
//  - the call link (AudioManager.setCommunicationDevice, which Android opens as a virtual call), for Ray's answer: it
//    played in the helmet; and for listening when voice recognition can't be started
// One link for the whole app: each user (listening, a native reply, the web app's reply) holds it by name, and it is
// handed back a moment after the last one lets go (so a quick second listen, or listen then answer, keeps it)
object BluetoothMic {

    private const val TAG = "RayBtMic"
    private const val PREFS = "ray_debug"
    private const val KEY_LINK_MODE = "link_mode"     // auto | vr | call (MicProbeActivity sets it, for testing)
    private const val LINK_TIMEOUT_MS = 2500L      // go ahead anyway if the link hasn't come up by then
    private const val SETTLE_MS = 300L             // the routing switch is reported a little before audio flows
    // a call link that was down: a helmet (Sena) plays its own tone and needs about a second before the mic's audio
    // flows; with 300 ms the recognizer's first listen heard the user's first words hardly or not at all
    private const val COLD_SETTLE_MS = 1200L
    // a voice-recognition link: the mic is reported up when audio flows (to be measured with MicProbeActivity)
    private const val VR_SETTLE_MS = 300L
    private const val POLL_MS = 50L
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

    // voice recognition: the headset profile, and the device we started it on (null: not started by us)
    @Volatile private var headset: BluetoothHeadset? = null
    private var proxyRequested = false
    private var vrDevice: BluetoothDevice? = null
    private var vrUp = false
    private var vrPoll: Runnable? = null

    /** True when Ray last listened through a headset less than 2 minutes ago: his answer should go back the same way. */
    fun inHeadsetConversation(): Boolean =
        lastHeadsetListenAt != 0L && SystemClock.elapsedRealtime() - lastHeadsetListenAt < CONVERSATION_MS

    /** Connects to the headset profile once (asynchronous), so voice recognition can be started on a press. */
    fun init(context: Context) {
        if (proxyRequested) return
        proxyRequested = true
        try {
            val adapter: BluetoothAdapter? = context.getSystemService(BluetoothManager::class.java)?.adapter
            adapter?.getProfileProxy(context.applicationContext, object : BluetoothProfile.ServiceListener {
                override fun onServiceConnected(profile: Int, proxy: BluetoothProfile) {
                    headset = proxy as? BluetoothHeadset
                    Log.d(TAG, "Headset profile connected")
                }

                override fun onServiceDisconnected(profile: Int) {
                    headset = null
                }
            }, BluetoothProfile.HEADSET)
        } catch (e: SecurityException) {
            Log.w(TAG, "No Bluetooth permission for the headset profile", e)
        }
    }

    /** "auto" (voice recognition to listen), "vr" or "call"; set only for testing. */
    fun linkMode(context: Context): String =
        context.getSharedPreferences(PREFS, Context.MODE_PRIVATE).getString(KEY_LINK_MODE, "auto") ?: "auto"

    fun setLinkMode(context: Context, mode: String) {
        context.getSharedPreferences(PREFS, Context.MODE_PRIVATE).edit().putString(KEY_LINK_MODE, mode).apply()
        VoiceTrace.event("link_mode", "mode" to mode)
    }

    /**
     * Holds the headset link for [holder] and calls onReady once it is live, at once when no headset with a mic is
     * connected (the phone's mic and speaker are used then).  [mode] overrides the link mode (MicProbeActivity).
     * Main thread only.
     */
    fun acquire(context: Context, holder: String, mode: String? = null, onReady: () -> Unit) {
        init(context)
        VoiceTrace.init(context)
        val am = audioManager ?: context.applicationContext.getSystemService(AudioManager::class.java).also { audioManager = it }
        handler.removeCallbacks(releaseNow)
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.S || am == null) { onReady(); return }
        val sco = am.availableCommunicationDevices.firstOrNull { it.type == AudioDeviceInfo.TYPE_BLUETOOTH_SCO }
        if (sco == null) {
            VoiceTrace.event("link_none", "holder" to holder)          // no headset with a mic: the phone's own
            onReady()
            return
        }
        holders.add(holder)
        if (holder == "listen") lastHeadsetListenAt = SystemClock.elapsedRealtime()

        val wanted = mode ?: linkMode(context)
        val listening = holder == "listen" || holder == "probe"
        if (listening && wanted != "call" && acquireVoiceRecognition(sco, holder, onReady)) return
        if (vrDevice != null) {
            if (vrUp && holders.any { it == "listen" || it == "probe" }) {
                VoiceTrace.event("link_live", "holder" to holder, "mode" to "vr")   // still listening: share it
                onReady()
                return
            }
            stopVoiceRecognition("call link wanted by $holder")
        }
        acquireCallLink(am, sco, holder, onReady)
    }

    // the headset's voice-recognition link; false when it can't be started (no profile, no device, refused)
    private fun acquireVoiceRecognition(sco: AudioDeviceInfo, holder: String, onReady: () -> Unit): Boolean {
        val hs = headset ?: return false.also { VoiceTrace.event("link_vr_unavailable", "why" to "no headset profile") }
        val device = try {
            hs.connectedDevices.firstOrNull { it.address.equals(sco.address, ignoreCase = true) }
                ?: hs.connectedDevices.firstOrNull()
        } catch (e: SecurityException) {
            null
        } ?: return false.also { VoiceTrace.event("link_vr_unavailable", "why" to "no connected headset") }

        if (vrDevice == device && vrUp) {
            Log.d(TAG, "$holder: voice-recognition link already live")
            VoiceTrace.event("link_live", "holder" to holder, "mode" to "vr")
            onReady()
            return true
        }
        waiting[holder] = onReady
        if (vrDevice == device) return true                     // coming up: onReady runs with the others
        if (owned) clearCallLink()                              // the call link would fight the voice-recognition one

        val askedAt = SystemClock.elapsedRealtime()
        val started = try { hs.startVoiceRecognition(device) } catch (e: SecurityException) { false }
        VoiceTrace.event("link_acquire", "holder" to holder, "mode" to "vr", "started" to started,
            "device" to sco.productName?.toString())
        if (!started) {
            Log.w(TAG, "startVoiceRecognition refused; using the call link")
            waiting.remove(holder)
            return false
        }
        vrDevice = device
        vrUp = false
        val fire = { reason: String ->
            vrPoll?.let { handler.removeCallbacks(it) }
            vrPoll = null
            vrUp = true
            Log.d(TAG, "Voice-recognition link ${sco.productName}: $reason, for ${waiting.keys}")
            VoiceTrace.event("link_up", "mode" to "vr", "reason" to reason, "ms" to SystemClock.elapsedRealtime() - askedAt)
            handler.postDelayed({
                val ready = waiting.values.toList()
                VoiceTrace.event("link_ready", "for" to waiting.keys.joinToString(), "settle_ms" to VR_SETTLE_MS)
                waiting.clear()
                ready.forEach { it() }
            }, VR_SETTLE_MS)
        }
        val poll = object : Runnable {
            override fun run() {
                val connected = try { headset?.isAudioConnected(device) == true } catch (_: SecurityException) { false }
                when {
                    connected -> fire("up")
                    SystemClock.elapsedRealtime() - askedAt >= LINK_TIMEOUT_MS -> fire("not confirmed after $LINK_TIMEOUT_MS ms")
                    else -> handler.postDelayed(this, POLL_MS)
                }
            }
        }
        vrPoll = poll
        handler.post(poll)
        return true
    }

    private fun acquireCallLink(am: AudioManager, sco: AudioDeviceInfo, holder: String, onReady: () -> Unit) {
        if (owned && linkUp && am.communicationDevice?.id == sco.id) {
            Log.d(TAG, "$holder: headset link already live (${sco.productName})")
            VoiceTrace.event("link_live", "holder" to holder, "mode" to "call")
            onReady()
            return
        }
        waiting[holder] = onReady
        if (pendingListener != null) return                     // already coming up: onReady runs with the others
        val cold = !owned                                       // not held a moment ago (released, or never)
        val askedAt = SystemClock.elapsedRealtime()
        VoiceTrace.event("link_acquire", "holder" to holder, "mode" to "call", "cold" to cold,
            "device" to sco.productName?.toString())

        val fire = { reason: String ->
            if (pendingListener != null || pendingTimeout != null) {
                cancelPending()
                linkUp = true
                Log.d(TAG, "Headset link ${sco.productName}: $reason, for ${waiting.keys}")
                VoiceTrace.event("link_up", "mode" to "call", "reason" to reason, "ms" to SystemClock.elapsedRealtime() - askedAt)
                val settle = if (cold) COLD_SETTLE_MS else SETTLE_MS
                handler.postDelayed({
                    val ready = waiting.values.toList()
                    VoiceTrace.event("link_ready", "for" to waiting.keys.joinToString(), "settle_ms" to settle)
                    waiting.clear()
                    ready.forEach { it() }
                }, settle)
            }
        }
        val listener = AudioManager.OnCommunicationDeviceChangedListener { device ->
            if (device?.id == sco.id) fire("up")
        }
        am.addOnCommunicationDeviceChangedListener({ handler.post(it) }, listener)
        pendingListener = listener
        if (!am.setCommunicationDevice(sco)) {
            Log.w(TAG, "setCommunicationDevice(${sco.productName}) refused; using the phone")
            VoiceTrace.event("link_refused")
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
    fun idle(): Boolean = holders.isEmpty() && !owned && vrDevice == null

    /** Lets go for [holder]; the link is handed back to the phone shortly after the last holder lets go. */
    fun release(holder: String) {
        holders.remove(holder)
        waiting.remove(holder)
        if (holders.isEmpty()) {
            cancelPending()
            handler.removeCallbacks(releaseNow)
            if (owned || vrDevice != null) handler.postDelayed(releaseNow, RELEASE_DELAY_MS)
        }
    }

    private fun clear() {
        if (holders.isNotEmpty()) return
        if (vrDevice != null) stopVoiceRecognition("released")
        if (owned) clearCallLink()
    }

    private fun clearCallLink() {
        if (owned && Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
            audioManager?.clearCommunicationDevice()
            Log.d(TAG, "Headset link released")
            VoiceTrace.event("link_released", "mode" to "call")
        }
        owned = false
        linkUp = false
    }

    // tells the headset that voice recognition is over (it closes the link): without it the helmet still thought it
    // was on, and took the next hold of its button as "stop" (2026-11-04)
    private fun stopVoiceRecognition(why: String) {
        val device = vrDevice ?: return
        vrPoll?.let { handler.removeCallbacks(it) }
        vrPoll = null
        val stopped = try { headset?.stopVoiceRecognition(device) == true } catch (_: SecurityException) { false }
        Log.d(TAG, "Voice-recognition link released ($why, stopped=$stopped)")
        VoiceTrace.event("link_released", "mode" to "vr", "why" to why, "stopped" to stopped)
        vrDevice = null
        vrUp = false
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
