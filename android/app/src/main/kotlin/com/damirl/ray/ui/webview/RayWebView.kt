package com.damirl.ray.ui.webview

import android.annotation.SuppressLint
import android.app.Activity
import android.content.Intent
import android.net.Uri
import android.util.Log
import android.view.ViewGroup
import android.webkit.ConsoleMessage
import android.webkit.URLUtil
import android.webkit.PermissionRequest
import android.webkit.ValueCallback
import android.webkit.WebChromeClient
import android.webkit.WebResourceRequest
import android.webkit.WebSettings
import android.webkit.WebView
import android.webkit.WebViewClient
import androidx.activity.compose.BackHandler
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.viewinterop.AndroidView

@SuppressLint("SetJavaScriptEnabled")
@Composable
fun RayWebView(
    url: String,
    modifier: Modifier = Modifier,
    onWebViewReady: (WebView) -> Unit = {}
) {
    val context = LocalContext.current
    var webViewInstance by remember { mutableStateOf<WebView?>(null) }
    var lastLoadedUrl by remember { mutableStateOf("") }
    var filePathCallback by remember { mutableStateOf<ValueCallback<Array<Uri>>?>(null) }

    val fileChooserLauncher = rememberLauncherForActivityResult(
        contract = ActivityResultContracts.StartActivityForResult()
    ) { result ->
        if (result.resultCode == Activity.RESULT_OK) {
            filePathCallback?.onReceiveValue(pickedUris(result.resultCode, result.data))
        } else {
            filePathCallback?.onReceiveValue(null)
        }
        filePathCallback = null
    }

    // Hierarchical back handling: closes web app drawers first before navigating back
    BackHandler(enabled = true) {
        val wv = webViewInstance ?: return@BackHandler
        wv.evaluateJavascript("(function(){ return window.hasOpenDrawer ? window.hasOpenDrawer() : false; })();") { result ->
            val hasDrawer = result == "true"
            if (hasDrawer) {
                wv.evaluateJavascript("if (window.closeOpenDrawer) window.closeOpenDrawer();", null)
            } else if (wv.canGoBack()) {
                wv.goBack()
            } else {
                (context as? Activity)?.moveTaskToBack(true)
            }
        }
    }

    AndroidView(
        modifier = modifier.fillMaxSize(),
        factory = { ctx ->
            WebView(ctx).apply {
                layoutParams = ViewGroup.LayoutParams(
                    ViewGroup.LayoutParams.MATCH_PARENT,
                    ViewGroup.LayoutParams.MATCH_PARENT
                )

                clearCache(true)
                settings.apply {
                    javaScriptEnabled = true
                    domStorageEnabled = true
                    databaseEnabled = true
                    cacheMode = WebSettings.LOAD_DEFAULT
                    mediaPlaybackRequiresUserGesture = false
                    allowFileAccess = false                       // nothing on the phone's storage by file:// URL
                    allowContentAccess = true                     // picked files reach uploads as content:// URIs
                    useWideViewPort = true
                    loadWithOverviewMode = true
                    mixedContentMode = WebSettings.MIXED_CONTENT_NEVER_ALLOW
                    setSupportZoom(false)
                    builtInZoomControls = false
                    displayZoomControls = false
                }

                // Strata's --st-bg until the page draws (WebView is white by default, which flashed on start)
                setBackgroundColor(android.graphics.Color.parseColor("#0B0D10"))
                isVerticalScrollBarEnabled = false
                isHorizontalScrollBarEnabled = false

                // Inject JavascriptInterface bridge
                val bridge = RayNativeBridge(
                    context = ctx,
                    webViewProvider = { this }
                )
                addJavascriptInterface(bridge, "RayAndroid")

                webChromeClient = object : WebChromeClient() {
                    override fun onShowFileChooser(
                        webView: WebView?,
                        callback: ValueCallback<Array<Uri>>?,
                        params: FileChooserParams?
                    ): Boolean {
                        filePathCallback?.onReceiveValue(null)
                        filePathCallback = callback

                        try {
                            val intent = params?.createIntent() ?: Intent(Intent.ACTION_GET_CONTENT).apply {
                                type = "*/*"
                                addCategory(Intent.CATEGORY_OPENABLE)
                            }
                            fileChooserLauncher.launch(intent)
                            return true
                        } catch (e: Exception) {
                            Log.e("RayWebView", "Failed to launch file chooser", e)
                            filePathCallback?.onReceiveValue(null)
                            filePathCallback = null
                            return false
                        }
                    }

                    override fun onPermissionRequest(request: PermissionRequest?) {
                        // the mic and camera for the Strata server's own pages only
                        if (request == null) return
                        if (com.damirl.ray.network.StrataOrigins.isTrusted(request.origin?.toString())) {
                            request.grant(request.resources)
                        } else {
                            Log.w("RayWebView", "Mic/camera refused for ${request.origin}")
                            request.deny()
                        }
                    }

                    override fun onConsoleMessage(consoleMessage: ConsoleMessage?): Boolean {
                        Log.d("RayWebConsole", "[${consoleMessage?.messageLevel()}] ${consoleMessage?.message()} (${consoleMessage?.sourceId()}:${consoleMessage?.lineNumber()})")
                        return true
                    }
                }

                webViewClient = object : WebViewClient() {
                    override fun shouldOverrideUrlLoading(view: WebView?, request: WebResourceRequest?): Boolean {
                        val reqUrl = request?.url ?: return false
                        val host = reqUrl.host ?: ""

                        // Stay inside WebView for the Strata server's own pages, and for Cloudflare Access's login (the email
                        // code) on the way to the remote one: opened in the browser, the login cookie landed there and
                        // the app never got in.  The login pages get no bridge (RayNativeBridge.trusted)
                        if (com.damirl.ray.network.StrataOrigins.isTrustedHost(host) ||
                            com.damirl.ray.network.StrataOrigins.isLoginHost(host)) {
                            return false
                        }

                        // Open external links in default browser
                        return try {
                            val browserIntent = Intent(Intent.ACTION_VIEW, reqUrl)
                            ctx.startActivity(browserIntent)
                            true
                        } catch (e: Exception) {
                            false
                        }
                    }

                    // the bridge answers only while the Strata server's page is shown (RayNativeBridge.trusted)
                    override fun onPageStarted(view: WebView?, startedUrl: String?, favicon: android.graphics.Bitmap?) {
                        bridge.pageUrl = startedUrl
                        super.onPageStarted(view, startedUrl, favicon)
                    }

                    override fun doUpdateVisitedHistory(view: WebView?, visitedUrl: String?, isReload: Boolean) {
                        bridge.pageUrl = visitedUrl
                        super.doUpdateVisitedHistory(view, visitedUrl, isReload)
                    }

                    override fun onPageFinished(view: WebView?, finishedUrl: String?) {
                        super.onPageFinished(view, finishedUrl)
                        Log.d("RayWebView", "Page loaded: $finishedUrl")
                        view?.evaluateJavascript("if (typeof checkRayAndroidCompanion === 'function') checkRayAndroidCompanion();", null)
                    }
                }

                // A WebView ignores downloads unless it is given a listener: files from the Strata server go to Downloads
                // (the workspace's own buttons use RayAndroid.downloadFile instead, see Downloads)
                setDownloadListener { dlUrl, userAgent, contentDisposition, mimeType, _ ->
                    val name = Downloads.attachmentName(contentDisposition)
                        ?: URLUtil.guessFileName(dlUrl, contentDisposition, mimeType)
                    Downloads.enqueue(ctx, dlUrl, name, mimeType, userAgent)
                }

                loadUrl(url)
                lastLoadedUrl = url
                webViewInstance = this
                onWebViewReady(this)
            }
        },
        update = { wv ->
            if (url.isNotBlank() && url != lastLoadedUrl) {
                lastLoadedUrl = url
                wv.loadUrl(url)
            }
        }
    )

    DisposableEffect(Unit) {
        onDispose {
            webViewInstance?.destroy()
            webViewInstance = null
        }
    }
}

// Every file picked in the chooser.  FileChooserParams.parseResult reads only intent.data, but with several files
// picked the gallery puts them all in clipData (and only the first in data), so the page got one file
private fun pickedUris(resultCode: Int, data: Intent?): Array<Uri>? {
    val clip = data?.clipData
    if (clip != null && clip.itemCount > 0) {
        return Array(clip.itemCount) { clip.getItemAt(it).uri }
    }
    data?.data?.let { return arrayOf(it) }
    return WebChromeClient.FileChooserParams.parseResult(resultCode, data)
}
