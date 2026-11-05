package com.damirl.ray.assistant

import kotlin.math.log10
import kotlin.math.sqrt

// A cheap loudness check in front of Vosk, so the recognizer only runs on sound that stands out from the room.  It
// follows the room's noise level and opens when a frame is well above it for a moment; while it is closed the only
// work is measuring the level.  One decision per 20 ms frame
class SpeechGate(
    private val openAboveDb: Double = 9.0,          // this far above the room
    private val openFrames: Int = 3,                // for this many frames in a row (60 ms: not a click)
    private val hangFrames: Int = 40,               // stays open this long after the last loud frame (800 ms)
    private val silentDb: Double = -70.0            // the room is never taken as quieter than this
) {
    var floorDb = silentDb
        private set
    var open = false
        private set
    private var loudRun = 0
    private var quietRun = 0

    /** Takes one frame's level (see [levelDb]) and says whether the gate is open after it. */
    fun push(levelDb: Double): Boolean {
        val loud = levelDb >= floorDb + openAboveDb
        // falls quickly with a quieter room, rises slowly (about 4 s) so one sentence doesn't count as the room
        floorDb = (floorDb + (levelDb - floorDb) * (if (levelDb < floorDb) 0.2 else 0.005)).coerceAtLeast(silentDb)
        if (loud) {
            loudRun++
            quietRun = 0
            if (loudRun >= openFrames) open = true
        } else {
            loudRun = 0
            if (open && ++quietRun >= hangFrames) open = false
        }
        return open
    }

    companion object {
        /** A frame's RMS level in dB, where 0 is full scale (16-bit samples). */
        fun levelDb(samples: ShortArray, from: Int, count: Int): Double {
            var sum = 0.0
            for (i in from until from + count) sum += samples[i].toDouble() * samples[i]
            val rms = sqrt(sum / count.coerceAtLeast(1)) / 32768.0
            return if (rms <= 1e-5) -100.0 else 20 * log10(rms)
        }
    }
}
