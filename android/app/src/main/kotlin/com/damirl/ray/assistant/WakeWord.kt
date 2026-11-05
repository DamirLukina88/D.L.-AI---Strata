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
    private const val KEY_CLIPS = "save_clips"

    private val _held = MutableStateFlow<Set<String>>(emptySet())
    val held: StateFlow<Set<String>> = _held.asStateFlow()

    fun isOn(context: Context): Boolean =
        context.getSharedPreferences(PREFS, Context.MODE_PRIVATE).getBoolean(KEY_ON, false)

    /** Whether each wake leaves a short recording on the phone (WakeClips).  Off unless set for a test, over adb. */
    fun savesClips(context: Context): Boolean =
        context.getSharedPreferences(PREFS, Context.MODE_PRIVATE).getBoolean(KEY_CLIPS, false)

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

    // the phrases that wake him
    val PHRASES = listOf("ok ray", "okay ray")

    // Words that sound like them, as answers Vosk can give.  With only the phrases and [unk] to choose from it turned
    // "okay they" into "okay ray"; with these it says "okay they", and nothing here wakes him.  Vosk's confidence
    // can't do this job: in grammar mode it is about 0.5 for the phrase and for look-alikes alike
    private val OKAY_LOOKALIKES = listOf(
        "they", "day", "way", "may", "play", "pray", "great", "gray", "grey", "wait", "right", "rate", "red", "read",
        "ready", "rain", "rare", "race", "raise", "rail", "ring", "rich", "train", "today", "stay", "tray"
    )
    val DECOYS = OKAY_LOOKALIKES.map { "okay $it" } + listOf("hey ray", "ray", "okay", "ok", "hey", "right", "hey there")

    // what Vosk may answer
    val GRAMMAR = PHRASES + DECOYS + "[unk]"

    // when the phrase started and ended in a final result, in seconds
    data class Heard(val word: String, val start: Double, val end: Double)

    const val MIN_SECONDS = 0.30                                  // shorter than anyone says the phrase: a noise
    const val MAX_SECONDS = 1.80                                  // longer: stretched out of something else

    fun matches(text: String): Boolean = text.trim().lowercase() in PHRASES

    /** Whether a final result is the phrase on its own, said in about the time the phrase takes. */
    fun accepts(text: String, words: List<Heard>): Boolean {
        if (!matches(text) || words.isEmpty()) return false
        return words.last().end - words.first().start in MIN_SECONDS..MAX_SECONDS
    }
}
