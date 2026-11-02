package com.damirl.ray.network

import android.util.Log
import java.io.IOException
import kotlinx.coroutines.channels.awaitClose
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.callbackFlow
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.RequestBody.Companion.toRequestBody
import okhttp3.Response
import okhttp3.sse.EventSource
import okhttp3.sse.EventSourceListener
import okhttp3.sse.EventSources

/** One piece of Ray's streamed reply: the answer, the model's thinking, or a tool he calls. */
sealed class ChatDelta {
    data class Text(val text: String) : ChatDelta()
    data class Thinking(val text: String) : ChatDelta()
    data class Tool(val name: String) : ChatDelta()
}

/**
 * The pieces in one SSE data line of /v1/ray/chat: delta.content (the answer), delta.reasoning_content (thinking)
 * and ray_tool.name (a tool call).  Empty for [DONE], keep-alives and anything unreadable.
 */
fun parseChatChunk(json: Json, data: String): List<ChatDelta> {
    if (data.isBlank() || data.trim() == "[DONE]") return emptyList()
    val root = runCatching { json.parseToJsonElement(data).jsonObject }.getOrNull() ?: return emptyList()
    val out = mutableListOf<ChatDelta>()
    val delta = root["choices"]?.jsonArray?.firstOrNull()?.jsonObject?.get("delta")?.jsonObject
    delta?.get("reasoning_content")?.jsonPrimitive?.contentOrNull?.takeIf { it.isNotEmpty() }?.let { out += ChatDelta.Thinking(it) }
    delta?.get("content")?.jsonPrimitive?.contentOrNull?.takeIf { it.isNotEmpty() }?.let { out += ChatDelta.Text(it) }
    (root["ray_tool"] as? JsonObject)?.get("name")?.jsonPrimitive?.contentOrNull?.takeIf { it.isNotEmpty() }
        ?.let { out += ChatDelta.Tool(it) }
    return out
}

sealed class SessionEvent {
    data object Cleared : SessionEvent()
    data object TurnEnd : SessionEvent()
    data object Hello : SessionEvent()
    data class Other(val type: String) : SessionEvent()
}

class RayChatRepository(private val networkClient: NetworkClient) {

    companion object {
        private const val TAG = "RayChatRepo"
        private val JSON_MEDIA_TYPE = "application/json; charset=utf-8".toMediaType()
    }

    private val json = Json {
        ignoreUnknownKeys = true
        isLenient = true
        encodeDefaults = true
    }

    fun streamChat(messages: List<ChatMessage>, isVoice: Boolean = false): Flow<ChatDelta> = callbackFlow {
        // Ensure route is active before request
        val baseUrl = networkClient.getActiveBaseUrl()
        Log.d(TAG, "Starting chat stream to $baseUrl/v1/ray/chat (voice=$isVoice)")

        val requestPayload = ChatRequest(
            messages = messages,
            stream = true,
            voice = isVoice
        )

        val bodyString = json.encodeToString(ChatRequest.serializer(), requestPayload)
        val request = networkClient.newAuthenticatedRequestBuilder("/v1/ray/chat")
            .post(bodyString.toRequestBody(JSON_MEDIA_TYPE))
            .header("Accept", "text/event-stream")
            .build()

        val factory = EventSources.createFactory(networkClient.okHttpClient)
        val eventSource = factory.newEventSource(request, object : EventSourceListener() {
            override fun onOpen(eventSource: EventSource, response: Response) {
                Log.d(TAG, "SSE stream opened: HTTP ${response.code}")
            }

            override fun onEvent(eventSource: EventSource, id: String?, type: String?, data: String) {
                if (data.trim() == "[DONE]") {
                    Log.d(TAG, "SSE stream complete ([DONE])")
                    close()
                    return
                }

                for (piece in parseChatChunk(json, data)) trySend(piece)
            }

            override fun onClosed(eventSource: EventSource) {
                Log.d(TAG, "SSE stream closed")
                close()
            }

            override fun onFailure(eventSource: EventSource, t: Throwable?, response: Response?) {
                Log.e(TAG, "SSE stream failed: ${t?.message}, response code: ${response?.code}", t)
                val errMsg = t?.message ?: "Stream failed with HTTP ${response?.code}"
                close(IOException(errMsg, t))
            }
        })

        awaitClose {
            Log.d(TAG, "Cancelling SSE stream")
            eventSource.cancel()
        }
    }

    suspend fun fetchHistory(session: String = "dl-ai-code"): List<ChatMessage> =
        kotlinx.coroutines.withContext(kotlinx.coroutines.Dispatchers.IO) {
            try {
                val request = networkClient.newAuthenticatedRequestBuilder("/v1/ray/history?session=$session")
                    .get()
                    .build()
                val response = networkClient.okHttpClient.newCall(request).execute()
                if (response.isSuccessful) {
                    val body = response.body?.string() ?: "{}"
                    val root = json.parseToJsonElement(body).jsonObject
                    val msgsArray = root["messages"]?.jsonArray
                    msgsArray?.mapNotNull { el ->
                        val obj = el.jsonObject
                        val role = obj["role"]?.jsonPrimitive?.content ?: "user"
                        val content = obj["content"]?.jsonPrimitive?.content ?: ""
                        if (content.isNotBlank()) ChatMessage(role, content) else null
                    } ?: emptyList()
                } else {
                    Log.w(TAG, "Failed to fetch history: HTTP ${response.code}")
                    emptyList()
                }
            } catch (e: Exception) {
                Log.w(TAG, "Error fetching session history", e)
                emptyList()
            }
        }

    fun observeSessionEvents(session: String = "dl-ai-code"): Flow<SessionEvent> = callbackFlow {
        val request = networkClient.newAuthenticatedRequestBuilder("/api/code/session/events?session=$session")
            .header("Accept", "text/event-stream")
            .build()

        val factory = EventSources.createFactory(networkClient.okHttpClient)
        val eventSource = factory.newEventSource(request, object : EventSourceListener() {
            override fun onOpen(eventSource: EventSource, response: Response) {
                Log.d(TAG, "Session events stream opened: HTTP ${response.code}")
            }

            override fun onEvent(eventSource: EventSource, id: String?, type: String?, data: String) {
                try {
                    val root = json.parseToJsonElement(data).jsonObject
                    val evType = root["type"]?.jsonPrimitive?.content ?: ""
                    when (evType) {
                        "cleared" -> trySend(SessionEvent.Cleared)
                        "turn_end" -> trySend(SessionEvent.TurnEnd)
                        "hello" -> trySend(SessionEvent.Hello)
                        else -> trySend(SessionEvent.Other(evType))
                    }
                } catch (_: Exception) {
                    // Ignored (e.g. comment pings ": ping")
                }
            }

            override fun onFailure(eventSource: EventSource, t: Throwable?, response: Response?) {
                Log.w(TAG, "Session events stream failure: ${t?.message}, HTTP ${response?.code}")
                close(t)
            }

            override fun onClosed(eventSource: EventSource) {
                Log.d(TAG, "Session events stream closed")
                close()
            }
        })

        awaitClose {
            eventSource.cancel()
        }
    }
}
