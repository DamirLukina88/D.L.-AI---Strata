package com.damirl.ray.audio

object SpeechCleaner {
    private val THINK_REGEX = Regex("(?is)<think>.*?</think>")
    private val THINK_OPEN_REGEX = Regex("(?is)<think>.*$")
    private val CODE_BLOCK_REGEX = Regex("(?m)(?:^|\\n)```[^\\n`]*\\n[\\s\\S]*?(?:^|\\n)```[ \\t]*(?:\\n|$)")
    private val CODE_BLOCK_OPEN_REGEX = Regex("(?m)(?:^|\\n)```[^\\n`]*\\n[\\s\\S]*$")
    private val HEADER_REGEX = Regex("(?m)^#{1,6}\\s+")
    private val BOLD_ITALIC_REGEX = Regex("[*_]{1,3}([^*_]+)[*_]{1,3}")
    private val BLOCKQUOTE_REGEX = Regex("(?m)^>\\s*")
    private val LIST_BULLET_REGEX = Regex("(?m)^[\\s]*[-*+]\\s+")
    private val LIST_NUMBER_REGEX = Regex("(?m)^[\\s]*\\d+\\.\\s+")
    private val INLINE_CODE_REGEX = Regex("`([^`]+)`")
    private val LINK_REGEX = Regex("\\[([^\\]]+)\\]\\([^)]+\\)")
    private val URL_REGEX = Regex("https?://[^\\s]+")
    private val HORIZONTAL_RULE_REGEX = Regex("(?m)^[-*_]{3,}\\s*$")

    private val DOLLAR_REGEX = Regex("\\$(\\d+(?:\\.\\d+)?)")
    private val PERCENT_NUM_REGEX = Regex("(\\d+)\\s*%")
    private val DEG_C_REGEX = Regex("(?i)(\\d+)\\s*°\\s*C\\b")
    private val DEG_F_REGEX = Regex("(?i)(\\d+)\\s*°\\s*F\\b")
    private val APPROX_REGEX = Regex("~(\\d+)")
    private val ARROWS_REGEX = Regex("->|→|=>|⇒")
    private val PLUS_REGEX = Regex("\\s*\\+\\s*")
    private val EQUALS_REGEX = Regex("\\s*=\\s*")
    private val TECH_PUNCT_REGEX = Regex("[~|^\\\\<>/#*_§©®™•●■◆▪▫◦★☆✓✔✕✖✗]")
    private val PAREN_REGEX = Regex("\\(([^)]+)\\)")
    private val DASH_REGEX = Regex("\\s*[\\u2012\\u2013\\u2014\\u2015\\u2212]\\s*")
    private val WHITESPACE_REGEX = Regex("[ \\t]+")
    private val MULTI_COMMA_REGEX = Regex("(\\s*,)+")
    private val COMMA_SPACE_REGEX = Regex("\\s*,\\s*")
    private val MULTI_NEWLINE_REGEX = Regex("\\n\\s*\\n+")

    fun clean(raw: String): String {
        if (raw.isBlank()) return ""
        var text = raw

        // 1. Thinking blocks
        text = text.replace(THINK_REGEX, "")
        text = text.replace(THINK_OPEN_REGEX, "")

        // 2. Code blocks
        text = text.replace(CODE_BLOCK_REGEX, " [Code block omitted.] ")
        text = text.replace(CODE_BLOCK_OPEN_REGEX, " [Code block omitted.] ")

        // 3. Markdown structures
        text = text.replace(HEADER_REGEX, "")
        text = text.replace(BOLD_ITALIC_REGEX, "$1")
        text = text.replace(BLOCKQUOTE_REGEX, "")
        text = text.replace(LIST_BULLET_REGEX, "")
        text = text.replace(LIST_NUMBER_REGEX, "")
        text = text.replace(INLINE_CODE_REGEX, "$1")
        text = text.replace(LINK_REGEX, "$1")
        text = text.replace(URL_REGEX, "link")
        text = text.replace(HORIZONTAL_RULE_REGEX, "")

        // 4. Units & symbols
        text = text.replace(DOLLAR_REGEX, "$1 dollars")
        text = text.replace(PERCENT_NUM_REGEX, "$1 percent")
        text = text.replace("%", " percent ")
        text = text.replace(DEG_C_REGEX, "$1 degrees Celsius")
        text = text.replace(DEG_F_REGEX, "$1 degrees Fahrenheit")
        text = text.replace("°", " degrees ")
        text = text.replace(APPROX_REGEX, "about $1")
        text = text.replace("&", " and ")
        text = text.replace(ARROWS_REGEX, ", ")
        text = text.replace(PLUS_REGEX, " plus ")
        text = text.replace(EQUALS_REGEX, " equals ")

        // 5. Strip all Unicode emojis, pictograms, and symbols
        val sb = StringBuilder(text.length)
        var i = 0
        while (i < text.length) {
            val cp = text.codePointAt(i)
            val charCount = Character.charCount(cp)
            val type = Character.getType(cp)

            val isEmojiOrPictogram = type == Character.OTHER_SYMBOL.toInt() ||
                type == Character.MODIFIER_SYMBOL.toInt() ||
                cp == 0xFE0E || cp == 0xFE0F || cp == 0x200D ||
                (cp in 0x1F300..0x1FAFF) ||
                (cp in 0x2600..0x27BF) ||
                (cp in 0x1F600..0x1F64F) ||
                (cp in 0x1F680..0x1F6FF)

            if (!isEmojiOrPictogram) {
                sb.appendCodePoint(cp)
            }
            i += charCount
        }
        text = sb.toString()

        // 6. Technical punctuation and parentheses
        text = text.replace(TECH_PUNCT_REGEX, " ")
        text = text.replace(PAREN_REGEX, ", $1, ")
        text = text.replace(DASH_REGEX, ", ")

        // 7. Whitespace and punctuation cleanup
        text = text.replace(WHITESPACE_REGEX, " ")
        text = text.replace(MULTI_COMMA_REGEX, ",")
        text = text.replace(COMMA_SPACE_REGEX, ", ")
        text = text.replace(MULTI_NEWLINE_REGEX, "\n\n")

        return text.trim()
    }
}
