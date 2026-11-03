package com.damirl.ray.assistant

import android.content.Context
import android.os.Bundle
import android.service.voice.VoiceInteractionSession
import android.util.Log
import android.view.View
import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.tween
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.navigationBarsPadding
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
import androidx.compose.material.icons.filled.OpenInFull
import androidx.compose.material.icons.filled.Stop
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.scale
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.ComposeView
import androidx.compose.ui.platform.ViewCompositionStrategy
import androidx.compose.ui.text.font.FontStyle
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
import com.damirl.ray.ui.components.RayAvatar
import com.damirl.ray.ui.components.RayFaceView
import com.damirl.ray.ui.components.RayMood
import com.damirl.ray.ui.theme.RayTheme
import com.damirl.ray.ui.theme.StrataAccent
import com.damirl.ray.ui.theme.StrataAccentText
import com.damirl.ray.ui.theme.StrataAccentTint
import com.damirl.ray.ui.theme.StrataDanger
import com.damirl.ray.ui.theme.StrataInk
import com.damirl.ray.ui.theme.StrataInkMuted
import com.damirl.ray.ui.theme.StrataInkSoft
import com.damirl.ray.ui.theme.StrataLine
import com.damirl.ray.ui.theme.StrataSurface
import com.damirl.ray.ui.theme.StrataSurface2
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel

// What the drawer is doing, for its status line, its dot and its mic button
enum class VoicePhase { LISTENING, THINKING, ANSWERING, IDLE, ERROR }

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
    private var drawer: VoiceDrawerController? = null

    override fun onCreate() {
        super.onCreate()
        Log.d(TAG, "RayVoiceSession onCreate")
        savedStateRegistryController.performRestore(null)
        lifecycleRegistry.handleLifecycleEvent(Lifecycle.Event.ON_CREATE)
        drawer = VoiceDrawerController(context, sessionScope)

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
                    drawer?.let { d ->
                        VoiceDrawer(
                            drawer = d,
                            onDismiss = { hide() },
                            onExpand = {
                                val intent = android.content.Intent(context, com.damirl.ray.MainActivity::class.java).apply {
                                    flags = android.content.Intent.FLAG_ACTIVITY_NEW_TASK or android.content.Intent.FLAG_ACTIVITY_SINGLE_TOP
                                }
                                context.startActivity(intent)
                                hide()
                            }
                        )
                    }
                }
            }
        }
        return composeView
    }

    override fun onPrepareShow(args: Bundle?, showFlags: Int) {
        super.onPrepareShow(args, showFlags)
        Log.d(TAG, "RayVoiceSession onPrepareShow, showFlags=$showFlags")
    }

    override fun onShow(args: Bundle?, showFlags: Int) {
        super.onShow(args, showFlags)
        lifecycleRegistry.handleLifecycleEvent(Lifecycle.Event.ON_START)
        lifecycleRegistry.handleLifecycleEvent(Lifecycle.Event.ON_RESUME)
        Log.d(TAG, "RayVoiceSession onShow, showFlags=$showFlags")
        VoiceDrawerController.closeOpen = { hide() }
        drawer?.start()
    }

    override fun onHide() {
        super.onHide()
        Log.d(TAG, "RayVoiceSession onHide")
        VoiceDrawerController.closeOpen = null
        drawer?.close()
        lifecycleRegistry.handleLifecycleEvent(Lifecycle.Event.ON_PAUSE)
        lifecycleRegistry.handleLifecycleEvent(Lifecycle.Event.ON_STOP)
    }

    override fun onDestroy() {
        super.onDestroy()
        Log.d(TAG, "RayVoiceSession onDestroy")
        sessionScope.cancel()
        drawer?.destroy()
        drawer = null
        store.clear()
        lifecycleRegistry.handleLifecycleEvent(Lifecycle.Event.ON_DESTROY)
    }
}

// The drawer bound to its controller (the system overlay and RayVoiceActivity both show this)
@Composable
fun VoiceDrawer(drawer: VoiceDrawerController, onDismiss: () -> Unit, onExpand: () -> Unit) {
    val speaking by AudioPlaybackService.isSpeakingState.collectAsState()
    val mood = when {
        speaking -> RayMood.TALKING
        drawer.phase == VoicePhase.LISTENING -> RayMood.LISTENING
        drawer.phase == VoicePhase.THINKING || drawer.phase == VoicePhase.ANSWERING -> RayMood.THINKING
        else -> RayMood.IDLE
    }
    AssistantOverlayScreen(
        face = {
            RayFaceView(
                mood = mood,
                speech = drawer.assistantResponse,
                prompt = drawer.userPrompt,
                toolCalls = drawer.toolCalls,
                lastTool = drawer.lastTool
            )
        },
        thinking = drawer.thinkingText,
        thoughtSeconds = drawer.thoughtSeconds,
        phase = drawer.phase,
        status = drawer.status,
        prompt = drawer.userPrompt,
        partial = drawer.partialText,
        micLevel = drawer.micLevel,
        response = drawer.assistantResponse,
        toolNote = drawer.activeToolNote,
        onDismiss = onDismiss,
        onExpand = onExpand,
        onMicTap = { drawer.onMicTap() }
    )
}

