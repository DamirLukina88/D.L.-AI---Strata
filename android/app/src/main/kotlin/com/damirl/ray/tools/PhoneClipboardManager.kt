package com.damirl.ray.tools

import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
import android.os.Handler
import android.os.Looper
import android.util.Log
import com.damirl.ray.network.NetworkClient
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONObject
import java.net.URLEncoder
import java.security.MessageDigest
import java.util.Locale
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit

/**
 * Live two-way clipboard synchronization and `phone_clipboard` MCP tool handler.
 *
 * - Event-driven Phone -> PC: registers `ClipboardManager.OnPrimaryClipChangedListener` (zero background polling).
 * - Piggybacked PC -> Phone: applies remote clipboard updates delivered via `/v1/ray/phone/pending` heartbeats.
 * - Deduplicates via SHA-256 hash so phone and PC never enter an echo loop.
 */
object PhoneClipboardManager {
    private const val TAG = "RayClipboard"
    private val JSON_MEDIA = "application/json; charset=utf-8".toMediaType()
    private val OCTET_MEDIA = "application/octet-stream".toMediaType()

    @Volatile private var listenerRegistered = false
    @Volatile private var lastKnownText: String = ""
    @Volatile private var lastSyncedHash: String = ""

    fun sha256(text: String): String {
        val md = MessageDigest.getInstance("SHA-256")
        val digest = md.digest(text.toByteArray(Charsets.UTF_8))
        return digest.joinToString("") { "%02x".format(it) }
    }

    /**
     * Register the zero-polling `OnPrimaryClipChangedListener` on the main thread.
     */
    fun ensureListener(context: Context) {
        if (listenerRegistered) return
        val appCtx = context.applicationContext
        Handler(Looper.getMainLooper()).post {
            if (listenerRegistered) return@post
            try {
                val cm = appCtx.getSystemService(Context.CLIPBOARD_SERVICE) as? ClipboardManager ?: return@post
                cm.addPrimaryClipChangedListener {
                    try {
                        val text = readPrimaryClipOnMain(cm) ?: return@addPrimaryClipChangedListener
                        if (text.isEmpty()) return@addPrimaryClipChangedListener
                        lastKnownText = text
                        val h = sha256(text)
                        if (h == lastSyncedHash) return@addPrimaryClipChangedListener
                        lastSyncedHash = h
                        Thread { pushPhoneClipToServer(text, h) }.start()
                    } catch (e: Throwable) {
                        Log.d(TAG, "Clipboard listener read skipped: ${e.message}")
                    }
                }
                listenerRegistered = true
                // Seed initial clipboard if accessible
                readPrimaryClipOnMain(cm)?.takeIf { it.isNotEmpty() }?.let {
                    lastKnownText = it
                    if (lastSyncedHash.isEmpty()) lastSyncedHash = sha256(it)
                }
                Log.d(TAG, "Clipboard change listener registered")
            } catch (e: Throwable) {
                Log.w(TAG, "Failed to register clipboard listener: ${e.message}")
            }
        }
    }

    /**
     * Called by `RayAccessibilityService` when a copy or text selection action occurs so clipboard changes
     * are captured even when another app is in the foreground.
     */
    fun onAccessibilityCopyCandidate(context: Context, fallbackText: String? = null) {
        ensureListener(context)
        val appCtx = context.applicationContext
        Handler(Looper.getMainLooper()).post {
            try {
                val cm = appCtx.getSystemService(Context.CLIPBOARD_SERVICE) as? ClipboardManager
                val text = (cm?.let { readPrimaryClipOnMain(it) } ?: fallbackText).orEmpty()
                if (text.isEmpty()) return@post
                lastKnownText = text
                val h = sha256(text)
                if (h == lastSyncedHash) return@post
                lastSyncedHash = h
                Thread { pushPhoneClipToServer(text, h) }.start()
            } catch (_: Throwable) {
            }
        }
    }

