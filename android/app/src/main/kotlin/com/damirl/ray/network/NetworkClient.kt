package com.damirl.ray.network

import android.content.Context
import android.net.ConnectivityManager
import android.net.Network
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
import java.security.MessageDigest
import java.security.SecureRandom
import java.util.concurrent.TimeUnit
import javax.crypto.Mac
import javax.crypto.spec.SecretKeySpec
import kotlin.coroutines.resume
import org.json.JSONObject

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

        /**
         * The answer only the real server can give to [nonce]: HMAC-SHA256(API key, "strata-lan-proof:" + nonce), as
         * serve/server.py's ray_lan_proof computes it.  The LAN address is used, and its page trusted, only when its
         * /v1/ray/proof answers this: on another Wi-Fi a host at the same IP got the key in clear from the probe.
         */
        fun lanProof(apiKey: String, nonce: String): String {
            if (apiKey.isEmpty()) return ""                 // nothing to prove with (an HMAC key can't be empty)
            val mac = Mac.getInstance("HmacSHA256")
            mac.init(SecretKeySpec(apiKey.toByteArray(Charsets.UTF_8), "HmacSHA256"))
            return mac.doFinal("strata-lan-proof:$nonce".toByteArray(Charsets.UTF_8)).joinToString("") { "%02x".format(it) }
        }

        /** True when [body] (the /v1/ray/proof JSON) carries the right proof for [nonce]; compared in constant time. */
        fun proofMatches(apiKey: String, nonce: String, body: String?): Boolean {
            if (apiKey.isBlank() || body.isNullOrBlank()) return false
            val want = lanProof(apiKey, nonce).toByteArray()
            val got = runCatching {
                val o = JSONObject(body)
                val list = o.optJSONArray("proofs")            // a server with several keys: one proof each
                (if (list != null) (0 until list.length()).map { list.optString(it, "") } else emptyList()) +
                    o.optString("proof", "")
            }.getOrDefault(emptyList())
            return got.any { it.isNotEmpty() && MessageDigest.isEqual(it.toByteArray(), want) }
        }

        fun newNonce(): String {
            val b = ByteArray(16)
            SecureRandom().nextBytes(b)
            return b.joinToString("") { "%02x".format(it) }
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

    // the network the LAN was proven on: a proof holds only there.  Another network (a café's Wi-Fi with a host at the
    // same IP) needs its own, or the relay kept polling that host with the key, and the page there was trusted
    @Volatile private var connectivity: ConnectivityManager? = null
    @Volatile private var provenOn: Network? = null

    /** Watch the phone's default network (once; any context): a LAN route proven on another network is dropped. */
    @Synchronized
    fun watchNetwork(context: Context) {
        if (connectivity != null) return
        val cm = context.applicationContext.getSystemService(ConnectivityManager::class.java) ?: return
        val ok = runCatching {
            cm.registerDefaultNetworkCallback(object : ConnectivityManager.NetworkCallback() {
                override fun onAvailable(network: Network) = forgetLanUnlessOn(network)
                override fun onLost(network: Network) = forgetLanUnlessOn(null)
            })
        }.isSuccess
        if (ok) {
            connectivity = cm
            // a LAN proven before the watch started (no network recorded): it was proven on the network now active
            if (provenOn == null && _currentRoute.value is NetworkRoute.Lan) provenOn = cm.activeNetwork
        }
    }

    /**
     * The relay's check, once a minute while on the LAN: the LAN alone is proven again (not a whole new route choice),
     * and the route changes only on a definite wrong answer.  A slow or lost probe keeps it: the network callback
     * covers a change of network, and a single 1.5 s timeout moved the open page to the tunnel and reloaded it.
     */
    suspend fun reproveLan() {
        if (_currentRoute.value !is NetworkRoute.Lan || isFresh(_currentRoute.value, probedAt, SystemClock.elapsedRealtime())) return
        val r = probeLan()
        when {
            r.ok -> probedAt = SystemClock.elapsedRealtime()
            r.wrongServer -> {
                Log.d(TAG, "LAN re-check: ${r.note}; choosing the route again")
                probedAt = 0L
                _currentRoute.value = NetworkRoute.Offline
            }
            else -> Log.d(TAG, "LAN re-check: ${r.note}; kept for now")
        }
    }

    private fun forgetLanUnlessOn(network: Network?) {
        if (_currentRoute.value is NetworkRoute.Lan && (network == null || network != provenOn)) {
            Log.d(TAG, "Network changed: the LAN route is proven again before it is used")
            probedAt = 0L
            _currentRoute.value = NetworkRoute.Offline
        }
    }

    private val _currentRoute = MutableStateFlow<NetworkRoute>(NetworkRoute.Offline)
    val currentRoute: StateFlow<NetworkRoute> = _currentRoute.asStateFlow()
    @Volatile private var probedAt = 0L                     // elapsedRealtime when a probe last found a route

    /** wrongServer: something answered at the address but not with this server's proof (another network's host). */
    private data class Probe(val ok: Boolean, val ms: Long, val note: String, val wrongServer: Boolean = false)

    /**
     * Probes the LAN and the tunnel at the same time (on mobile data the LAN's 1.5 s timeout no longer comes before
     * the tunnel's probe) and picks the LAN when it answers, else the tunnel.
     */
    suspend fun probeAndSelectRoute(): NetworkRoute = withContext(Dispatchers.IO) {
        val started = SystemClock.elapsedRealtime()
        coroutineScope {
            val lan = async { probeLan() }
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

    /** The LAN, without the key: it must answer this nonce's proof (see [lanProof]). */
    private suspend fun probeLan(): Probe {
        if (lanUrl.isBlank()) return Probe(false, 0, "no address")
        if (apiKey.isBlank()) return Probe(false, 0, "no key to check it with")
        val nonce = newNonce()
        val started = SystemClock.elapsedRealtime()
        val probedOn = connectivity?.activeNetwork
        val call = lanProbeClient.newCall(Request.Builder().url("${lanUrl.trimEnd('/')}/v1/ray/proof?nonce=$nonce").get().build())
        return suspendCancellableCoroutine { cont ->
            cont.invokeOnCancellation { call.cancel() }
            call.enqueue(object : Callback {
                override fun onFailure(call: Call, e: IOException) {
                    cont.resume(Probe(false, SystemClock.elapsedRealtime() - started, e.javaClass.simpleName))
                }

                override fun onResponse(call: Call, response: Response) {
                    response.use {
                        val ok = it.isSuccessful && proofMatches(apiKey, nonce, it.body?.string())
                        if (ok) provenOn = probedOn
                        cont.resume(Probe(ok, SystemClock.elapsedRealtime() - started,
                            if (ok) "HTTP ${it.code}, proof ok" else "HTTP ${it.code}, not this server", wrongServer = !ok))
                    }
                }
            })
        }
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
            // the tunnel (https), not the LAN address: unproven, it may be another network's host, and every request
            // carries the key.  The same as the page (MainScreen)
            NetworkRoute.Offline -> remoteUrl.ifBlank { lanUrl }
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
