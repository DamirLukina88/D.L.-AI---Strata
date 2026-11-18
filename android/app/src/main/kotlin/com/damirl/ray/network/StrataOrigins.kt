package com.damirl.ray.network

import java.net.URI
import com.damirl.ray.BuildConfig

// The Strata server's own addresses (the LAN and the remote URL from secrets.properties).  Only pages and downloads
// from these hosts are trusted: they stay inside the app, may use the RayAndroid bridge and the mic, and their files
// go to Downloads.  Hosts are compared exactly (a "contains" check let look-alike hosts through)
object StrataOrigins {

    private fun originOf(url: String): String? = runCatching {
        val u = URI(url)
        val scheme = u.scheme?.lowercase() ?: return@runCatching null
        val host = u.host?.lowercase() ?: return@runCatching null
        val port = if (u.port != -1) u.port else if (scheme == "https") 443 else if (scheme == "http") 80 else -1
        "$scheme://$host:$port"
    }.getOrNull()

    private val lanOrigin: String? by lazy { originOf(BuildConfig.STRATA_LAN_URL) }
    private val remoteOrigin: String? by lazy { originOf(BuildConfig.STRATA_REMOTE_URL) }

    /** The LAN address counts only while the route is the LAN, which a probe proved is this server (NetworkClient). */
    @Volatile var lanProven: () -> Boolean = { NetworkClient.shared.currentRoute.value is NetworkRoute.Lan }

    private val hosts: Set<String> by lazy {
        listOf(BuildConfig.STRATA_LAN_URL, BuildConfig.STRATA_REMOTE_URL)
            .mapNotNull { hostOf(it) }
            .filter { it.isNotBlank() }
            .toSet()
    }

    fun isTrustedHost(host: String?): Boolean = host != null && host.lowercase() in hosts

    /** Cloudflare Access's login pages (<team>.cloudflareaccess.com): kept inside the app, but never trusted. */
    fun isLoginHost(host: String?): Boolean {
        val h = host?.lowercase() ?: return false
        return h.endsWith(".cloudflareaccess.com") && h.count { it == '.' } == 2
    }

    /**
     * The page or download is the server's own: the scheme, host and port of one of its two addresses exactly (the
     * host alone let another service on the same PC, e.g. a dev server on :5173, have the bridge and the key), and the
     * LAN one only while it is proven.
     */
    fun isTrusted(url: String?): Boolean = isTrusted(url, lanOrigin, remoteOrigin, lanProven())

    internal fun isTrusted(url: String?, lan: String?, remote: String?, lanOk: Boolean): Boolean {
        if (url.isNullOrBlank()) return false
        val o = originOf(url) ?: return false
        if (!o.startsWith("http://") && !o.startsWith("https://")) return false
        return (remote != null && o == remote) || (lanOk && lan != null && o == lan)
    }

    internal fun originFor(url: String): String? = originOf(url)

    private fun hostOf(url: String): String? = runCatching { URI(url).host?.lowercase() }.getOrNull()
}
