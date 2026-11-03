package com.damirl.ray.ui.main

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.safeDrawingPadding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.compose.LifecycleEventEffect
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import androidx.navigation3.runtime.NavKey
import com.damirl.ray.BuildConfig
import com.damirl.ray.network.NetworkRoute
import com.damirl.ray.ui.webview.RayWebView

@Composable
fun MainScreen(
    onItemClick: (NavKey) -> Unit = {},
    modifier: Modifier = Modifier,
    viewModel: MainScreenViewModel = viewModel()
) {
    val route by viewModel.networkRoute.collectAsStateWithLifecycle()

    // Automatically probe and select optimal low-latency route on resume
    LifecycleEventEffect(Lifecycle.Event.ON_RESUME) {
        viewModel.probeRoute()
    }

    val targetUrl = when (val r = route) {
        is NetworkRoute.Lan -> r.url
        is NetworkRoute.Remote -> r.url
        is NetworkRoute.Offline -> viewModel.networkClient.getActiveBaseUrl()
    }

    Box(
        modifier = modifier
            .fillMaxSize()
            .background(Color(0xFF0B0D10))
            // Status and navigation bars, the camera cutout (left or right in landscape) and the keyboard, which
            // edge-to-edge windows are not resized for
            .safeDrawingPadding()
    ) {
        RayWebView(
            url = targetUrl,
            modifier = Modifier.fillMaxSize()
        )

        // Offline notice banner if disconnected
        if (route is NetworkRoute.Offline) {
            Surface(
                shape = RoundedCornerShape(12.dp),
                color = Color(0xFFFFEBEE),
                modifier = Modifier
                    .fillMaxWidth()
                    .align(Alignment.TopCenter)
                    .padding(horizontal = 16.dp, vertical = 36.dp)
            ) {
                Text(
                    text = "⚠️ Offline: Checking LAN and Tunnel connection...",
                    style = MaterialTheme.typography.bodySmall,
                    fontWeight = FontWeight.SemiBold,
                    color = Color(0xFFC62828),
                    modifier = Modifier.padding(horizontal = 12.dp, vertical = 8.dp)
                )
            }
        }
    }
}
