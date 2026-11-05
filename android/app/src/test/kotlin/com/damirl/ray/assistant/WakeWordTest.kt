package com.damirl.ray.assistant

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class WakeWordTest {
    private fun heard(start: Double = 1.0, end: Double = 1.6) = listOf(
        WakeWord.Heard("ok", start, (start + end) / 2),
        WakeWord.Heard("ray", (start + end) / 2, end)
    )

    @Test
    fun theClearPhraseIsAccepted() {
        assertTrue(WakeWord.accepts("ok ray", heard()))
        assertTrue(WakeWord.accepts(" Okay Ray ", heard()))
    }

    @Test
    fun anythingElseInTheResultIsRefused() {
        assertFalse(WakeWord.accepts("[unk] ok ray", heard()))
        assertFalse(WakeWord.accepts("ok ray [unk]", heard()))
        assertFalse(WakeWord.accepts("ok", heard()))
    }

    @Test
    fun noLookAlikeWakesHim() {
        assertTrue(WakeWord.DECOYS.isNotEmpty())
        assertTrue(WakeWord.DECOYS.none { WakeWord.matches(it) })
        assertTrue("[unk]" in WakeWord.GRAMMAR && WakeWord.PHRASES.all { it in WakeWord.GRAMMAR })
    }

    @Test
    fun tooShortOrTooLongIsRefused() {
        assertFalse(WakeWord.accepts("ok ray", heard(end = 1.2)))
        assertFalse(WakeWord.accepts("ok ray", heard(end = 3.0)))
    }

    @Test
    fun noWordTimingIsRefused() {
        assertFalse(WakeWord.accepts("ok ray", emptyList()))
    }
}

class SpeechGateTest {
    private fun SpeechGate.feed(db: Double, frames: Int): Boolean {
        var open = false
        repeat(frames) { open = push(db) }
        return open
    }

    @Test
    fun stayClosedInAQuietRoom() {
        assertFalse(SpeechGate().feed(-65.0, 500))
    }

    @Test
    fun aClickDoesNotOpenIt() {
        val gate = SpeechGate()
        gate.feed(-65.0, 200)
        gate.feed(-20.0, 2)
        assertFalse(gate.feed(-65.0, 1))
    }

    @Test
    fun speechOpensItAndItClosesAfterTheHang() {
        val gate = SpeechGate()
        gate.feed(-65.0, 200)
        assertTrue(gate.feed(-30.0, 10))
        assertTrue(gate.feed(-65.0, 39))
        assertFalse(gate.feed(-65.0, 1))
    }

    @Test
    fun aSteadyNoiseBecomesTheRoomAndClosesIt() {
        val gate = SpeechGate()
        gate.feed(-65.0, 200)
        gate.feed(-40.0, 2000)
        assertFalse(gate.open)
        assertTrue(gate.feed(-25.0, 5))           // speech over the noise still opens it
    }

    @Test
    fun theLevelOfSilenceAndFullScale() {
        assertEquals(-100.0, SpeechGate.levelDb(ShortArray(320), 0, 320), 0.01)
        assertEquals(0.0, SpeechGate.levelDb(ShortArray(320) { -32768 }, 0, 320), 0.01)
    }
}