// The drawer that slides up when Ray is held: Ray and what he is doing, what you said (live while you speak), his
// answer, and the mic.  Strata's dark surfaces with the orange accent, like the web app's Code tab
@Composable
fun AssistantOverlayScreen(
    face: @Composable () -> Unit = { RayAvatar(size = 44.dp) },
    thinking: String = "",
    thoughtSeconds: Int? = null,
    phase: VoicePhase,
    status: String,
    prompt: String,
    partial: String,
    micLevel: Float,
    response: String,
    toolNote: String? = null,
    onDismiss: () -> Unit,
    onExpand: () -> Unit = {},
    onMicTap: () -> Unit
) {
    val listening = phase == VoicePhase.LISTENING
    val sheetShape = RoundedCornerShape(topStart = 28.dp, topEnd = 28.dp)

    Box(
        modifier = Modifier
            .fillMaxSize()
            .background(Color.Black.copy(alpha = 0.55f))
            .clickable(
                interactionSource = remember { MutableInteractionSource() },
                indication = null
            ) { onDismiss() }
    ) {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .align(Alignment.BottomCenter)
                .clip(sheetShape)
                .background(StrataSurface)
                .border(1.dp, StrataLine, sheetShape)
                .clickable(
                    interactionSource = remember { MutableInteractionSource() },
                    indication = null
                ) { /* Consume clicks inside sheet */ }
                .navigationBarsPadding()
                .padding(start = 20.dp, end = 12.dp, top = 12.dp, bottom = 20.dp)
        ) {
            // Drag handle
            Box(
                modifier = Modifier
                    .size(40.dp, 4.dp)
                    .clip(CircleShape)
                    .background(StrataLine)
                    .align(Alignment.CenterHorizontally)
            )

            Spacer(modifier = Modifier.height(14.dp))

            // Header: Ray, and what he is doing
            Row(
                modifier = Modifier.fillMaxWidth(),
                verticalAlignment = Alignment.CenterVertically
            ) {
                face()
                Spacer(modifier = Modifier.width(12.dp))
                Column(modifier = Modifier.weight(1f)) {
                    Text("Ray", color = StrataInk, fontWeight = FontWeight.Bold, fontSize = 18.sp)
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        StatusDot(phase)
                        Spacer(modifier = Modifier.width(6.dp))
                        Text(
                            text = status,
                            fontSize = 13.sp,
                            color = when (phase) {
                                VoicePhase.LISTENING -> StrataAccentText
                                VoicePhase.ERROR -> StrataDanger
                                else -> StrataInkMuted
                            }
                        )
                    }
                }
                IconButton(onClick = onExpand) {
                    Icon(Icons.Default.OpenInFull, contentDescription = "Open Ray", tint = StrataInkMuted,
                        modifier = Modifier.size(20.dp))
                }
                IconButton(onClick = onDismiss) {
                    Icon(Icons.Default.Close, contentDescription = "Close", tint = StrataInkMuted)
                }
            }

            Spacer(modifier = Modifier.height(14.dp))

            // What was said and the answer, on the raised surface the web app uses for messages
            val cardShape = RoundedCornerShape(16.dp)
            Column(
                modifier = Modifier
                    .padding(end = 8.dp)
                    .fillMaxWidth()
                    .heightIn(min = 96.dp, max = 240.dp)
                    .clip(cardShape)
                    .background(StrataSurface2)
                    .border(1.dp, StrataLine, cardShape)
                    .verticalScroll(rememberScrollState())
                    .padding(14.dp)
            ) {
                if (!toolNote.isNullOrBlank()) {
                    Text(
                        text = toolNote,
                        fontSize = 12.sp,
                        fontWeight = FontWeight.SemiBold,
                        color = StrataAccentText,
                        modifier = Modifier
                            .padding(bottom = 8.dp)
                            .clip(CircleShape)
                            .background(StrataAccentTint)
                            .padding(horizontal = 10.dp, vertical = 4.dp)
                    )
                }
                val said = prompt.ifBlank { partial }
                if (said.isNotBlank()) {
                    Text(
                        text = "“$said”",
                        fontSize = 15.sp,
                        fontWeight = FontWeight.SemiBold,
                        color = if (prompt.isBlank()) StrataInkMuted else StrataInkSoft
                    )
                    Spacer(modifier = Modifier.height(8.dp))
                }
                if (thinking.isNotBlank()) {
                    ThinkingBlock(thinking, thoughtSeconds)
                    Spacer(modifier = Modifier.height(10.dp))
                }
                when {
                    response.isNotBlank() -> Text(text = response, fontSize = 15.sp, lineHeight = 22.sp,
                        color = if (phase == VoicePhase.ERROR) StrataDanger else StrataInk)
                    listening && said.isBlank() -> Text("Say something…", fontSize = 15.sp, color = StrataInkMuted)
                    phase == VoicePhase.THINKING && thinking.isBlank() -> ThinkingDots()
                    phase == VoicePhase.IDLE && said.isBlank() ->
                        Text("Tap the mic and speak.", fontSize = 15.sp, color = StrataInkMuted)
                }
            }

            Spacer(modifier = Modifier.height(18.dp))

            MicButton(
                listening = listening,
                level = micLevel,
                onClick = onMicTap,
                modifier = Modifier
                    .padding(end = 8.dp)
                    .align(Alignment.CenterHorizontally)
            )
            Spacer(modifier = Modifier.height(8.dp))
            Text(
                text = if (listening) "Tap to stop" else "Tap to speak",
                fontSize = 12.sp,
                color = StrataInkMuted,
                modifier = Modifier
                    .padding(end = 8.dp)
                    .align(Alignment.CenterHorizontally)
            )
        }
    }
}

