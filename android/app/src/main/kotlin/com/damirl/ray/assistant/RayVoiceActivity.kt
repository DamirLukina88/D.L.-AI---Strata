package com.damirl.ray.assistant

import android.content.Intent
import android.os.Bundle
import android.util.Log
import androidx.activity.ComponentActivity
import androidx.activity.SystemBarStyle
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.lifecycle.lifecycleScope
import com.damirl.ray.MainActivity
import com.damirl.ray.ui.theme.RayTheme

// The voice drawer as an activity over whatever is on screen (the lock screen too).  RayAssistTrampolineActivity
// opens it when the system assistant overlay can't be asked for: Android connects RayVoiceInteractionService to the
// process it started first, and after that process is swiped away the new one has no connection until Android binds
// the service again, so a headset button pressed in between used to open the full app instead
class RayVoiceActivity : ComponentActivity() {

    companion object {
        private const val TAG = "RayVoiceActivity"
    }

    private var drawer: VoiceDrawerController? = null

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        Log.d(TAG, "RayVoiceActivity onCreate, action=${intent?.action}")
        setShowWhenLocked(true)
        setTurnScreenOn(true)
        enableEdgeToEdge(
            statusBarStyle = SystemBarStyle.dark(android.graphics.Color.TRANSPARENT),
            navigationBarStyle = SystemBarStyle.dark(android.graphics.Color.TRANSPARENT)
        )
        val d = VoiceDrawerController(this, lifecycleScope)
        drawer = d
        setContent {
            RayTheme {
                VoiceDrawer(
                    drawer = d,
                    onDismiss = { finish() },
                    onExpand = {
                        startActivity(Intent(this, MainActivity::class.java).apply {
                            flags = Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_SINGLE_TOP
                        })
                        finish()
                    }
                )
            }
        }
        d.start()
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        Log.d(TAG, "RayVoiceActivity onNewIntent, action=${intent.action}")
        drawer?.start()
    }

    override fun onStop() {
        super.onStop()
        drawer?.stopListening()
    }

    override fun onDestroy() {
        super.onDestroy()
        drawer?.destroy()
        drawer = null
    }
}
