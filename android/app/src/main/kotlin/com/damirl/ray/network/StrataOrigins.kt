package com.damirl.ray.network

import java.net.URI
import com.damirl.ray.BuildConfig

// The Strata server's own addresses (the LAN and the remote URL from secrets.properties).  Only pages and downloads
// from these hosts are trusted: they stay inside the app, may use the RayAndroid bridge and the mic, and their files
// go to Downloads.  Hosts are compared exactly (a "contains" check let look-alike hosts through)
object StrataOrigins {

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

    fun isTrusted(url: String?): Boolean {
        if (url.isNullOrBlank()) return false
        val uri = runCatching { URI(url) }.getOrNull() ?: return false
        return (uri.scheme == "http" || uri.scheme == "https") && isTrustedHost(uri.host)
    }

    private fun hostOf(url: String): String? = runCatching { URI(url).host?.lowercase() }.getOrNull()
}