    /**
     * Called by `PhoneToolRelay` when the server piggybacks a PC clipboard change on `/v1/ray/phone/pending`.
     */
    fun applyRemoteClipboardIfChanged(context: Context, text: String, hash: String = "") {
        if (text.isEmpty()) return
        val effectiveHash = hash.ifEmpty { sha256(text) }
        if (effectiveHash == lastSyncedHash || text == lastKnownText) return
        lastSyncedHash = effectiveHash
        lastKnownText = text
        val appCtx = context.applicationContext
        Handler(Looper.getMainLooper()).post {
            try {
                val cm = appCtx.getSystemService(Context.CLIPBOARD_SERVICE) as? ClipboardManager ?: return@post
                cm.setPrimaryClip(ClipData.newPlainText("Ray PC Sync", text))
                Log.d(TAG, "Applied PC clipboard to phone (${text.length} chars)")
            } catch (e: Throwable) {
                Log.w(TAG, "Failed to apply remote clipboard: ${e.message}")
            }
        }
    }

    /**
     * Execute `phone_clipboard` MCP tool (`action`: "get" or "set").
     */
    fun execute(context: Context, action: String = "get", text: String = ""): String {
        ensureListener(context)
        val act = action.trim().lowercase(Locale.US)
        val appCtx = context.applicationContext

        if (act == "set" || act == "write" || act == "copy") {
            if (text.isEmpty()) return "Error: 'text' is required when setting the clipboard."
            val h = sha256(text)
            lastSyncedHash = h
            lastKnownText = text
            var err: String? = null
            runOnMainSync {
                try {
                    val cm = appCtx.getSystemService(Context.CLIPBOARD_SERVICE) as? ClipboardManager
                    if (cm == null) {
                        err = "Error: ClipboardManager unavailable."
                    } else {
                        cm.setPrimaryClip(ClipData.newPlainText("Ray", text))
                    }
                } catch (e: Throwable) {
                    err = "Error setting clipboard: ${e.message}"
                }
            }
            if (err != null) return err!!
            Thread { pushPhoneClipToServer(text, h) }.start()
            return "Phone clipboard updated (${text.length} chars) and synced to PC."
        }

        // Default: "get" / "read"
        var clipText: String? = null
        runOnMainSync {
            try {
                val cm = appCtx.getSystemService(Context.CLIPBOARD_SERVICE) as? ClipboardManager
                if (cm != null) {
                    clipText = readPrimaryClipOnMain(cm)
                }
            } catch (_: Throwable) {
            }
        }
        val resolved = clipText?.takeIf { it.isNotEmpty() } ?: lastKnownText
        return if (resolved.isNotEmpty()) {
            lastKnownText = resolved
            "Phone clipboard (${resolved.length} chars):\n$resolved"
        } else {
            "Phone clipboard is currently empty (or no text clip is stored)."
        }
    }

    private fun readPrimaryClipOnMain(cm: ClipboardManager): String? {
        if (!cm.hasPrimaryClip()) return null
        val clip = cm.primaryClip ?: return null
        if (clip.itemCount <= 0) return null
        val item = clip.getItemAt(0) ?: return null
        return item.text?.toString() ?: item.coerceToText(null)?.toString()
    }

    private fun runOnMainSync(block: () -> Unit) {
        if (Looper.myLooper() == Looper.getMainLooper()) {
            block()
            return
        }
        val latch = CountDownLatch(1)
        Handler(Looper.getMainLooper()).post {
            try {
                block()
            } finally {
                latch.countDown()
            }
        }
        try {
            latch.await(2, TimeUnit.SECONDS)
        } catch (_: InterruptedException) {
        }
    }

    private fun pushPhoneClipToServer(text: String, hash: String) {
        val network = NetworkClient.shared
        val payload = JSONObject()
            .put("text", text)
            .put("hash", hash)
            .put("source", "phone")
            .put("updated_ms", System.currentTimeMillis())
            .toString()
            .toByteArray(Charsets.UTF_8)

        try {
            val req = network.newAuthenticatedRequestBuilder("/v1/ray/phone/clipboard")
                .post(payload.toRequestBody(JSON_MEDIA))
                .build()
            network.okHttpClient.newCall(req).execute().use { r ->
                if (r.isSuccessful) return
            }
        } catch (_: Throwable) {
        }
        try {
            val rel = "phone-photos/_ray_clipboard_sync.json"
            val req = network.newAuthenticatedRequestBuilder(
                "/v1/ray/phone/upload?file=" + URLEncoder.encode(rel, "UTF-8")
            )
                .header("X-Filename", rel)
                .post(payload.toRequestBody(OCTET_MEDIA))
                .build()
            network.okHttpClient.newCall(req).execute().close()
        } catch (e: Throwable) {
            Log.d(TAG, "Clipboard sync push skipped: ${e.message}")
        }
    }
}
