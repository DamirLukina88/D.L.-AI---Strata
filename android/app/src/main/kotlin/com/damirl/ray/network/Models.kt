package com.damirl.ray.network

import kotlinx.serialization.Serializable

@Serializable
data class ChatMessage(
    val role: String,
    val content: String
)

@Serializable
data class ChatRequest(
    val messages: List<ChatMessage>,
    val stream: Boolean = true,
    val max_tokens: Int? = null,
    val voice: Boolean = false
)

sealed interface NetworkRoute {
    val displayName: String

    data class Lan(val url: String) : NetworkRoute {
        override val displayName: String = "Home LAN ($url)"
    }

    data class Remote(val url: String) : NetworkRoute {
        override val displayName: String = "Cloudflare Tunnel ($url)"
    }

    data object Offline : NetworkRoute {
        override val displayName: String = "Offline (No route to server)"
    }
}
