package com.damirl.ray.audio

import android.annotation.SuppressLint
import android.app.Activity
import android.media.AudioFormat
import android.media.AudioManager
import android.media.AudioRecord
import android.media.MediaRecorder
import android.os.Bundle
import android.os.SystemClock
import android.util.Log
import android.view.Gravity
import android.widget.TextView
import com.damirl.ray.BuildConfig
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import kotlin.math.log10
import kotlin.math.sqrt

// A test of the headset's mic, from adb only (the activity needs android.permission.DUMP, which adb's shell has):
//   adb shell am start -n com.damirl.ray/.audio.MicProbeActivity --es mode vr --ei seconds 8 [--es source vr|comm|mic]
//                                       [--es audio_mode normal|comm]   (comm: MODE_IN_COMMUNICATION, as a VoIP call)
//   adb shell am start -n com.damirl.ray/.audio.MicProbeActivity --es link_mode auto|vr|call    (the drawer's mode)
// It opens the link the way given (vr: voice recognition, call: the call link), records what the recognizer would
// hear (VOICE_RECOGNITION source, 16 kHz mono) into files/mic_probe.wav, and writes 100 ms levels and the times to
// files/mic_probe.json, so tools/helmet_test.py can compare the two ways while you talk.  Debug builds only.
class MicProbeActivity : Activity() {

    companion object {
        private const val TAG = "RayMicProbe"
        private const val RATE = 16_000
        private const val FRAME = RATE / 10                     // 100 ms
    }

    private lateinit var label: TextView

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setShowWhenLocked(true)
        setTurnScreenOn(true)
        label = TextView(this).apply {
            gravity = Gravity.CENTER
            textSize = 22f
            setTextColor(0xFFF97316.toInt())
            setBackgroundColor(0xFF0B0D10.toInt())
            text = "Ray mic test"
        }
        setContentView(label)
        if (!BuildConfig.DEBUG) { finish(); return }
        VoiceTrace.init(this)

        intent.getStringExtra("link_mode")?.let { mode ->
            BluetoothMic.setLinkMode(this, mode)
            label.text = "Link mode: $mode"
            label.postDelayed({ finish() }, 800)
            return
        }
        val mode = intent.getStringExtra("mode") ?: "vr"
        val seconds = intent.getIntExtra("seconds", 8).coerceIn(1, 30)
        val source = when (intent.getStringExtra("source") ?: "vr") {
            "comm" -> MediaRecorder.AudioSource.VOICE_COMMUNICATION
            "mic" -> MediaRecorder.AudioSource.MIC
            else -> MediaRecorder.AudioSource.VOICE_RECOGNITION
        }
        val inCall = intent.getStringExtra("audio_mode") == "comm"
        label.text = "Mic test ($mode): keep talking…"
        val askedAt = SystemClock.elapsedRealtime()
        VoiceTrace.event("probe_start", "mode" to mode, "seconds" to seconds, "source" to source, "in_call" to inCall)
        val am = getSystemService(AudioManager::class.java)
        if (inCall) am?.mode = AudioManager.MODE_IN_COMMUNICATION
        BluetoothMic.acquire(this, "probe", mode) {
            Thread({
                record(mode, seconds, askedAt, source)
                if (inCall) runOnUiThread { am?.mode = AudioManager.MODE_NORMAL }
            }, "RayMicProbe").start()
        }
    }

    @SuppressLint("MissingPermission")                         // RECORD_AUDIO is granted at setup
    private fun record(mode: String, seconds: Int, askedAt: Long, source: Int) {
        val minBuf = AudioRecord.getMinBufferSize(RATE, AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT)
        val rec = AudioRecord(source, RATE, AudioFormat.CHANNEL_IN_MONO,
            AudioFormat.ENCODING_PCM_16BIT, maxOf(minBuf, FRAME * 4))
        val levels = JSONArray()
        val pcm = ShortArray(RATE * seconds)
        var got = 0
        var firstLoudMs = -1L
        val startedAt = SystemClock.elapsedRealtime()
        try {
            rec.startRecording()
            val frame = ShortArray(FRAME)
            while (got < pcm.size) {
                val n = rec.read(frame, 0, minOf(FRAME, pcm.size - got))
                if (n <= 0) break
                System.arraycopy(frame, 0, pcm, got, n)
                var sum = 0.0
                for (i in 0 until n) sum += frame[i].toDouble() * frame[i]
                val db = 20 * log10(maxOf(sqrt(sum / n), 1.0) / 32768.0)
                levels.put(Math.round(db * 10) / 10.0)
                if (firstLoudMs < 0 && db > -40) firstLoudMs = got * 1000L / RATE
                got += n
            }
            val device = rec.routedDevice
            VoiceTrace.event("probe_done", "mode" to mode, "device_type" to device?.type,
                "device" to device?.productName?.toString(), "link_ms" to startedAt - askedAt,
                "first_loud_ms" to firstLoudMs, "peak_db" to (0 until levels.length()).maxOfOrNull { levels.getDouble(it) })
            JSONObject().apply {
                put("mode", mode)
                put("source", source)
                put("audio_mode", (getSystemService(AudioManager::class.java))?.mode ?: -1)
                put("wall_start_ms", System.currentTimeMillis() - (SystemClock.elapsedRealtime() - startedAt))
                put("link_ms", startedAt - askedAt)
                put("device_type", device?.type ?: -1)
                put("device", device?.productName?.toString() ?: "")
                put("frame_ms", 100)
                put("levels_db", levels)
            }.let { File(filesDir, "mic_probe.json").writeText(it.toString()) }
            Wav.write(File(filesDir, "mic_probe.wav"), pcm, got, RATE)
        } catch (e: Exception) {
            Log.e(TAG, "Mic test failed", e)
            VoiceTrace.event("probe_failed", "error" to (e.message ?: e.javaClass.simpleName))
        } finally {
            try { rec.stop() } catch (_: Exception) {}
            rec.release()
            runOnUiThread {
                BluetoothMic.release("probe")
                label.text = "Mic test done"
                label.postDelayed({ finish() }, 500)
            }
        }
    }
}
