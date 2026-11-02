package com.damirl.ray.assistant

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
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
import org.vosk.android.RecognitionListener
import org.vosk.android.SpeechService
import java.io.File

// "Ok Ray": listens on the phone for the wake phrase with Vosk, offline (nothing leaves the phone), and opens the voice
// drawer when it hears it.  A foreground service of type microphone with a quiet notification, which Android needs for
// a mic in the background.  The recognizer only knows the phrases in WakeWord.PHRASES (and "[unk]" for anything else).
// It lets go of the mic while the drawer, a recognizer or Ray's voice is busy (WakeWord.held)
class HotwordListenerService : Service() {

    companion object {
        private const val TAG = "RayHotword"
        private const val NOTIFICATION_ID = 2002
        private const val CHANNEL_ID = "ray_hotword_channel"
        private const val SAMPLE_RATE = 16000f
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
    private var speech: SpeechService? = null
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
        if (speech != null) return
        try {
            val grammar = JSONArray(WakeWord.PHRASES + "[unk]").toString()
            val rec = Recognizer(m, SAMPLE_RATE, grammar)
            speech = SpeechService(rec, SAMPLE_RATE).also { it.startListening(listener) }
            Log.d(TAG, "Listening for Ok Ray")
        } catch (e: Exception) {
            Log.e(TAG, "Could not open the mic for Ok Ray", e)
            speech = null
        }
    }

    private fun stopListening() {
        speech?.let {
            it.stop()
            it.shutdown()
            Log.d(TAG, "Ok Ray paused (mic or speaker busy: ${WakeWord.held.value})")
        }
        speech = null
    }

    private val listener = object : RecognitionListener {
        override fun onPartialResult(hypothesis: String?) = check(hypothesis, "partial")
        override fun onResult(hypothesis: String?) = check(hypothesis, "text")
        override fun onFinalResult(hypothesis: String?) = check(hypothesis, "text")
        override fun onError(exception: Exception?) {
            Log.w(TAG, "Ok Ray listener error: ${exception?.message}")
            stopListening()
            scope.launch { delay(2000); if (WakeWord.held.value.isEmpty()) listen() }
        }
        override fun onTimeout() {}
    }

    private fun check(hypothesis: String?, key: String) {
        val text = runCatching { JSONObject(hypothesis ?: "{}").optString(key) }.getOrDefault("")
        if (!WakeWord.matches(text)) return
        val now = System.currentTimeMillis()
        if (now - lastWake < 3000) return
        lastWake = now
        Log.d(TAG, "Heard \"$text\": opening the drawer")
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
            .setContentText("On the phone only; switch it off in About")
            .setContentIntent(pendingIntent)
            .setPriority(NotificationCompat.PRIORITY_MIN)
            .setOngoing(true)
            .build()
    }

    override fun onBind(intent: Intent?): IBinder? = null
}
