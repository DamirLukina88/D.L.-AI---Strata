package com.damirl.ray.audio

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class SpeechPiecesTest {
    private val sentence = "This sentence is about forty characters."

    @Test
    fun aShortAnswerIsOnePiece() {
        assertEquals(listOf("Sure thing. It's five past five."), SpeechPieces.split("Sure thing. It's five past five."))
    }

    @Test
    fun nothingToSayIsNoPieces() {
        assertTrue(SpeechPieces.split("").isEmpty())
        assertTrue(SpeechPieces.split(" \n\n ").isEmpty())
    }

    @Test
    fun theFirstPieceIsShortAndEachNextIsLonger() {
        val pieces = SpeechPieces.split(List(40) { sentence }.joinToString(" "))
        assertTrue(pieces.size >= 3)
        assertTrue(pieces[0].length in SpeechPieces.FIRST_CHARS until 2 * SpeechPieces.FIRST_CHARS)
        assertTrue(pieces[1].length >= 3 * pieces[0].length)
    }

    @Test
    fun noWordIsLostOrMoved() {
        val text = List(40) { "$sentence Number $it." }.joinToString(" ")
        assertEquals(text, SpeechPieces.split(text).joinToString(" "))
    }

    @Test
    fun noPieceHoldsALineBreak() {
        val text = "First paragraph, long enough to pass the first limit of eighty characters on its own.\n\nA second one."
        val pieces = SpeechPieces.split(text)
        assertEquals(2, pieces.size)
        assertFalse(pieces.any { it.contains('\n') })
        assertEquals("A second one.", pieces[1])
    }

    @Test
    fun aLineWithoutAStopStillEnds() {
        assertEquals(listOf("Milk. Eggs. Bread."), SpeechPieces.split("Milk\nEggs\nBread."))
    }

    @Test
    fun oneHugeSentenceStaysWhole() {
        val huge = "word ".repeat(200).trim() + "."
        assertEquals(listOf(huge), SpeechPieces.split(huge))
    }
}
