package com.damirl.ray.assistant

import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Test
import java.nio.ByteBuffer
import java.nio.ByteOrder

class WakeClipsTest {
    private fun shorts(vararg v: Int) = ShortArray(v.size) { v[it].toShort() }

    @Test
    fun aRingNotYetFullKeepsEverythingInOrder() {
        val ring = ClipRing(5)
        ring.add(shorts(1, 2, 3), 3)
        assertArrayEquals(shorts(1, 2, 3), ring.snapshot())
    }

    @Test
    fun aFullRingKeepsOnlyTheNewest() {
        val ring = ClipRing(4)
        ring.add(shorts(1, 2, 3), 3)
        ring.add(shorts(4, 5, 6), 3)
        assertArrayEquals(shorts(3, 4, 5, 6), ring.snapshot())
    }

    @Test
    fun aBlockLargerThanTheRingKeepsItsEnd() {
        val ring = ClipRing(3)
        ring.add(shorts(1, 2, 3, 4, 5, 6, 7), 7)
        assertArrayEquals(shorts(5, 6, 7), ring.snapshot())
    }

    @Test
    fun onlyTheCountedSamplesAreAdded() {
        val ring = ClipRing(5)
        ring.add(shorts(1, 2, 9, 9), 2)
        assertArrayEquals(shorts(1, 2), ring.snapshot())
    }

    @Test
    fun theWavHeaderDescribesTheSound() {
        val bytes = WakeClips.wav(shorts(1, -2), 16000)
        assertEquals(48, bytes.size)
        val b = ByteBuffer.wrap(bytes).order(ByteOrder.LITTLE_ENDIAN)
        assertEquals("RIFF", String(bytes, 0, 4))
        assertEquals(40, b.getInt(4))
        assertEquals("WAVE", String(bytes, 8, 4))
        assertEquals(1, b.getShort(20).toInt())                    // plain PCM
        assertEquals(1, b.getShort(22).toInt())                    // mono
        assertEquals(16000, b.getInt(24))
        assertEquals(32000, b.getInt(28))
        assertEquals(16, b.getShort(34).toInt())
        assertEquals("data", String(bytes, 36, 4))
        assertEquals(4, b.getInt(40))
        assertEquals(1, b.getShort(44).toInt())
        assertEquals(-2, b.getShort(46).toInt())
    }
}
