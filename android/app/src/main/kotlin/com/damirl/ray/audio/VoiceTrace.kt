package com.damirl.ray.audio

import android.app.KeyguardManager
import android.content.Context
import android.media.AudioDeviceInfo
import android.media.AudioManager
import android.os.Build
import android.os.PowerManager
import android.os.SystemClock
import android.util.Log
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
import java.io.File
import java.util.concurrent.Executors

// What happened when on the phone during a voice turn: one JSON line per event, in files/voice_trace.jsonl and in the
// log (tag RayTrace).  tools/helmet_test.py reads the file (adb exec-out run-as com.damirl.ray cat
// files/voice_trace.jsonl) and lines it up with the PC mic, the server and the system log.  The file outlives the log
// (its 2 MB buffer held 8 minutes on this phone) and an adb link that drops when Wi-Fi goes off.
// Each line: t = wall clock ms, up = elapsedRealtime ms, ev = the event, then its fields.
object VoiceTrace {

    private const val TAG = "RayTrace"
    const val FILE = "voice_trace.jsonl"
    private const val MAX_BYTES = 1_000_000L          // then the file moves to voice_trace.jsonl.1 and starts over

    @Volatile private var dir: File? = null
    private val writer = Executors.newSingleThreadExecutor { r -> Thread(r, "RayTrace").apply { isDaemon = true } }

    /** Where the file goes; any entry point may call it (the first call wins, the rest are no-ops). */
    fun init(context: Context) {
        if (dir == null) dir = context.applicationContext.filesDir
    }

    /** Records [event] with its fields: strings, numbers, booleans or null. */
    fun event(event: String, vararg fields: Pair<String, Any?>) {
        val line = line(System.currentTimeMillis(), SystemClock.elapsedRealtime(), event, fields.asList())
        Log.i(TAG, line)
        val d = dir ?: return
        writer.execute { append(d, line) }
    }

    /** The phone's state at a trigger: locked, screen on, a headset with a mic (call link) connected. */
    fun deviceState(context: Context): Array<Pair<String, Any?>> {
        val keyguard = context.getSystemService(KeyguardManager::class.java)
        val power = context.getSystemService(PowerManager::class.java)
        val audio = context.getSystemService(AudioManager::class.java)
        val sco = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
            audio?.availableCommunicationDevices?.firstOrNull { it.type == AudioDeviceInfo.TYPE_BLUETOOTH_SCO }
        } else null
        return arrayOf(
            "locked" to keyguard?.isDeviceLocked,
            "keyguard" to keyguard?.isKeyguardLocked,
            "screen_on" to power?.isInteractive,
            "headset" to sco?.productName?.toString()
        )
    }

    internal fun line(wallMs: Long, upMs: Long, event: String, fields: List<Pair<String, Any?>>): String =
        buildJsonObject {
            put("t", wallMs)
            put("up", upMs)
            put("ev", event)
            for ((key, value) in fields) {
                when (value) {
                    null -> put(key, JsonNull)
                    is Boolean -> put(key, value)
                    is Number -> put(key, value)
                    else -> put(key, value.toString())
                }
            }
        }.toString()

    internal fun append(dir: File, line: String, maxBytes: Long = MAX_BYTES) {
        try {
            val file = File(dir, FILE)
            if (file.length() > maxBytes) {
                val old = File(dir, "$FILE.1")
                old.delete()
                file.renameTo(old)
            }
            file.appendText(line + "\n")
        } catch (e: Exception) {
            Log.w(TAG, "Couldn't write the trace", e)
        }
    }
}
