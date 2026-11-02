package com.damirl.ray.assistant

import android.content.Context
import android.os.Bundle
import android.service.voice.VoiceInteractionSession
import android.util.Log
import android.view.View
import androidx.compose.animation.AnimatedVisibility
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.Mic
import androidx.compose.material.icons.filled.Stop
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.ComposeView
import androidx.compose.ui.platform.ViewCompositionStrategy
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleOwner
import androidx.lifecycle.LifecycleRegistry
import androidx.lifecycle.ViewModelStore
import androidx.lifecycle.ViewModelStoreOwner
import androidx.lifecycle.setViewTreeLifecycleOwner
import androidx.lifecycle.setViewTreeViewModelStoreOwner
import androidx.savedstate.SavedStateRegistry
import androidx.savedstate.SavedStateRegistryController
import androidx.savedstate.SavedStateRegistryOwner
import androidx.savedstate.setViewTreeSavedStateRegistryOwner
import com.damirl.ray.audio.AudioPlaybackService
import com.damirl.ray.audio.SpeechRecognitionManager
import com.damirl.ray.network.ChatMessage
import com.damirl.ray.network.NetworkClient
import com.damirl.ray.network.RayChatRepository
import com.damirl.ray.ui.theme.RayTheme
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.flow.catch
import kotlinx.coroutines.launch

