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

class MainActivity : ComponentActivity() {

    companion object {
        /** Ray's app is on screen (the music tools bring it back after waking Brave). */
        @Volatile var shown = false
    }

    override fun onResume() {
        super.onResume()
        shown = true
    }

    override fun onPause() {
        shown = false
        super.onPause()
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        handleIntent(intent)
        com.damirl.ray.assistant.WakeWord.startIfOn(this)     // "Ok Ray", if it is switched on
        com.damirl.ray.tools.PhoneToolRelay.ensureBackgroundRelay(this)

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
        // the same voice drawer as the power button, the helmet button, the tile and "Ok Ray"
        if (shouldListen) {
            startActivity(Intent(this, RayAssistTrampolineActivity::class.java).apply {
                this.action = action ?: Intent.ACTION_ASSIST
                flags = Intent.FLAG_ACTIVITY_NEW_TASK
            })
        }
    }
}
