package com.damirl.ray.ui.webview

import android.annotation.SuppressLint
import android.app.Activity
import android.content.Intent
import android.net.Uri
import android.util.Log
import android.view.ViewGroup
import android.webkit.ConsoleMessage
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
            val data = result.data
            val uris = WebChromeClient.FileChooserParams.parseResult(result.resultCode, data)
            filePathCallback?.onReceiveValue(uris)
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
                    allowFileAccess = true
                    allowContentAccess = true
                    useWideViewPort = true
                    loadWithOverviewMode = true
                    mixedContentMode = WebSettings.MIXED_CONTENT_ALWAYS_ALLOW
                    setSupportZoom(false)
                    builtInZoomControls = false
                    displayZoomControls = false
                }

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
                        // Automatically grant Web Audio / Camera permissions inside companion app
                        request?.grant(request.resources)
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

                        // Stay inside WebView for server and local endpoints
                        if (host.contains("damir-lukina.com") || host.startsWith("192.168.") || host == "localhost" || host == "127.0.0.1") {
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

                    override fun onPageFinished(view: WebView?, finishedUrl: String?) {
                        super.onPageFinished(view, finishedUrl)
                        Log.d("RayWebView", "Page loaded: $finishedUrl")
                        view?.evaluateJavascript("if (typeof checkRayAndroidCompanion === 'function') checkRayAndroidCompanion();", null)
                    }
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
