package com.damirl.ray.ui.main

import android.content.Context
import android.util.Log
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.damirl.ray.audio.AudioPlaybackService
import com.damirl.ray.audio.SpeechRecognitionManager
import com.damirl.ray.network.ChatDelta
import com.damirl.ray.network.ChatMessage
import com.damirl.ray.network.NetworkClient
import com.damirl.ray.network.NetworkRoute
import com.damirl.ray.network.RayChatRepository
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.catch
import kotlinx.coroutines.launch

// The app's screen is the web app in a WebView (MainScreen), which shows the conversation itself.  This holds what the
// native side still does there: which route reaches the server (LAN or remote), and the "listen now" path of the
// Quick Settings tile and the assist intent (hear one question, send it to Ray, read his answer aloud)
class MainScreenViewModel(
    val networkClient: NetworkClient = NetworkClient.shared,
    private val chatRepository: RayChatRepository = RayChatRepository(networkClient)
) : ViewModel() {

    val networkRoute: StateFlow<NetworkRoute> = networkClient.currentRoute

    private var speechManager: SpeechRecognitionManager? = null
    private val _isListening = MutableStateFlow(false)
    val isListening: StateFlow<Boolean> = _isListening.asStateFlow()
    private var asking = false

    init {
        probeRoute()
    }

    fun probeRoute() {
        viewModelScope.launch { networkClient.probeAndSelectRoute() }
    }

    fun toggleVoiceInput(context: Context) {
        if (_isListening.value) {
            speechManager?.stopListening()
            _isListening.value = false
            return
        }
        val manager = speechManager ?: SpeechRecognitionManager(context).also { speechManager = it }
        _isListening.value = true
        manager.startListening(
            onFinalResult = { transcribed ->
                _isListening.value = false
                ask(context, transcribed)
            },
            onError = { err ->
                _isListening.value = false
                Log.w(TAG, "Listening failed: $err")
            }
        )
    }

    // One spoken question to Ray's shared session; the WebView shows the turn, this reads the answer aloud (the web
    // app doesn't speak turns that came from the phone)
    private fun ask(context: Context, prompt: String) {
        val text = prompt.trim()
        if (text.isBlank() || asking) return
        asking = true
        viewModelScope.launch {
            if (networkRoute.value is NetworkRoute.Offline) networkClient.probeAndSelectRoute()
            var answer = ""
            chatRepository.streamChat(listOf(ChatMessage(role = "user", content = text)), isVoice = true)
                .catch { Log.w(TAG, "Ask failed: ${it.message}") }
                .collect { piece -> if (piece is ChatDelta.Text) answer += piece.text }
            if (answer.isNotBlank()) AudioPlaybackService.startSpeaking(context, answer)
            asking = false
        }
    }

    override fun onCleared() {
        super.onCleared()
        speechManager?.cancel()
        speechManager = null
    }

    companion object {
        private const val TAG = "RayMainVM"
    }
}
