package com.damirl.ray.ui.components

import android.annotation.SuppressLint
import android.graphics.Color
import android.util.Log
import android.webkit.WebView
import android.webkit.WebViewClient
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.size
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.compose.ui.viewinterop.AndroidView
import org.json.JSONObject

/** What the drawer is doing, for Ray's panda. */
enum class RayMood { LISTENING, THINKING, TALKING, IDLE }

// Ray's animated red panda: the web app's own drawing code (serve/web/rayface.js, bundled into assets at build time)
// on a transparent WebView.  It loads only the app's assets (no network, no JavaScript bridge) and is driven from
// here: listening -> an attentive, curious pose; thinking -> paw on his chin (and his work props after tool calls);
// talking -> he moves with the reply; afterwards he stays in a calm idle.  Falls back to the still RayAvatar if the
// page can't load
@SuppressLint("SetJavaScriptEnabled")
@Composable
fun RayFaceView(
    mood: RayMood,
    speech: String,
    prompt: String,
    toolCalls: Int,
    lastTool: String?,
    sounding: com.damirl.ray.audio.VoiceOutput.Piece? = null,
    modifier: Modifier = Modifier,
    width: Dp = 84.dp,
    height: Dp = 73.dp
) {
    var ready by remember { mutableStateOf(false) }
    var failed by remember { mutableStateOf(false) }
    var view by remember { mutableStateOf<WebView?>(null) }

    if (failed) {
        RayAvatar(size = height, modifier = modifier)
        return
    }

    fun run(js: String) {
        if (ready) view?.evaluateJavascript("try { $js } catch (e) {}", null)
    }

    Box(modifier = modifier.size(width, height)) {
        AndroidView(
            modifier = Modifier.size(width, height),
            factory = { ctx ->
                WebView(ctx).apply {
                    setBackgroundColor(Color.TRANSPARENT)
                    isVerticalScrollBarEnabled = false
                    isHorizontalScrollBarEnabled = false
                    settings.javaScriptEnabled = true
                    settings.blockNetworkLoads = true
                    settings.allowFileAccess = false              // the app's assets load regardless
                    settings.allowContentAccess = false
                    webViewClient = object : WebViewClient() {
                        override fun onPageFinished(v: WebView?, url: String?) {
                            ready = true
                        }

                        override fun onReceivedError(
                            v: WebView?, request: android.webkit.WebResourceRequest?, error: android.webkit.WebResourceError?
                        ) {
                            if (request?.isForMainFrame == true) {
                                Log.w("RayFaceView", "Panda page failed: ${error?.description}")
                                failed = true
                            }
                        }
                    }
                    loadUrl("file:///android_asset/rayface/index.html")
                    view = this
                }
            }
        )
    }

    // a new question: what it is about picks his work props on a long think
    LaunchedEffect(ready, prompt) {
        if (prompt.isNotBlank()) run("RayFace.taskStart(${JSONObject.quote(prompt)})")
    }
    LaunchedEffect(ready, toolCalls) {
        if (toolCalls > 0) run("RayFace.taskTool(${JSONObject.quote(lastTool ?: "")}, {})")
    }
    LaunchedEffect(ready, mood) {
        when (mood) {
            RayMood.LISTENING -> run("RayFace.listen()")
            RayMood.THINKING -> run("RayFace.thinking()")
            RayMood.TALKING -> {}                         // his mouth follows `sounding`, below
            RayMood.IDLE -> run("RayFace.end()")
        }
    }

    // the voice's real start, length and end
    LaunchedEffect(ready, sounding) {
        val piece = sounding
        if (piece != null) run("RayFace.speakTimed(${JSONObject.quote(piece.text)}, ${piece.seconds})")
        else run("RayFace.chunkEnd()")
    }

    DisposableEffect(Unit) {
        onDispose {
            view?.destroy()
            view = null
        }
    }
}
