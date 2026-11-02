package com.damirl.ray.network

import android.util.Log
import com.damirl.ray.BuildConfig
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.withContext
import okhttp3.OkHttpClient
import okhttp3.Request
import java.io.IOException
import java.util.concurrent.TimeUnit

class NetworkClient(
    val lanUrl: String = BuildConfig.STRATA_LAN_URL,
    val remoteUrl: String = BuildConfig.STRATA_REMOTE_URL,
    val apiKey: String = BuildConfig.STRATA_API_KEY
) {
    companion object {
        private const val TAG = "RayNetwork"

        /** One client for the app's page and the voice drawer, so the route is probed once and agreed on. */
        val shared: NetworkClient by lazy { NetworkClient() }
    }

    val okHttpClient: OkHttpClient = OkHttpClient.Builder()
        .connectTimeout(15, TimeUnit.SECONDS)
        .readTimeout(120, TimeUnit.SECONDS)
        .writeTimeout(30, TimeUnit.SECONDS)
        .build()

    private val probeClient: OkHttpClient = okHttpClient.newBuilder()
        .connectTimeout(1500, TimeUnit.MILLISECONDS)
        .readTimeout(1500, TimeUnit.MILLISECONDS)
        .build()

    private val _currentRoute = MutableStateFlow<NetworkRoute>(NetworkRoute.Offline)
    val currentRoute: StateFlow<NetworkRoute> = _currentRoute.asStateFlow()

    suspend fun probeAndSelectRoute(): NetworkRoute = withContext(Dispatchers.IO) {
        // 1. Try LAN route first (fast probe)
        if (lanUrl.isNotBlank()) {
            try {
                val reqBuilder = Request.Builder().url("${lanUrl.trimEnd('/')}/v1/models").get()
                if (apiKey.isNotBlank()) {
                    reqBuilder.addHeader("Authorization", "Bearer $apiKey")
                }

                probeClient.newCall(reqBuilder.build()).execute().use { response ->
                    if (response.isSuccessful) {
                        Log.d(TAG, "Using LAN route: $lanUrl")
                        val route = NetworkRoute.Lan(lanUrl)
                        _currentRoute.value = route
                        return@withContext route
                    }
                }
            } catch (e: Exception) {
                Log.d(TAG, "LAN probe failed: ${e.message}, falling back to remote")
            }
        }

        // 2. Try Remote Cloudflare route (/v1/* bypasses Cloudflare Access with Bearer key)
        if (remoteUrl.isNotBlank()) {
            try {
                val reqBuilder = Request.Builder().url("${remoteUrl.trimEnd('/')}/v1/models").get()
                if (apiKey.isNotBlank()) {
                    reqBuilder.addHeader("Authorization", "Bearer $apiKey")
                }
                probeClient.newCall(reqBuilder.build()).execute().use { response ->
                    if (response.isSuccessful) {
                        Log.d(TAG, "Using Cloudflare Tunnel route: $remoteUrl")
                        val route = NetworkRoute.Remote(remoteUrl)
                        _currentRoute.value = route
                        return@withContext route
                    } else {
                        Log.w(TAG, "Remote probe HTTP ${response.code}: ${response.message}")
                    }
                }
            } catch (e: Exception) {
                Log.w(TAG, "Remote probe failed: ${e.message}")
            }
        }

        val offline = NetworkRoute.Offline
        _currentRoute.value = offline
        offline
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
