package com.damirl.ray.ui.webview

import android.app.DownloadManager
import android.content.Context
import android.net.Uri
import android.os.Environment
import android.util.Log
import android.webkit.CookieManager
import android.webkit.WebSettings
import android.widget.Toast
import com.damirl.ray.network.StrataOrigins

// A file from the Strata server into Downloads through Android's download manager (progress and "done" in the
// notification shade).  The web app's workspace hands each file's single-use link straight here (RayAndroid
// .downloadFile): through the WebView's own download path the WebView fetched the link first to see it was a
// download, which used up the ticket, and the download manager then got 403
object Downloads {

    private const val TAG = "RayDownloads"

    fun enqueue(context: Context, url: String, fileName: String?, mimeType: String? = null, userAgent: String? = null): Boolean {
        if (!StrataOrigins.isTrusted(url)) {
            Log.w(TAG, "Download refused: not the Strata server")
            return false
        }
        val name = safeName(fileName) ?: "download"
        return try {
            val request = DownloadManager.Request(Uri.parse(url)).apply {
                setTitle(name)
                if (!mimeType.isNullOrBlank()) setMimeType(mimeType)
                addRequestHeader("User-Agent", userAgent ?: WebSettings.getDefaultUserAgent(context))
                // the Cloudflare Access login, for the remote route
                CookieManager.getInstance().getCookie(url)?.let { addRequestHeader("Cookie", it) }
                setNotificationVisibility(DownloadManager.Request.VISIBILITY_VISIBLE_NOTIFY_COMPLETED)
                setDestinationInExternalPublicDir(Environment.DIRECTORY_DOWNLOADS, name)
            }
            (context.getSystemService(Context.DOWNLOAD_SERVICE) as DownloadManager).enqueue(request)
            Log.d(TAG, "Download queued: $name")
            true
        } catch (e: Exception) {
            Log.e(TAG, "Download failed to start", e)
            Toast.makeText(context, "Download failed: ${e.message}", Toast.LENGTH_LONG).show()
            false
        }
    }

    // a bare file name: no folders, nothing hidden, nothing a file system refuses
    internal fun safeName(name: String?): String? =
        name?.substringAfterLast('/')?.substringAfterLast('\\')
            ?.replace(Regex("""[\u0000-\u001f:*?"<>|]"""), "_")
            ?.trimStart('.')?.trim()
            ?.takeIf { it.isNotBlank() }

    // The file name in Content-Disposition: filename*=UTF-8''… first (any characters), then filename="…".
    // URLUtil.guessFileName only matches a header that ends after filename="…", so with the UTF-8 form after it every
    // workspace file came out as "download.<ext>"
    internal fun attachmentName(contentDisposition: String?): String? {
        if (contentDisposition.isNullOrBlank()) return null
        val name = Regex("""filename\*\s*=\s*UTF-8''([^;]+)""", RegexOption.IGNORE_CASE).find(contentDisposition)
            ?.let { runCatching { java.net.URLDecoder.decode(it.groupValues[1].trim().replace("+", "%2B"), "UTF-8") }.getOrNull() }
            ?: Regex("""filename\s*=\s*"([^"]*)"""", RegexOption.IGNORE_CASE).find(contentDisposition)?.groupValues?.get(1)
            ?: Regex("""filename\s*=\s*([^;]+)""", RegexOption.IGNORE_CASE).find(contentDisposition)?.groupValues?.get(1)?.trim()
        return safeName(name)
    }
}
