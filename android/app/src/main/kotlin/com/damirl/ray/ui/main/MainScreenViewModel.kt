package com.damirl.ray.ui.main

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.damirl.ray.network.NetworkClient
import com.damirl.ray.network.NetworkRoute
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.launch

// The app's screen is the web app in a WebView (MainScreen), which shows the conversation itself.  This holds what the
// native side still does there: which route reaches the server (LAN or remote).  Every way of calling Ray by voice
// (power button, headset, tile, assist intent, "Ok Ray") opens the voice drawer (RayAssistTrampolineActivity)
class MainScreenViewModel(
    val networkClient: NetworkClient = NetworkClient.shared
) : ViewModel() {

    val networkRoute: StateFlow<NetworkRoute> = networkClient.currentRoute

    init {
        probeRoute()
    }

    fun probeRoute() {
        viewModelScope.launch { networkClient.probeAndSelectRoute() }
    }
}
