package com.damirl.ray.tools

import android.content.Context
import android.os.SystemClock
import android.util.Log
import com.damirl.ray.audio.VoiceTrace
import com.damirl.ray.network.NetworkClient
import com.damirl.ray.network.NetworkRoute
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.CoroutineDispatcher
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.NonCancellable
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.withContext
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONException
import org.json.JSONObject
import java.io.IOException
import java.util.concurrent.TimeUnit

/** One phone tool Ray called, waiting on the server. */
data class PhoneToolCall(val id: String, val tool: String, val args: JSONObject)

/** The answer to GET /v1/ray/phone/pending: the waiting call, or null when there is none (or the answer is unreadable). */
fun parsePendingCall(body: String, context: Context? = null): PhoneToolCall? = try {
    val root = JSONObject(body)
    if (context != null) {
        root.optJSONObject("clipboard")?.let { clip ->
            val text = clip.optString("text", "")
            val hash = clip.optString("hash", "")
            if (text.isNotEmpty()) {
                PhoneClipboardManager.applyRemoteClipboardIfChanged(context, text, hash)
            }
        }
    }
    root.optJSONObject("pending")?.let { call ->
        val id = call.optString("id")
        val tool = call.optString("tool")
        if (id.isEmpty() || tool.isEmpty()) null
        else PhoneToolCall(id, tool, call.optJSONObject("args") ?: JSONObject())
    }
} catch (_: JSONException) {
    null
}

/** How the relay reaches the server; both calls block and throw IOException when they fail. */
interface PhoneRelayLink {
    fun pending(): PhoneToolCall?
    fun post(id: String, result: String)
}

// Over the app's own client, the route the drawer probed.  The /v1 paths on purpose: Cloudflare Access answers
// /api/phone/* itself (HTTP 401) for anything without its login cookie, which only the web page has
class HttpPhoneRelayLink(
    private val network: NetworkClient,
    private val context: Context? = null
) : PhoneRelayLink {

    companion object {
        const val PENDING_PATH = "/v1/ray/phone/pending"
        const val RESULT_PATH = "/v1/ray/phone/result"
        private const val REPROBE_INTERVAL_MS = 10_000L
        private val JSON_TYPE = "application/json; charset=utf-8".toMediaType()
    }

    // a stalled mobile link mustn't hold the relay: the next poll goes out instead (shares the app's connections)
    private val client = network.okHttpClient.newBuilder().callTimeout(6, TimeUnit.SECONDS).build()
    @Volatile private var lastProbeMs = 0L

    override fun pending(): PhoneToolCall? {
        if (network.currentRoute.value is NetworkRoute.Offline) {
            probeIfNeeded()
        }
        return try {
            val request = network.newAuthenticatedRequestBuilder(PENDING_PATH).get().build()
            client.newCall(request).execute().use { r ->
                if (!r.isSuccessful) throw IOException("HTTP ${r.code}")
                parsePendingCall(r.body?.string().orEmpty(), context)
            }
        } catch (e: IOException) {
            probeIfNeeded()
            throw e
        }
    }

    private fun probeIfNeeded() {
        val now = SystemClock.elapsedRealtime()
        if (now - lastProbeMs >= REPROBE_INTERVAL_MS) {
            lastProbeMs = now
            runBlocking { network.probeAndSelectRoute() }
        }
    }

    override fun post(id: String, result: String) {
        val body = JSONObject().put("id", id).put("result", result).toString().toRequestBody(JSON_TYPE)
        val request = network.newAuthenticatedRequestBuilder(RESULT_PATH).post(body).build()
        client.newCall(request).execute().use { r ->
            if (!r.isSuccessful) throw IOException("HTTP ${r.code}")
        }
    }
}

// Ray's phone tools while the app is in the background or only the voice drawer runs.  The web app's page relays them
// too (startPhoneCompanionBridge in app.js), but with the phone locked in a pocket that page is paused or not there at
// all, and away from home there is no adb.  Each poll is also the heartbeat tools/phone_mcp.py checks before it sends a
// call.  One call at a time, like the page.  [execute] is PhoneTools.execute, so the private tools stay refused on a
// locked phone.  If the page polls as well, the server hands each call to one of them
class PhoneToolRelay(
    private val link: PhoneRelayLink,
    private val execute: (String, JSONObject) -> String,
    private val pollMs: Long = POLL_MS,
    private val io: CoroutineDispatcher = Dispatchers.IO
) {

    companion object {
        private const val TAG = "RayToolRelay"
        private const val POLL_MS = 1_000L
        private const val BG_POLL_MS = 2_000L
        private const val POST_TRIES = 3
        private const val POST_RETRY_MS = 500L

        private val bgScope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
        @Volatile private var bgJob: Job? = null

        /**
         * Ensures a persistent background relay is polling in this process so non-private phone tools (torch, battery,
         * volume, music) work when the phone is locked and Ray is in the background.
         */
        @Synchronized
        fun ensureBackgroundRelay(context: Context) {
            val appCtx = context.applicationContext
            PhoneClipboardManager.ensureListener(appCtx)
            if (bgJob?.isActive == true) return
            val relay = PhoneToolRelay(
                HttpPhoneRelayLink(NetworkClient.shared, appCtx),
                PhoneTools(appCtx)::execute,
                pollMs = BG_POLL_MS
            )
            bgJob = bgScope.launch {
                Log.d(TAG, "Background phone tool relay started")
                relay.run()
            }
        }
    }

    /** Polls until cancelled.  A call already taken from the server still runs and is answered. */
    suspend fun run() = withContext(io) {
        var polls = 0
        var failed = 0
        var calls = 0
        VoiceTrace.event("relay_start")
        try {
            while (isActive) {
                val call = try {
                    polls++
                    link.pending()
                } catch (e: IOException) {
                    // the first one tells why; a turn on a bad link shouldn't fill the trace
                    if (failed++ == 0) VoiceTrace.event("relay_poll_failed", "error" to (e.message ?: e.javaClass.simpleName))
                    Log.d(TAG, "Poll failed: ${e.message}")
                    null
                }
                if (call == null) {
                    delay(pollMs)
                } else {
                    calls++
                    withContext(NonCancellable) { serve(call) }
                }
            }
        } finally {
            VoiceTrace.event("relay_stop", "polls" to polls, "failed" to failed, "calls" to calls)
        }
    }

    private suspend fun serve(call: PhoneToolCall) {
        val started = System.currentTimeMillis()
        VoiceTrace.event("relay_call", "tool" to call.tool)         // no arguments: they can be private
        val result = try {
            execute(call.tool, call.args)
        } catch (e: CancellationException) {
            throw e
        } catch (e: Exception) {
            Log.e(TAG, "Tool ${call.tool} failed", e)
            "Error executing tool: ${e.message ?: e.javaClass.simpleName}"
        }
        val ran = System.currentTimeMillis() - started
        for (attempt in 1..POST_TRIES) {
            try {
                link.post(call.id, result)
                VoiceTrace.event("relay_result", "tool" to call.tool, "chars" to result.length, "ms" to ran,
                    "total_ms" to System.currentTimeMillis() - started, "try" to attempt)
                return
            } catch (e: IOException) {
                Log.w(TAG, "Result of ${call.tool} not delivered (try $attempt): ${e.message}")
                if (attempt == POST_TRIES) {
                    VoiceTrace.event("relay_result_lost", "tool" to call.tool, "error" to (e.message ?: e.javaClass.simpleName))
                } else {
                    delay(POST_RETRY_MS)
                }
            }
        }
    }
}
