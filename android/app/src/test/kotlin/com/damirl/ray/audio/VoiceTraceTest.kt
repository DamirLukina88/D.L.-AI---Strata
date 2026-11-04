package com.damirl.ray.audio

import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.io.File

class VoiceTraceTest {

    @get:Rule
    val tmp = TemporaryFolder()

    @Test
    fun lineHasTimesEventAndTypedFields() {
        val line = VoiceTrace.line(
            1_793_815_490_123L, 42L, "link_up",
            listOf("reason" to "up", "ms" to 812L, "cold" to true, "device" to null)
        )
        val o = JSONObject(line)
        assertEquals(1_793_815_490_123L, o.getLong("t"))
        assertEquals(42L, o.getLong("up"))
        assertEquals("link_up", o.getString("ev"))
        assertEquals("up", o.getString("reason"))
        assertEquals(812L, o.getLong("ms"))
        assertTrue(o.getBoolean("cold"))
        assertTrue(o.isNull("device"))
    }

    @Test
    fun quotesAndNewlinesStayOneLine() {
        val line = VoiceTrace.line(1L, 2L, "stt_result", listOf("text" to "he said \"hi\"\nthen left"))
        assertFalse(line.contains('\n'))
        assertEquals("he said \"hi\"\nthen left", JSONObject(line).getString("text"))
    }

    @Test
    fun otherValuesAreWrittenAsText() {
        val line = VoiceTrace.line(1L, 2L, "x", listOf("route" to StringBuilder("lan")))
        assertEquals("lan", JSONObject(line).getString("route"))
    }

    @Test
    fun appendsLinesAndRotatesPastTheLimit() {
        val dir = tmp.newFolder()
        VoiceTrace.append(dir, "one", maxBytes = 10)
        VoiceTrace.append(dir, "two", maxBytes = 10)
        assertEquals(listOf("one", "two"), File(dir, VoiceTrace.FILE).readLines())
        VoiceTrace.append(dir, "a-much-longer-line", maxBytes = 10)
        VoiceTrace.append(dir, "three", maxBytes = 10)     // the file passed 10 bytes: it moved to .1
        assertEquals(listOf("three"), File(dir, VoiceTrace.FILE).readLines())
        assertEquals(listOf("one", "two", "a-much-longer-line"), File(dir, "${VoiceTrace.FILE}.1").readLines())
    }
}
