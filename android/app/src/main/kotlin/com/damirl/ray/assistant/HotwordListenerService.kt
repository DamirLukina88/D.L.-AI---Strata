package com.damirl.ray.assistant

import android.annotation.SuppressLint
import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.media.AudioFormat
import android.media.AudioRecord
import android.media.MediaRecorder
import android.os.Build
import android.os.Bundle
import android.os.IBinder
import android.util.Log
import androidx.core.app.NotificationCompat
import androidx.core.app.ServiceCompat
import com.damirl.ray.MainActivity
import com.damirl.ray.R
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import org.json.JSONArray
import org.json.JSONObject
import org.vosk.Model
import org.vosk.Recognizer
import java.io.File

// "Ok Ray": listens on the phone for the wake phrase with Vosk, offline (nothing leaves the phone), and opens the voice
// drawer when it hears it.  A foreground service of type microphone with a quiet notification, which Android needs for
// a mic in the background.  The recognizer only knows WakeWord.GRAMMAR (the phrases, their look-alikes and "[unk]") and
// only runs on sound that SpeechGate lets through; a final result must pass WakeWord.accepts.  It lets go of the mic
// while the drawer, a recognizer or Ray's voice is busy (WakeWord.held)
class HotwordListenerService : Service() {

    companion object {
        private const val TAG = "RayHotword"
        private const val NOTIFICATION_ID = 2002
        private const val CHANNEL_ID = "ray_hotword_channel"
        private const val SAMPLE_RATE = 16000f
        private const val PRE_ROLL_FRAMES = 20                     // 400 ms kept from before the gate opens
        private const val GATE_LOG_FRAMES = 3000                   // one minute
        private const val CLIP_SECONDS = 4
        const val ACTION_START = "com.damirl.ray.action.START_HOTWORD"
        const val ACTION_STOP = "com.damirl.ray.action.STOP_HOTWORD"

        @Volatile
        var running = false
            private set

        fun start(context: Context) {
            val intent = Intent(context, HotwordListenerService::class.java).apply { action = ACTION_START }
            try {
                context.startForegroundService(intent)
            } catch (e: Exception) {
                // Android refuses a mic service started from the background; it starts the next time the app opens
                Log.w(TAG, "Could not start the Ok Ray listener now: ${e.message}")
            }
        }

        fun stop(context: Context) {
            context.stopService(Intent(context, HotwordListenerService::class.java))
        }
    }

    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main)
    private var model: Model? = null
    private var micThread: Thread? = null
    @Volatile private var micOn = false
    private var watchJob: Job? = null
    private var lastWake = 0L

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        if (intent?.action == ACTION_STOP) {
            stopSelf()
            return START_NOT_STICKY
        }
        createNotificationChannel()
        ServiceCompat.startForeground(
            this, NOTIFICATION_ID, createNotification(),
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) ServiceInfo.FOREGROUND_SERVICE_TYPE_MICROPHONE else 0
        )
        if (!running) {
            running = true
            scope.launch { loadAndWatch() }
        }
        return START_STICKY
    }

    private suspend fun loadAndWatch() {
        val m = try {
            withContext(Dispatchers.IO) { Model(unpackModel().absolutePath) }
        } catch (e: Exception) {
            Log.e(TAG, "Vosk model failed to load", e)
            stopSelf()
            return
        }
        model = m
        Log.d(TAG, "Ok Ray listener ready")
        // listen while nothing else uses the mic or the speaker; let go while anything does
        watchJob = scope.launch {
            WakeWord.held.collect { holders ->
                if (holders.isEmpty()) {
                    delay(600)                                     // let the other user of the mic finish letting go
                    if (WakeWord.held.value.isEmpty()) listen()
                } else {
                    stopListening()
                }
            }
        }
    }

    private fun listen() {
        val m = model ?: return
        if (micThread != null) return
        micOn = true
        micThread = Thread({ micLoop(m) }, "RayWakeMic").also { it.start() }
        Log.d(TAG, "Listening for Ok Ray")
    }

    private fun stopListening() {
        val t = micThread ?: return
        micOn = false
        t.join(1500)
        micThread = null
        Log.d(TAG, "Ok Ray paused (mic or speaker busy: ${WakeWord.held.value})")
    }

    // Reads the mic in 200 ms blocks and gives Vosk only what the gate lets through, with the moment before the gate
    // opened so the start of "ok" isn't lost.  Only final results count: partial ones are guesses that often change
    @SuppressLint("MissingPermission")                             // the service only runs after the app was given it
    private fun micLoop(m: Model) {
        val rate = SAMPLE_RATE.toInt()
        val frame = rate / 50                                      // 20 ms
        val block = ShortArray(frame * 10)
        val preRoll = Array(PRE_ROLL_FRAMES) { ShortArray(frame) }
        var preRollAt = 0
        val gate = SpeechGate()
        val clip = if (WakeWord.savesClips(this)) ClipRing(rate * CLIP_SECONDS) else null
        var openFrames = 0
        var allFrames = 0
        var rec: Recognizer? = null
        var mic: AudioRecord? = null
        try {
            rec = Recognizer(m, SAMPLE_RATE, JSONArray(WakeWord.GRAMMAR).toString()).apply { setWords(true) }
            val size = maxOf(
                AudioRecord.getMinBufferSize(rate, AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT),
                block.size * 2 * 2
            )
            mic = AudioRecord(
                MediaRecorder.AudioSource.VOICE_RECOGNITION, rate, AudioFormat.CHANNEL_IN_MONO,
                AudioFormat.ENCODING_PCM_16BIT, size
            )
            check(mic.state == AudioRecord.STATE_INITIALIZED) { "the mic is in use" }
            mic.startRecording()
            while (micOn) {
                val got = mic.read(block, 0, block.size)
                check(got >= 0) { "mic read failed: $got" }
                clip?.add(block, got)
                var at = 0
                while (at + frame <= got) {
                    val wasOpen = gate.open
                    val open = gate.push(SpeechGate.levelDb(block, at, frame))
                    if (open && !wasOpen) {
                        for (i in preRoll.indices) rec.acceptWaveForm(preRoll[(preRollAt + i) % PRE_ROLL_FRAMES], frame)
                    }
                    if (open) {
                        val tmp = block.copyOfRange(at, at + frame)
                        if (rec.acceptWaveForm(tmp, frame)) judge(rec.result, clip)
                        openFrames++
                    } else {
                        block.copyInto(preRoll[preRollAt], 0, at, at + frame)
                        preRollAt = (preRollAt + 1) % PRE_ROLL_FRAMES
                        if (wasOpen) {
                            judge(rec.finalResult, clip)
                            rec.reset()
                        }
                    }
                    allFrames++
                    at += frame
                }
                if (allFrames >= GATE_LOG_FRAMES) {
                    Log.d(TAG, "Vosk ran ${openFrames * 100 / allFrames}% of the last minute (room ${gate.floorDb.toInt()} dB)")
                    openFrames = 0
                    allFrames = 0
                }
            }
        } catch (e: Exception) {
            Log.w(TAG, "Ok Ray listener error: ${e.message}")
            scope.launch {
                micThread = null
                delay(2000)
                if (WakeWord.held.value.isEmpty()) listen()
            }
        } finally {
            runCatching { mic?.stop() }
            mic?.release()
            rec?.close()
        }
    }

    private fun judge(json: String, clip: ClipRing?) {
        val result = runCatching { JSONObject(json) }.getOrNull() ?: return
        val text = result.optString("text")
        if (!WakeWord.matches(text)) return
        val list = result.optJSONArray("result")
        val words = (0 until (list?.length() ?: 0)).map { i ->
            val w = list!!.getJSONObject(i)
            WakeWord.Heard(w.optString("word"), w.optDouble("start"), w.optDouble("end"))
        }
        val summary = "$text in %.2f s".format((words.lastOrNull()?.end ?: 0.0) - (words.firstOrNull()?.start ?: 0.0))
        if (!WakeWord.accepts(text, words)) {
            Log.d(TAG, "Wrong length, ignored: $summary")
            return
        }
        val sound = clip?.snapshot()
        scope.launch { heard(summary, text, sound) }
    }

    private fun heard(summary: String, text: String, sound: ShortArray?) {
        val now = System.currentTimeMillis()
        if (now - lastWake < 3000) return
        lastWake = now
        Log.d(TAG, "Heard Ok Ray ($summary): opening the drawer")
        if (sound != null) {
            scope.launch(Dispatchers.IO) { WakeClips.save(this@HotwordListenerService, sound, SAMPLE_RATE.toInt(), text) }
        }
        stopListening()
        openDrawer()
    }

    // the same way as the helmet button: the system assistant overlay, or the drawer activity if that isn't connected
    // (starting it from here is allowed because Ray's VoiceInteractionService is bound by the system)
    private fun openDrawer() {
        val args = Bundle().apply { putString("source", "wake_word") }
        if (!RayVoiceInteractionService.showSession(args)) {
            startActivity(Intent(this, RayVoiceActivity::class.java).apply {
                action = Intent.ACTION_ASSIST
                flags = Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_SINGLE_TOP
            })
        }
    }

    // Vosk reads its model from files: copy it out of the assets once per model version
    private fun unpackModel(): File {
        val version = assets.open("vosk-model/VERSION").bufferedReader().use { it.readText().trim() }
        val dir = File(filesDir, "vosk/$version")
        val done = File(dir, ".unpacked")
        if (done.exists()) return dir
        File(filesDir, "vosk").deleteRecursively()
        copyAssets("vosk-model", dir)
        done.writeText(version)
        Log.d(TAG, "Vosk model unpacked to $dir")
        return dir
    }

    private fun copyAssets(path: String, to: File) {
        val children = assets.list(path).orEmpty()
        if (children.isEmpty()) {
            to.parentFile?.mkdirs()
            assets.open(path).use { input -> to.outputStream().use { input.copyTo(it) } }
            return
        }
        to.mkdirs()
        for (child in children) copyAssets("$path/$child", File(to, child))
    }

    override fun onDestroy() {
        running = false
        watchJob?.cancel()
        stopListening()
        model?.close()
        model = null
        scope.cancel()
        Log.d(TAG, "Ok Ray listener stopped")
        super.onDestroy()
    }

    private fun createNotificationChannel() {
        val channel = NotificationChannel(CHANNEL_ID, "Ok Ray", NotificationManager.IMPORTANCE_MIN).apply {
            description = "Shown while Ray listens for \"Ok Ray\" on the phone"
            setShowBadge(false)
        }
        getSystemService(NotificationManager::class.java).createNotificationChannel(channel)
    }

    private fun createNotification(): Notification {
        val pendingIntent = PendingIntent.getActivity(
            this, 0, Intent(this, MainActivity::class.java),
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
        )
        return NotificationCompat.Builder(this, CHANNEL_ID)
            .setSmallIcon(R.drawable.ic_tile_paw)
            .setContentTitle("Listening for “Ok Ray”")
            .setContentText(
                if (WakeWord.savesClips(this)) "On the phone only; test mode saves each wake as a clip"
                else "On the phone only; switch it off in About"
            )
            .setContentIntent(pendingIntent)
            .setPriority(NotificationCompat.PRIORITY_MIN)
            .setOngoing(true)
            .build()
    }

    override fun onBind(intent: Intent?): IBinder? = null
}
