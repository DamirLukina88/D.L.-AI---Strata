package com.damirl.ray.network

import android.os.SystemClock
import android.util.Log
import com.damirl.ray.BuildConfig
import com.damirl.ray.audio.VoiceTrace
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.async
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.suspendCancellableCoroutine
import kotlinx.coroutines.withContext
import okhttp3.Call
import okhttp3.Callback
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.Response
import java.io.IOException
import java.net.ConnectException
import java.net.NoRouteToHostException
import java.net.SocketTimeoutException
import java.net.UnknownHostException
import java.util.concurrent.TimeUnit
import kotlin.coroutines.resume

class NetworkClient(
    val lanUrl: String = BuildConfig.STRATA_LAN_URL,
    val remoteUrl: String = BuildConfig.STRATA_REMOTE_URL,
    val apiKey: String = BuildConfig.STRATA_API_KEY
) {
    companion object {
        private const val TAG = "RayNetwork"
        // a route a probe found this recently is used as it is (Ray's voice right after the drawer probed)
        private const val ROUTE_FRESH_MS = 60_000L

        /** One client for the app's page, the voice drawer and Ray's voice, so the route is probed once and agreed on. */
        val shared: NetworkClient by lazy { NetworkClient() }

        /** LAN when it answered, else the tunnel when it answered, else offline. */
        fun chooseRoute(lanOk: Boolean, remoteOk: Boolean, lanUrl: String, remoteUrl: String): NetworkRoute = when {
            lanOk -> NetworkRoute.Lan(lanUrl)
            remoteOk -> NetworkRoute.Remote(remoteUrl)
            else -> NetworkRoute.Offline
        }

        /** True when [route], found by a probe at [probedAt], can be used at [now] without probing again. */
        fun isFresh(route: NetworkRoute, probedAt: Long, now: Long): Boolean =
            route !is NetworkRoute.Offline && probedAt > 0 && now - probedAt < ROUTE_FRESH_MS

        /**
         * True when [e] means the server was never reached (no connection made), so sending the same request again on
         * another route can't send it twice.  A failure after the server answered (an HTTP error, a broken stream)
         * is not one.
         */
        fun isConnectFailure(e: Throwable?): Boolean {
            var cause = e
            while (cause != null) {
                when {
                    cause is ConnectException || cause is UnknownHostException || cause is NoRouteToHostException -> return true
                    // OkHttp: "failed to connect to /192.168.x.x (port 8080) ... after 15000ms"
                    cause is SocketTimeoutException && cause.message?.contains("connect", ignoreCase = true) == true -> return true
                }
                cause = cause.cause
            }
            return false
        }

        fun label(route: NetworkRoute): String = when (route) {
            is NetworkRoute.Lan -> "lan"
            is NetworkRoute.Remote -> "tunnel"
            NetworkRoute.Offline -> "offline"
        }
    }

    val okHttpClient: OkHttpClient = OkHttpClient.Builder()
        .connectTimeout(15, TimeUnit.SECONDS)
        .readTimeout(120, TimeUnit.SECONDS)
        .writeTimeout(30, TimeUnit.SECONDS)
        .build()

    // the LAN answers within milliseconds or not at all (a home address from mobile data goes nowhere); the tunnel goes
    // through Cloudflare (DNS, TLS) and needs longer on a cold mobile link
    private val lanProbeClient: OkHttpClient = okHttpClient.newBuilder()
        .connectTimeout(1500, TimeUnit.MILLISECONDS)
        .readTimeout(1500, TimeUnit.MILLISECONDS)
        .build()
    private val remoteProbeClient: OkHttpClient = okHttpClient.newBuilder()
        .connectTimeout(4, TimeUnit.SECONDS)
        .readTimeout(4, TimeUnit.SECONDS)
        .build()

    private val _currentRoute = MutableStateFlow<NetworkRoute>(NetworkRoute.Offline)
    val currentRoute: StateFlow<NetworkRoute> = _currentRoute.asStateFlow()
    @Volatile private var probedAt = 0L                     // elapsedRealtime when a probe last found a route

    private data class Probe(val ok: Boolean, val ms: Long, val note: String)

    /**
     * Probes the LAN and the tunnel at the same time (on mobile data the LAN's 1.5 s timeout no longer comes before
     * the tunnel's probe) and picks the LAN when it answers, else the tunnel.
     */
    suspend fun probeAndSelectRoute(): NetworkRoute = withContext(Dispatchers.IO) {
        val started = SystemClock.elapsedRealtime()
        coroutineScope {
            val lan = async { probe(lanUrl, lanProbeClient) }
            val remote = async { probe(remoteUrl, remoteProbeClient) }
            val lanResult = lan.await()
            val remoteResult = if (lanResult.ok) {
                remote.cancel()                             // cancels its HTTP call too
                null
            } else remote.await()
            val route = chooseRoute(lanResult.ok, remoteResult?.ok == true, lanUrl, remoteUrl)
            _currentRoute.value = route
            if (route !is NetworkRoute.Offline) probedAt = SystemClock.elapsedRealtime()
            Log.d(TAG, "Route: ${route.displayName} (LAN ${lanResult.note} in ${lanResult.ms} ms" +
                (remoteResult?.let { ", tunnel ${it.note} in ${it.ms} ms" } ?: "") + ")")
            VoiceTrace.event(
                "route", "route" to label(route), "ms" to SystemClock.elapsedRealtime() - started,
                "lan_ok" to lanResult.ok, "lan_ms" to lanResult.ms, "lan_note" to lanResult.note,
                "tunnel_ok" to remoteResult?.ok, "tunnel_ms" to remoteResult?.ms, "tunnel_note" to remoteResult?.note
            )
            route
        }
    }

    /** The route to use now: the current one if a probe found it less than a minute ago, else a new probe. */
    suspend fun ensureRoute(): NetworkRoute {
        val route = _currentRoute.value
        return if (isFresh(route, probedAt, SystemClock.elapsedRealtime())) route else probeAndSelectRoute()
    }

    private suspend fun probe(base: String, client: OkHttpClient): Probe {
        if (base.isBlank()) return Probe(false, 0, "no address")
        val started = SystemClock.elapsedRealtime()
        val request = Request.Builder().url("${base.trimEnd('/')}/v1/models").get().apply {
            if (apiKey.isNotBlank()) addHeader("Authorization", "Bearer $apiKey")
        }.build()
        val call = client.newCall(request)
        return suspendCancellableCoroutine { cont ->
            cont.invokeOnCancellation { call.cancel() }
            call.enqueue(object : Callback {
                override fun onFailure(call: Call, e: IOException) {
                    cont.resume(Probe(false, SystemClock.elapsedRealtime() - started, e.javaClass.simpleName))
                }

                override fun onResponse(call: Call, response: Response) {
                    response.use {
                        cont.resume(Probe(it.isSuccessful, SystemClock.elapsedRealtime() - started, "HTTP ${it.code}"))
                    }
                }
            })
        }
    }

    fun getActiveBaseUrl(): String {
        return when (val r = _currentRoute.value) {
            is NetworkRoute.Lan -> r.url
            is NetworkRoute.Remote -> r.url
            NetworkRoute.Offline -> lanUrl.ifBlank { remoteUrl }      // the same as the page (MainScreen)
        }
    }

    fun newAuthenticatedRequestBuilder(path: String): Request.Builder {
        val base = getActiveBaseUrl().trimEnd('/')
        val fullUrl = if (path.startsWith("/")) "$base$path" else "$base/$path"
        val builder = Request.Builder().url(fullUrl)
        if (apiKey.isNotBlank()) {
            builder.addHeader("Authorization", "Bearer $apiKey")
        }
        return builder
    }
}
