package com.damirl.ray.assistant

import android.content.Context
import android.util.Log
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow

// "Ok Ray": the setting (on/off, kept across restarts) and who is using the mic or the speaker right now.  The listener
// (HotwordListenerService) lets go of the mic while anything holds it: the voice drawer is open, a recognizer is
// listening (drawer or the app's mic button), or Ray is talking; it listens again once all have let go
object WakeWord {

    private const val TAG = "RayWakeWord"
    private const val PREFS = "ray_wake_word"
    private const val KEY_ON = "on"

    private val _held = MutableStateFlow<Set<String>>(emptySet())
    val held: StateFlow<Set<String>> = _held.asStateFlow()

    fun isOn(context: Context): Boolean =
        context.getSharedPreferences(PREFS, Context.MODE_PRIVATE).getBoolean(KEY_ON, false)

    /** Turns "Ok Ray" on or off (the About card's switch) and starts or stops the listener. */
    fun set(context: Context, on: Boolean) {
        context.getSharedPreferences(PREFS, Context.MODE_PRIVATE).edit().putBoolean(KEY_ON, on).apply()
        Log.d(TAG, "Ok Ray ${if (on) "on" else "off"}")
        if (on) HotwordListenerService.start(context) else HotwordListenerService.stop(context)
    }

    /** Starts the listener if the setting is on (when the app opens: Android doesn't allow a mic service at boot). */
    fun startIfOn(context: Context) {
        if (isOn(context)) HotwordListenerService.start(context)
    }

    fun hold(holder: String) {
        _held.value = _held.value + holder
    }

    fun release(holder: String) {
        _held.value = _held.value - holder
    }

    // the phrases that wake him; Vosk is limited to these (and [unk]) so other speech can't match
    val PHRASES = listOf("ok ray", "okay ray")

    fun matches(text: String): Boolean = text.trim().lowercase() in PHRASES
}
