package com.damirl.ray

import android.content.Intent
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.ui.Modifier
import com.damirl.ray.assistant.RayAssistTrampolineActivity
import com.damirl.ray.ui.theme.RayTheme
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow

class MainActivity : ComponentActivity() {

    companion object {
        private val _autoListenRequest = MutableStateFlow(false)
        val autoListenRequest: StateFlow<Boolean> = _autoListenRequest.asStateFlow()

        fun clearAutoListenRequest() {
            _autoListenRequest.value = false
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        handleIntent(intent)

        enableEdgeToEdge(
            statusBarStyle = androidx.activity.SystemBarStyle.dark(
                android.graphics.Color.TRANSPARENT
            ),
            navigationBarStyle = androidx.activity.SystemBarStyle.dark(
                android.graphics.Color.TRANSPARENT
            )
        )
        setContent {
            RayTheme {
                Surface(
                    modifier = Modifier.fillMaxSize(),
                    color = MaterialTheme.colorScheme.background
                ) {
                    MainNavigation()
                }
            }
        }
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        handleIntent(intent)
    }

    private fun handleIntent(intent: Intent?) {
        if (intent == null) return
        val action = intent.action
        val shouldListen = intent.getBooleanExtra(RayAssistTrampolineActivity.EXTRA_START_LISTENING, false) ||
                Intent.ACTION_ASSIST == action ||
                Intent.ACTION_VOICE_COMMAND == action ||
                "android.speech.action.VOICE_SEARCH_HANDS_FREE" == action ||
                "android.intent.action.VOICE_ASSIST" == action
        if (shouldListen) {
            _autoListenRequest.value = true
        }
    }
}
