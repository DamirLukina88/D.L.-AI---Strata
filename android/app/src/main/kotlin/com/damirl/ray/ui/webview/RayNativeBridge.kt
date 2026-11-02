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
import com.damirl.ray.audio.BluetoothMic
import com.damirl.ray.audio.VoiceOutput
import com.damirl.ray.audio.SpeechCleaner
import com.damirl.ray.audio.SpeechRecognitionManager
import com.damirl.ray.BuildConfig
import com.damirl.ray.network.StrataOrigins
import com.damirl.ray.tools.PhoneTools
import org.json.JSONObject

class RayNativeBridge(
    private val context: Context,
    private val webViewProvider: () -> WebView? = { null },
    private val audioSpeaker: ((String) -> Unit)? = null
) {

    companion object {
        private const val TAG = "RayNativeBridge"
    }

    private val phoneTools = PhoneTools(context)
    private var speechManager: SpeechRecognitionManager? = null

    // The page the WebView shows now (set by RayWebView on every navigation).  Every call below answers only the
    // Strata server's own pages: any other page the WebView might show (a link, a redirect) gets nothing, above all
    // not the API key or the phone tools
    @Volatile
    var pageUrl: String? = null

    private fun trusted(call: String): Boolean {
        if (StrataOrigins.isTrusted(pageUrl)) return true
        Log.w(TAG, "RayAndroid.$call refused: the page is not the Strata server")
        return false
    }

    init {
        // the drawer and the native mic stop the web app's voice through this before they listen
        VoiceOutput.stopWebSpeech = {
            webViewProvider()?.let { wv ->
                wv.post { wv.evaluateJavascript("if (typeof TTSController !== 'undefined' && TTSController.speaking) TTSController.stop();", null) }
            }
        }
        try {
            speechManager = SpeechRecognitionManager(context)
        } catch (e: Exception) {
            Log.w(TAG, "SpeechRecognitionManager init deferred or unavailable", e)
        }
    }

    @JavascriptInterface
    fun speak(text: String) {
        if (!trusted("speak")) return
        val cleaned = SpeechCleaner.clean(text)
        if (cleaned.isBlank()) return
        if (BuildConfig.DEBUG) Log.d(TAG, "speak: '$cleaned'")
        if (audioSpeaker != null) {
            audioSpeaker.invoke(cleaned)
        } else {
            AudioPlaybackService.startSpeaking(context, cleaned)
        }
    }

    // The web app's reply (the server voice through Web Audio) goes over a headset's call link too, after you spoke
    // through the headset (BluetoothMic): TTSController holds it while it reads aloud and lets go when it stops
    @JavascriptInterface
    fun holdHeadsetForSpeech(on: Boolean) {
        if (!trusted("holdHeadsetForSpeech")) return
        android.os.Handler(android.os.Looper.getMainLooper()).post {
            if (!on) {
                BluetoothMic.release("web-reply")
            } else if (BluetoothMic.inHeadsetConversation()) {
                Log.d(TAG, "Web reply over the headset's call link")
                BluetoothMic.acquire(context, "web-reply") {}
            }
        }
    }

    // Polled by the web app's TTSController so it speaks the next chunk only after this one finishes
    @JavascriptInterface
    fun isSpeaking(): Boolean = trusted("isSpeaking") && AudioPlaybackService.isSpeakingState.value

    @JavascriptInterface
    fun stopSpeaking() {
        if (!trusted("stopSpeaking")) return
        Log.d(TAG, "stopSpeaking")
        AudioPlaybackService.stopSpeaking(context)
    }

    @JavascriptInterface
    fun startListening() {
        if (!trusted("startListening")) return
        Log.d(TAG, "startListening called from web")
        hapticFeedback("subtle")
        android.os.Handler(android.os.Looper.getMainLooper()).post {
            try {
                speechManager?.startListening(
                    onFinalResult = { transcribed ->
                        if (BuildConfig.DEBUG) Log.d(TAG, "Speech final: '$transcribed'")
                        deliverSpeechResultToWeb(transcribed, isFinal = true)
                    },
                    onError = { err ->
                        Log.w(TAG, "Speech error: $err")
                        // the page's mic button would otherwise stay on "recording" with the keyboard hidden
                        webViewProvider()?.let { wv ->
                            val js = "if (typeof window.onRayAndroidSpeechError === 'function') " +
                                "window.onRayAndroidSpeechError(${JSONObject.quote(err)});"
                            wv.post { wv.evaluateJavascript(js, null) }
                        }
                    }
                )
            } catch (e: Exception) {
                Log.e(TAG, "Error starting speech listening on main thread", e)
            }
        }
    }

    @JavascriptInterface
    fun stopListening() {
        if (!trusted("stopListening")) return
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
        if (!trusted("hapticFeedback")) return
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

    // A workspace file's single-use download link (absolute URL) and its name: into Downloads, see Downloads
    @JavascriptInterface
    fun downloadFile(url: String, fileName: String): Boolean = trusted("downloadFile") && Downloads.enqueue(context, url, fileName)

    // "Ok Ray" on or off (the switch in the web app's About card); see WakeWord
    @JavascriptInterface
    fun isWakeWordOn(): Boolean = trusted("isWakeWordOn") && com.damirl.ray.assistant.WakeWord.isOn(context)

    @JavascriptInterface
    fun setWakeWord(on: Boolean) {
        if (!trusted("setWakeWord")) return
        android.os.Handler(android.os.Looper.getMainLooper()).post { com.damirl.ray.assistant.WakeWord.set(context, on) }
    }

    // The "Android settings" button in the web app's About tab: the setup screen with Ray's permissions
    @JavascriptInterface
    fun openSetup() {
        if (!trusted("openSetup")) return
        Log.d(TAG, "openSetup")
        context.startActivity(android.content.Intent(context, com.damirl.ray.OnboardingActivity::class.java).apply {
            if (context !is android.app.Activity) addFlags(android.content.Intent.FLAG_ACTIVITY_NEW_TASK)
        })
    }

    @JavascriptInterface
    fun getApiKey(): String {
        if (!trusted("getApiKey")) return ""
        return try {
            com.damirl.ray.BuildConfig.STRATA_API_KEY
        } catch (_: Throwable) {
            ""
        }
    }

    @JavascriptInterface
    fun executeTool(name: String, argsJson: String = "{}", callId: String = ""): String {
        if (!trusted("executeTool")) {
            return JSONObject().put("tool", name).put("callId", callId)
                .put("result", "Error: refused (not the Strata server)").toString()
        }
        // arguments can be private (app names, alarm labels): logged in debug builds only
        if (BuildConfig.DEBUG) Log.d(TAG, "executeTool: name=$name args=$argsJson callId=$callId") else Log.d(TAG, "executeTool: $name")
        val args = try {
            JSONObject(if (argsJson.isBlank()) "{}" else argsJson)
        } catch (_: Exception) {
            JSONObject()
        }

        val result = phoneTools.execute(name, args)

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