// The model's thinking, like the web app's: streamed live in a small muted box that follows the newest line while he
// thinks; once the answer starts it folds to "Thought for N s", which opens again on a tap.  Never read aloud
@Composable
private fun ThinkingBlock(thinking: String, thoughtSeconds: Int?) {
    var open by remember(thoughtSeconds == null) { mutableStateOf(thoughtSeconds == null) }
    val scroll = rememberScrollState()
    LaunchedEffect(thinking, open) { if (open && thoughtSeconds == null) scroll.scrollTo(scroll.maxValue) }
    Column {
        Row(
            verticalAlignment = Alignment.CenterVertically,
            modifier = Modifier
                .clip(RoundedCornerShape(8.dp))
                .clickable { open = !open }
                .padding(vertical = 2.dp)
        ) {
            Text(
                text = if (thoughtSeconds == null) "Thinking" else "Thought for $thoughtSeconds s",
                fontSize = 12.sp,
                fontWeight = FontWeight.SemiBold,
                color = StrataInkMuted
            )
            Text(
                text = if (open) "  ⌄" else "  ›",
                fontSize = 12.sp,
                color = StrataInkMuted
            )
        }
        if (open) {
            Text(
                text = thinking.trim(),
                fontSize = 13.sp,
                lineHeight = 19.sp,
                fontStyle = FontStyle.Italic,
                color = StrataInkMuted,
                modifier = Modifier
                    .padding(top = 4.dp)
                    .fillMaxWidth()
                    .heightIn(max = 140.dp)
                    .verticalScroll(scroll)
                    .padding(start = 10.dp)
            )
        }
    }
}

// Orange and breathing while listening or working, muted when idle, red after an error
@Composable
private fun StatusDot(phase: VoicePhase) {
    val busy = phase == VoicePhase.LISTENING || phase == VoicePhase.THINKING || phase == VoicePhase.ANSWERING
    val pulse by rememberInfiniteTransition(label = "dot").animateFloat(
        initialValue = 0.35f, targetValue = 1f,
        animationSpec = infiniteRepeatable(tween(700), RepeatMode.Reverse), label = "dotAlpha"
    )
    val color = when (phase) {
        VoicePhase.ERROR -> StrataDanger
        VoicePhase.IDLE -> StrataInkMuted
        else -> StrataAccent
    }
    Box(
        modifier = Modifier
            .size(8.dp)
            .clip(CircleShape)
            .background(color.copy(alpha = if (busy) pulse else 1f))
    )
}

// Three orange dots rising in turn while Ray thinks
@Composable
private fun ThinkingDots() {
    val t by rememberInfiniteTransition(label = "think").animateFloat(
        initialValue = 0f, targetValue = 3f,
        animationSpec = infiniteRepeatable(tween(1200)), label = "thinkPhase"
    )
    Row(horizontalArrangement = Arrangement.spacedBy(6.dp), modifier = Modifier.padding(vertical = 6.dp)) {
        repeat(3) { i ->
            val on = (t.toInt() % 3) == i
            Box(
                modifier = Modifier
                    .size(8.dp)
                    .clip(CircleShape)
                    .background(if (on) StrataAccent else StrataAccent.copy(alpha = 0.3f))
            )
        }
    }
}

// The orange mic.  While listening a soft ring around it grows with your voice (SpeechRecognizer's level, about
// -2 to 10 dB), so you can see that Ray hears you
@Composable
private fun MicButton(listening: Boolean, level: Float, onClick: () -> Unit, modifier: Modifier = Modifier) {
    val loud = if (listening) ((level + 2f) / 12f).coerceIn(0f, 1f) else 0f
    val ring by animateFloatAsState(targetValue = 1f + 0.45f * loud, animationSpec = tween(120), label = "micRing")
    Box(modifier = modifier.size(96.dp), contentAlignment = Alignment.Center) {
        if (listening) {
            Box(
                modifier = Modifier
                    .size(68.dp)
                    .scale(ring)
                    .clip(CircleShape)
                    .background(StrataAccent.copy(alpha = 0.22f))
            )
        }
        IconButton(
            onClick = onClick,
            modifier = Modifier
                .size(64.dp)
                .clip(CircleShape)
                .background(StrataAccent)
        ) {
            Icon(
                if (listening) Icons.Default.Stop else Icons.Default.Mic,
                contentDescription = if (listening) "Stop listening" else "Speak",
                tint = Color.White,
                modifier = Modifier.size(30.dp)
            )
        }
    }
}