class RayVoiceSession(context: Context) : VoiceInteractionSession(context),
    LifecycleOwner, ViewModelStoreOwner, SavedStateRegistryOwner {

    companion object {
        private const val TAG = "RayVoiceSession"
    }

    private val lifecycleRegistry = LifecycleRegistry(this)
    private val savedStateRegistryController = SavedStateRegistryController.create(this)
    private val store = ViewModelStore()

    override val lifecycle: Lifecycle get() = lifecycleRegistry
    override val savedStateRegistry: SavedStateRegistry get() = savedStateRegistryController.savedStateRegistry
    override val viewModelStore: ViewModelStore get() = store

    private val sessionScope = CoroutineScope(SupervisorJob() + Dispatchers.Main)
    private val networkClient = NetworkClient()
    private val chatRepository = RayChatRepository(networkClient)
    private var speechManager: SpeechRecognitionManager? = null

    // UI state observable by Compose
    private var sessionTitle by mutableStateOf("Listening...")
    private var userPrompt by mutableStateOf("")
    private var assistantResponse by mutableStateOf("")
    private var activeToolNote by mutableStateOf<String?>(null)
    private var isThinkingOrStreaming by mutableStateOf(false)
    private var isListening by mutableStateOf(false)

    override fun onCreate() {
        super.onCreate()
        savedStateRegistryController.performRestore(null)
        lifecycleRegistry.handleLifecycleEvent(Lifecycle.Event.ON_CREATE)
        speechManager = SpeechRecognitionManager(context)

        window?.window?.let { win ->
            win.setLayout(
                android.view.ViewGroup.LayoutParams.MATCH_PARENT,
                android.view.ViewGroup.LayoutParams.MATCH_PARENT
            )
            win.setGravity(android.view.Gravity.BOTTOM)
            win.addFlags(
                android.view.WindowManager.LayoutParams.FLAG_SHOW_WHEN_LOCKED or
                android.view.WindowManager.LayoutParams.FLAG_TURN_SCREEN_ON or
                android.view.WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON
            )
        }
        setContentView(onCreateContentView())
    }

    override fun onCreateContentView(): View {
        val composeView = ComposeView(context).apply {
            setViewCompositionStrategy(ViewCompositionStrategy.DisposeOnDetachedFromWindow)

            setViewTreeLifecycleOwner(this@RayVoiceSession)
            setViewTreeViewModelStoreOwner(this@RayVoiceSession)
            setViewTreeSavedStateRegistryOwner(this@RayVoiceSession)

            setContent {
                RayTheme {
                    AssistantOverlayScreen(
                        title = sessionTitle,
                        prompt = userPrompt,
                        response = assistantResponse,
                        toolNote = activeToolNote,
                        isListening = isListening,
                        isStreaming = isThinkingOrStreaming,
                        onDismiss = { hide() },
                        onExpand = {
                            val intent = android.content.Intent(context, com.damirl.ray.MainActivity::class.java).apply {
                                flags = android.content.Intent.FLAG_ACTIVITY_NEW_TASK or android.content.Intent.FLAG_ACTIVITY_SINGLE_TOP
                            }
                            context.startActivity(intent)
                            hide()
                        },
                        onMicTap = {
                            if (isListening) {
                                speechManager?.stopListening()
                            } else {
                                startListeningLoop()
                            }
                        }
                    )
                }
            }
        }
        return composeView
    }

    override fun onShow(args: Bundle?, showFlags: Int) {
        super.onShow(args, showFlags)
        lifecycleRegistry.handleLifecycleEvent(Lifecycle.Event.ON_START)
        lifecycleRegistry.handleLifecycleEvent(Lifecycle.Event.ON_RESUME)
        Log.d(TAG, "RayVoiceSession onShow, showFlags=$showFlags")

        // Reset state
        userPrompt = ""
        assistantResponse = ""
        activeToolNote = null
        isThinkingOrStreaming = false

        // Probe route in background
        sessionScope.launch {
            networkClient.probeAndSelectRoute()
        }

        startListeningLoop()
    }

    private fun startListeningLoop() {
        isListening = true
        sessionTitle = "Listening..."
        userPrompt = ""
        activeToolNote = null

        speechManager?.startListening(
            onFinalResult = { transcribed ->
                Log.d(TAG, "Assistant session speech: '$transcribed'")
                isListening = false
                userPrompt = transcribed
                processQuery(transcribed)
            },
            onError = { err ->
                Log.w(TAG, "Assistant session STT error: $err")
                isListening = false
                sessionTitle = err
            }
        )
    }

    private fun processQuery(text: String) {
        if (text.isBlank()) return

        sessionTitle = "Ray is thinking..."
        isThinkingOrStreaming = true
        assistantResponse = ""
        activeToolNote = null

        val messages = listOf(ChatMessage(role = "user", content = text))

        sessionScope.launch {
            var accumulated = ""
            chatRepository.streamChat(messages, isVoice = true)
                .catch { error ->
                    isThinkingOrStreaming = false
                    assistantResponse = "Error: ${error.message}"
                    sessionTitle = "Connection error"
                }
                .collect { token ->
                    sessionTitle = "Ray is answering..."
                    accumulated += token
                    if (token.contains("phone_") || token.contains("[Tool]")) {
                        activeToolNote = "🔧 Executing phone tool..."
                    }
                    assistantResponse = accumulated
                }

            isThinkingOrStreaming = false
            sessionTitle = "Ray Assistant 🐾"

            if (accumulated.isNotBlank()) {
                AudioPlaybackService.startSpeaking(context, accumulated)
            }
        }
    }

    override fun onHide() {
        super.onHide()
        Log.d(TAG, "RayVoiceSession onHide")
        speechManager?.stopListening()
        isListening = false
        lifecycleRegistry.handleLifecycleEvent(Lifecycle.Event.ON_PAUSE)
        lifecycleRegistry.handleLifecycleEvent(Lifecycle.Event.ON_STOP)
    }

    override fun onDestroy() {
        super.onDestroy()
        Log.d(TAG, "RayVoiceSession onDestroy")
        sessionScope.cancel()
        speechManager?.cancel()
        speechManager = null
        store.clear()
        lifecycleRegistry.handleLifecycleEvent(Lifecycle.Event.ON_DESTROY)
    }
}

