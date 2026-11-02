package com.damirl.ray.audio

import org.junit.Assert.assertEquals
import org.junit.Test

class SpeechCleanerTest {
    @Test
    fun stripsStandardEmojis() {
        val input = "Hello world! 😄 Great job 🚀"
        assertEquals("Hello world! Great job", SpeechCleaner.clean(input))
    }

    @Test
    fun stripsPawPrintsEmoji() {
        val input = "Started a clean new session! What would you like to work on? 🐾"
        assertEquals("Started a clean new session! What would you like to work on?", SpeechCleaner.clean(input))
    }

    @Test
    fun stripsCompoundEmojis() {
        val input = "Family 👨‍👩‍👧‍👦 and check ✔ done."
        assertEquals("Family and check done.", SpeechCleaner.clean(input))
    }

    @Test
    fun translatesSymbolsAndPreservesNumbers() {
        val input = "Temp is 24°C, humidity 45%, and price is $50."
        assertEquals("Temp is 24 degrees Celsius, humidity 45 percent, and price is 50 dollars.", SpeechCleaner.clean(input))
    }
}
