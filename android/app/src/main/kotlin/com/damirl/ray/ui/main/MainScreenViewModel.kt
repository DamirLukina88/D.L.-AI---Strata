package com.damirl.ray.ui.main

import android.content.Context
import android.util.Log
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.damirl.ray.audio.AudioPlaybackService
import com.damirl.ray.audio.SpeechRecognitionManager
import com.damirl.ray.network.ChatMessage
import com.damirl.ray.network.NetworkClient
import com.damirl.ray.network.NetworkRoute
import com.damirl.ray.network.RayChatRepository
import com.damirl.ray.network.SessionEvent
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.catch
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch

class MainScreenViewModel(
    val networkClient: NetworkClient = NetworkClient(),
    val chatRepository: RayChatRepository = RayChatRepository(networkClient)
) : ViewModel() {

    val networkRoute: StateFlow<NetworkRoute> = networkClient.currentRoute
    val isSpeaking: StateFlow<Boolean> = AudioPlaybackService.isSpeakingState

    private var speechManager: SpeechRecognitionManager? = null
    private val _isListening = MutableStateFlow(false)
    val isListening: StateFlow<Boolean> = _isListening.asStateFlow()

    private val _partialSpeechText = MutableStateFlow("")
    val partialSpeechText: StateFlow<String> = _partialSpeechText.asStateFlow()

    private val _messages = MutableStateFlow<List<ChatMessage>>(emptyList())
    val messages: StateFlow<List<ChatMessage>> = _messages.asStateFlow()

    private val _currentStreamingText = MutableStateFlow("")
    val currentStreamingText: StateFlow<String> = _currentStreamingText.asStateFlow()

    private val _isStreaming = MutableStateFlow(false)
    val isStreaming: StateFlow<Boolean> = _isStreaming.asStateFlow()

    private val _statusText = MutableStateFlow("Probing network...")
    val statusText: StateFlow<String> = _statusText.asStateFlow()

    private val _autoSpeakEnabled = MutableStateFlow(true)
    val autoSpeakEnabled: StateFlow<Boolean> = _autoSpeakEnabled.asStateFlow()

    private var eventsJob: Job? = null

    init {
        probeRoute()
    }

    fun probeRoute() {
        viewModelScope.launch {
            _statusText.value = "Checking routes..."
            val route = networkClient.probeAndSelectRoute()
            _statusText.value = "Connected via ${route.displayName}"
            loadSessionHistory()
            startSessionEventsSync()
        }
    }

    fun loadSessionHistory() {
        viewModelScope.launch {
            val history = chatRepository.fetchHistory()
            _messages.value = history
        }
    }

    private fun startSessionEventsSync() {
        eventsJob?.cancel()
        eventsJob = viewModelScope.launch {
            while (isActive) {
                try {
                    chatRepository.observeSessionEvents()
                        .catch { e ->
                            Log.w("RayChatRepo", "Session events disconnected: ${e.message}")
                            delay(3000)
                        }
                        .collect { ev ->
                            when (ev) {
                                is SessionEvent.Cleared -> {
                                    Log.d("RayChatRepo", "Session cleared -> wiping messages on phone")
                                    _messages.value = emptyList()
                                    _currentStreamingText.value = ""
                                }
                                is SessionEvent.TurnEnd -> {
                                    // Turn completed on desktop, CLI, or phone: reconcile history
                                    if (!_isStreaming.value) {
                                        loadSessionHistory()
                                    }
                                }
                                is SessionEvent.Hello -> {
                                    if (!_isStreaming.value) {
                                        loadSessionHistory()
                                    }
                                }
                                else -> {}
                            }
                        }
                } catch (_: Exception) {
                    delay(3000)
                }
            }
        }
    }

    private fun isNewSessionCommand(prompt: String): Boolean {
        val clean = prompt.trim().lowercase().removeSuffix(".").removeSuffix("!").removeSuffix("?")
        if (clean in listOf(
                "/clear", "/new", "/reset",
                "clear", "new session", "start a new session",
                "start new session", "clear session", "clear conversation",
                "reset session", "reset conversation", "start a new conversation",
                "new conversation", "start over", "start fresh"
            )) return true
        return listOf("start a new session and ", "start a new session to ", "new session, ", "new session: ", "start fresh and ")
            .any { clean.startsWith(it) }
    }

    fun toggleAutoSpeak() {
        _autoSpeakEnabled.value = !_autoSpeakEnabled.value
    }

    fun speak(context: Context, text: String) {
        AudioPlaybackService.startSpeaking(context, text)
    }

    fun stopSpeaking(context: Context) {
        AudioPlaybackService.stopSpeaking(context)
    }

    fun toggleVoiceInput(context: Context) {
        if (_isListening.value) {
            speechManager?.stopListening()
            _isListening.value = false
        } else {
            // Stop any ongoing speech before listening
            AudioPlaybackService.stopSpeaking(context)

            if (speechManager == null) {
                speechManager = SpeechRecognitionManager(context)
            }

            _isListening.value = true
            _partialSpeechText.value = "Listening..."

            speechManager?.startListening(
                onFinalResult = { transcribed ->
                    _isListening.value = false
                    _partialSpeechText.value = ""
                    sendMessage(context, transcribed)
                },
                onError = { err ->
                    _isListening.value = false
                    _partialSpeechText.value = ""
                    _statusText.value = err
                }
            )
        }
    }

    fun sendMessage(context: Context, prompt: String) {
        val trimmed = prompt.trim()
        if (trimmed.isBlank() || _isStreaming.value) return

        val isNewSession = isNewSessionCommand(trimmed)
        val userMsg = ChatMessage(role = "user", content = trimmed)

        val currentList = if (isNewSession) {
            _messages.value = emptyList()
            listOf(userMsg)
        } else {
            val list = _messages.value + userMsg
            _messages.value = list
            list
        }

        _currentStreamingText.value = ""
        _isStreaming.value = true

        viewModelScope.launch {
            if (networkRoute.value is NetworkRoute.Offline) {
                networkClient.probeAndSelectRoute()
            }

            var accumulated = ""
            chatRepository.streamChat(currentList, isVoice = _autoSpeakEnabled.value)
                .catch { error ->
                    _isStreaming.value = false
                    val errorReply = "[Error: ${error.message}]"
                    _messages.value = _messages.value + ChatMessage(role = "assistant", content = errorReply)
                    _currentStreamingText.value = ""
                }
                .collect { token ->
                    accumulated += token
                    _currentStreamingText.value = accumulated
                }

            if (accumulated.isNotBlank()) {
                val finalAssistantMsg = ChatMessage(role = "assistant", content = accumulated)
                if (isNewSession) {
                    _messages.value = listOf(finalAssistantMsg)
                } else {
                    _messages.value = _messages.value + finalAssistantMsg
                }
                if (_autoSpeakEnabled.value) {
                    AudioPlaybackService.startSpeaking(context, accumulated)
                }
            }
            _currentStreamingText.value = ""
            _isStreaming.value = false
            loadSessionHistory()
        }
    }

    override fun onCleared() {
        super.onCleared()
        eventsJob?.cancel()
        eventsJob = null
        speechManager?.cancel()
        speechManager = null
    }
}