@Composable
fun AssistantOverlayScreen(
    title: String,
    prompt: String,
    response: String,
    toolNote: String? = null,
    isListening: Boolean,
    isStreaming: Boolean,
    onDismiss: () -> Unit,
    onExpand: () -> Unit = {},
    onMicTap: () -> Unit
) {
    Box(
        modifier = Modifier
            .fillMaxSize()
            .background(Color.Black.copy(alpha = 0.5f))
            .clickable(
                interactionSource = remember { MutableInteractionSource() },
                indication = null
            ) { onDismiss() }
    ) {
        Surface(
            modifier = Modifier
                .fillMaxWidth()
                .align(Alignment.BottomCenter)
                .clickable(
                    interactionSource = remember { MutableInteractionSource() },
                    indication = null
                ) { /* Consume clicks inside sheet */ },
            shape = RoundedCornerShape(topStart = 28.dp, topEnd = 28.dp),
            color = MaterialTheme.colorScheme.surface,
            tonalElevation = 12.dp,
            shadowElevation = 16.dp
        ) {
            Column(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(20.dp)
            ) {
                // Drag handle
                Box(
                    modifier = Modifier
                        .size(40.dp, 4.dp)
                        .clip(CircleShape)
                        .background(MaterialTheme.colorScheme.outlineVariant)
                        .align(Alignment.CenterHorizontally)
                )

                Spacer(modifier = Modifier.height(14.dp))

                // Header
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.SpaceBetween
                ) {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Box(
                            modifier = Modifier
                                .size(36.dp)
                                .clip(CircleShape)
                                .background(MaterialTheme.colorScheme.primaryContainer),
                            contentAlignment = Alignment.Center
                        ) {
                            Text("🐾", fontSize = 18.sp)
                        }
                        Spacer(modifier = Modifier.width(10.dp))
                        Column {
                            Text(
                                text = "Ray Assistant",
                                fontWeight = FontWeight.Bold,
                                fontSize = 16.sp
                            )
                            Text(
                                text = title,
                                style = MaterialTheme.typography.bodySmall,
                                color = if (isListening) Color(0xFFE53935) else MaterialTheme.colorScheme.outline
                            )
                        }
                    }

                    Row(verticalAlignment = Alignment.CenterVertically) {
                        IconButton(onClick = onExpand) {
                            Text("⤢", fontSize = 20.sp, fontWeight = FontWeight.Bold)
                        }
                        IconButton(onClick = onDismiss) {
                            Icon(Icons.Default.Close, contentDescription = "Close assistant")
                        }
                    }
                }

                Spacer(modifier = Modifier.height(10.dp))

                // Tool note indicator
                if (!toolNote.isNullOrBlank()) {
                    Surface(
                        shape = RoundedCornerShape(12.dp),
                        color = MaterialTheme.colorScheme.secondaryContainer,
                        modifier = Modifier.padding(bottom = 8.dp)
                    ) {
                        Text(
                            text = toolNote,
                            style = MaterialTheme.typography.bodySmall,
                            fontWeight = FontWeight.SemiBold,
                            color = MaterialTheme.colorScheme.onSecondaryContainer,
                            modifier = Modifier.padding(horizontal = 10.dp, vertical = 4.dp)
                        )
                    }
                }

                // Content area
                Column(
                    modifier = Modifier
                        .fillMaxWidth()
                        .height(140.dp)
                        .verticalScroll(rememberScrollState())
                ) {
                    if (prompt.isNotBlank()) {
                        Text(
                            text = "\"$prompt\"",
                            style = MaterialTheme.typography.bodyMedium,
                            fontWeight = FontWeight.SemiBold,
                            color = MaterialTheme.colorScheme.onSurfaceVariant
                        )
                        Spacer(modifier = Modifier.height(8.dp))
                    }

                    if (response.isNotBlank()) {
                        Text(
                            text = response,
                            style = MaterialTheme.typography.bodyLarge,
                            fontSize = 15.sp,
                            color = MaterialTheme.colorScheme.onSurface
                        )
                    } else if (isListening) {
                        Text(
                            text = "Listening for your voice...",
                            style = MaterialTheme.typography.bodyMedium,
                            color = MaterialTheme.colorScheme.outline
                        )
                    } else if (isStreaming) {
                        Row(verticalAlignment = Alignment.CenterVertically) {
                            CircularProgressIndicator(modifier = Modifier.size(16.dp), strokeWidth = 2.dp)
                            Spacer(modifier = Modifier.width(8.dp))
                            Text("Thinking...", style = MaterialTheme.typography.bodySmall)
                        }
                    }
                }

                Spacer(modifier = Modifier.height(12.dp))

                // Bottom Mic action
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.Center
                ) {
                    IconButton(
                        onClick = onMicTap,
                        modifier = Modifier
                            .size(56.dp)
                            .background(
                                color = if (isListening) Color(0xFFE53935) else MaterialTheme.colorScheme.primary,
                                shape = CircleShape
                            )
                    ) {
                        Icon(
                            if (isListening) Icons.Default.Stop else Icons.Default.Mic,
                            contentDescription = if (isListening) "Stop" else "Listen",
                            tint = Color.White,
                            modifier = Modifier.size(28.dp)
                        )
                    }
                }
            }
        }
    }
}
