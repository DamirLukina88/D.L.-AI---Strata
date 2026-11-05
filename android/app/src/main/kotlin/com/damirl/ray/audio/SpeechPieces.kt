package com.damirl.ray.audio

// Ray starts speaking once the first piece of an answer is made, not the whole answer (2.3 s for 704 characters; the
// first sentence takes 0.57 s).  Each piece is 4 times the one before: it plays for far longer than the next takes
// to make (about 17 characters a second against 320), so the next is ready when it ends even on a slow link.  Every
// cut is at the end of a sentence or line, and no piece holds a line break: a WAV from the server stops at the first.
object SpeechPieces {
    const val FIRST_CHARS = 80
    private const val GROWTH = 4
    private val SENTENCE_END = Regex("(?<=[.!?])\\s+")
    private val SAID_TO_THE_END = Regex("[.!?:;,]$")

    fun split(cleanText: String): List<String> {
        val sentences = cleanText.lines().map { it.trim() }.filter { it.isNotEmpty() }
            .map { if (SAID_TO_THE_END.containsMatchIn(it)) it else "$it." }     // a line without one still ends
            .flatMap { it.split(SENTENCE_END) }
        val pieces = mutableListOf<String>()
        var size = FIRST_CHARS
        val piece = StringBuilder()
        for (sentence in sentences) {
            if (piece.isNotEmpty()) piece.append(' ')
            piece.append(sentence)
            if (piece.length >= size) {
                pieces += piece.toString()
                piece.clear()
                size *= GROWTH
            }
        }
        if (piece.isNotEmpty()) pieces += piece.toString()
        return pieces
    }
}
