package com.damirl.ray.ui.webview

import android.content.Context
import android.os.Build
import android.os.VibrationEffect
import android.os.Vibrator
import android.os.VibratorManager
import android.util.Log
import android.webkit.JavascriptInterface
import android.webkit.WebView
import com.damirl.ray.audio.AudioPlaybackService
import com.damirl.ray.audio.SpeechCleaner
import com.damirl.ray.audio.SpeechRecognitionManager
import com.damirl.ray.tools.CameraVisionManager
import com.damirl.ray.tools.DeviceToolsManager
import com.damirl.ray.tools.RayAccessibilityService
import com.damirl.ray.tools.RayMediaController
import com.damirl.ray.tools.RayNotificationListenerService
import org.json.JSONObject

class RayNativeBridge(
    private val context: Context,
    private val webViewProvider: () -> WebView? = { null },
    private val audioSpeaker: ((String) -> Unit)? = null
) {

    companion object {
        private const val TAG = "RayNativeBridge"
    }

    private val deviceTools = DeviceToolsManager(context)
    private val mediaController = RayMediaController(context)
    private val cameraVision = CameraVisionManager(context)
    private var speechManager: SpeechRecognitionManager? = null

    init {
        try {
            speechManager = SpeechRecognitionManager(context)
        } catch (e: Exception) {
            Log.w(TAG, "SpeechRecognitionManager init deferred or unavailable", e)
        }
    }

    @JavascriptInterface
    fun speak(text: String) {
        val cleaned = SpeechCleaner.clean(text)
        if (cleaned.isBlank()) return
        Log.d(TAG, "speak: '$cleaned'")
        if (audioSpeaker != null) {
            audioSpeaker.invoke(cleaned)
        } else {
            AudioPlaybackService.startSpeaking(context, cleaned)
        }
    }

    @JavascriptInterface
    fun stopSpeaking() {
        Log.d(TAG, "stopSpeaking")
        AudioPlaybackService.stopSpeaking(context)
    }

    @JavascriptInterface
    fun startListening() {
        Log.d(TAG, "startListening called from web")
        hapticFeedback("subtle")
        android.os.Handler(android.os.Looper.getMainLooper()).post {
            try {
                speechManager?.startListening(
                    onFinalResult = { transcribed ->
                        Log.d(TAG, "Speech final: '$transcribed'")
                        deliverSpeechResultToWeb(transcribed, isFinal = true)
                    },
                    onError = { err ->
                        Log.w(TAG, "Speech error: $err")
                    }
                )
            } catch (e: Exception) {
                Log.e(TAG, "Error starting speech listening on main thread", e)
            }
        }
    }

    @JavascriptInterface
    fun stopListening() {
        Log.d(TAG, "stopListening called from web")
        android.os.Handler(android.os.Looper.getMainLooper()).post {
            try {
                speechManager?.stopListening()
            } catch (e: Exception) {
                Log.e(TAG, "Error stopping speech listening on main thread", e)
            }
        }
    }

    @JavascriptInterface
    fun hapticFeedback(intensity: String = "subtle") {
        try {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
                val vibratorManager = context.getSystemService(Context.VIBRATOR_MANAGER_SERVICE) as? VibratorManager
                val vibrator = vibratorManager?.defaultVibrator
                val effect = when (intensity.lowercase()) {
                    "heavy" -> VibrationEffect.createPredefined(VibrationEffect.EFFECT_HEAVY_CLICK)
                    "double" -> VibrationEffect.createPredefined(VibrationEffect.EFFECT_DOUBLE_CLICK)
                    "tick" -> VibrationEffect.createPredefined(VibrationEffect.EFFECT_TICK)
                    else -> VibrationEffect.createPredefined(VibrationEffect.EFFECT_CLICK)
                }
                vibrator?.vibrate(effect)
            } else {
                @Suppress("DEPRECATION")
                val vibrator = context.getSystemService(Context.VIBRATOR_SERVICE) as? Vibrator
                if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
                    val effect = VibrationEffect.createPredefined(VibrationEffect.EFFECT_CLICK)
                    vibrator?.vibrate(effect)
                } else {
                    @Suppress("DEPRECATION")
                    vibrator?.vibrate(20)
                }
            }
        } catch (e: Exception) {
            Log.w(TAG, "Haptic feedback unavailable: ${e.message}")
        }
    }

    @JavascriptInterface
    fun getApiKey(): String {
        return try {
            com.damirl.ray.BuildConfig.STRATA_API_KEY
        } catch (_: Throwable) {
            ""
        }
    }

    @JavascriptInterface
    fun executeTool(name: String, argsJson: String = "{}", callId: String = ""): String {
        Log.d(TAG, "executeTool: name=$name args=$argsJson callId=$callId")
        val args = try {
            JSONObject(if (argsJson.isBlank()) "{}" else argsJson)
        } catch (_: Exception) {
            JSONObject()
        }

        val result = when (name) {
            "phone_toggle_torch" -> {
                val enabled = args.optBoolean("enabled", false)
                deviceTools.toggleTorch(enabled)
            }
            "phone_get_battery" -> {
                deviceTools.getBatteryInfo()
            }
            "phone_set_volume" -> {
                val stream = args.optString("stream", "media")
                val level = args.optInt("level", 50)
                deviceTools.setVolume(stream, level)
            }
            "phone_set_alarm" -> {
                val hour = args.optInt("hour", 8)
                val minute = args.optInt("minute", 0)
                val label = args.optString("label", "Alarm from Ray")
                deviceTools.setAlarm(hour, minute, label)
            }
            "phone_launch_app" -> {
                val pkg = args.optString("package_or_name", "")
                deviceTools.launchApp(pkg)
            }
            "phone_get_recent_notifications" -> {
                val count = args.optInt("count", 5)
                RayNotificationListenerService.getRecentNotifications(count)
            }
            "phone_get_2fa_code" -> {
                RayNotificationListenerService.getLatest2faCode()
            }
            "phone_get_now_playing" -> {
                mediaController.getNowPlaying()
            }
            "phone_control_media" -> {
                val action = args.optString("action", "play_pause")
                mediaController.controlMedia(action)
            }
            "phone_camera_snap" -> {
                val prompt = args.optString("prompt", "")
                cameraVision.snapPhoto(prompt)
            }
            "phone_get_screen" -> {
                RayAccessibilityService.getScreenContent()
            }
            else -> {
                "Error: Unknown tool '$name'."
            }
        }

        return try {
            val json = JSONObject().apply {
                put("tool", name)
                put("callId", callId)
                put("result", result)
            }
            json.toString()
        } catch (_: Exception) {
            fallbackJson(name, callId, result)
        }
    }

    private fun fallbackJson(name: String, callId: String, result: String): String {
        val escapedTool = name.replace("\"", "\\\"")
        val escapedCallId = callId.replace("\"", "\\\"")
        val escapedResult = result.replace("\\", "\\\\").replace("\"", "\\\"").replace("\n", "\\n").replace("\r", "\\r")
        return "{\"tool\":\"$escapedTool\",\"callId\":\"$escapedCallId\",\"result\":\"$escapedResult\"}"
    }

    @JavascriptInterface
    fun hasOpenDrawer(): Boolean {
        // Will be queried or evaluated on WebView
        return false
    }

    @JavascriptInterface
    fun closeOpenDrawer(): Boolean {
        return false
    }

    private fun deliverSpeechResultToWeb(text: String, isFinal: Boolean) {
        val webView = webViewProvider() ?: return
        val escaped = JSONObject.quote(text)
        val js = """
            (function() {
                if (typeof window.onRayAndroidSpeechResult === 'function') {
                    window.onRayAndroidSpeechResult($escaped, $isFinal);
                } else {
                    const input = document.getElementById('code-mobile-input');
                    if (input) {
                        input.value = $escaped;
                        input.dispatchEvent(new Event('input', { bubbles: true }));
                        ${if (isFinal) "const sendBtn = document.getElementById('code-mobile-send'); if (sendBtn) sendBtn.click();" else ""}
                    }
                }
            })();
        """.trimIndent()

        webView.post {
            webView.evaluateJavascript(js, null)
        }
    }
}
