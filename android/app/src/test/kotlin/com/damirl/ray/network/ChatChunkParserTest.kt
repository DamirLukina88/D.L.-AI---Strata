package com.damirl.ray.network

import kotlinx.serialization.json.Json
import org.junit.Assert.assertEquals
import org.junit.Test

// /v1/ray/chat stream lines -> the voice drawer's pieces (answer, thinking, tool call)
class ChatChunkParserTest {

    private val json = Json { ignoreUnknownKeys = true; isLenient = true }

    private fun chunk(delta: String, extra: String = "") =
        """{"id":"chatcmpl-ray","object":"chat.completion.chunk","choices":[{"index":0,"delta":$delta,"finish_reason":null}]$extra}"""

    @Test
    fun answerText() {
        assertEquals(listOf(ChatDelta.Text("Hi!")), parseChatChunk(json, chunk("""{"content":"Hi!"}""")))
    }

    @Test
    fun thinkingIsNotAnswer() {
        assertEquals(listOf(ChatDelta.Thinking("hmm")), parseChatChunk(json, chunk("""{"reasoning_content":"hmm"}""")))
    }

    @Test
    fun toolCall() {
        assertEquals(
            listOf(ChatDelta.Tool("phone__phone_get_battery")),
            parseChatChunk(json, chunk("{}", ""","ray_tool":{"name":"phone__phone_get_battery"}"""))
        )
    }

    @Test
    fun doneEmptyAndBrokenLinesGiveNothing() {
        assertEquals(emptyList<ChatDelta>(), parseChatChunk(json, "[DONE]"))
        assertEquals(emptyList<ChatDelta>(), parseChatChunk(json, ""))
        assertEquals(emptyList<ChatDelta>(), parseChatChunk(json, "{not json"))
        assertEquals(emptyList<ChatDelta>(), parseChatChunk(json, chunk("""{"content":""}""")))
        assertEquals(emptyList<ChatDelta>(), parseChatChunk(json, chunk("""{"content":null}""")))
    }

    // an older server sends only content: the drawer keeps working
    @Test
    fun plainOpenAiChunk() {
        assertEquals(listOf(ChatDelta.Text("ok")), parseChatChunk(json, chunk("""{"role":"assistant","content":"ok"}""")))
    }
}
